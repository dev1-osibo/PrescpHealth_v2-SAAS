"""
PrescpHealth Backend — Prescription Service (Orchestrator).

Central service for prescription lifecycle management. Coordinates:
- ATC code validation via CodeCatalogService
- Drug interaction checks via DDI stub (wired to real engine in Task 12)
- Prescription CRUD with status transitions
- Domain event publishing (PrescriptionWritten)
- Audit logging for all CUD operations

Business Rules:
    - ATC code must be valid and active in the code catalog
    - Contraindicated interactions block unless acknowledged with justification
    - Status transitions follow defined state machine (see enums.py)
    - All operations are audit-logged with prescription_id only (no PHI)

HIPAA Compliance:
    - NEVER log drug names, dosages, or frequencies
    - Only log prescription_id (opaque UUID) in audit and application logs
    - PHI is stored in the database but never appears in log output

Usage:
    from app.modules.prescriptions.service import PrescriptionService

    svc = PrescriptionService()
    prescription = await svc.write_prescription(db, tenant_id, ...)
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import PrescriptionWritten, event_bus
from app.core.request_context import get_request_id
from app.modules.audit.service import AuditService
from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.service import CodeCatalogService
from app.modules.prescriptions.ddi_stub import check_drug_interactions
from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InteractionBlockedError,
    InvalidPrescriptionStatusError,
    PrescriptionNotFoundError,
)
from app.modules.prescriptions.prescription_model import Prescription

# ---------------------------------------------------------------------------
# Module logger — logs prescription operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Shared service instances
_audit = AuditService()
_code_catalog = CodeCatalogService()


class PrescriptionService:
    """
    Orchestrates prescription lifecycle operations.

    Handles writing, reading, discontinuing, holding, and resuming
    prescriptions. Integrates with code validation and DDI checking
    on write, and publishes domain events for cross-module reactions.
    """

    # -----------------------------------------------------------------------
    # Write Prescription
    # -----------------------------------------------------------------------
    async def write_prescription(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        encounter_id: uuid.UUID | None,
        drug_data: dict,
    ) -> Prescription:
        """
        Write a new prescription with ATC validation and DDI check.

        Flow:
        1. Validate ATC code against code catalog
        2. Fetch patient's active medications (ATC codes)
        3. Check drug interactions via DDI engine
        4. If Contraindicated and not acknowledged → raise InteractionBlockedError
        5. Create prescription record
        6. Publish PrescriptionWritten event
        7. Audit log the creation

        Args:
            db: Async database session.
            tenant_id: Tenant UUID for RLS context.
            patient_id: Patient receiving the medication.
            user_id: Doctor writing the prescription.
            encounter_id: Originating encounter (nullable).
            drug_data: Dict with keys: drug_name, atc_code, dosage,
                frequency, duration_days, route, refills_allowed,
                interaction_acknowledged, interaction_justification.

        Returns:
            The created Prescription model instance.

        Raises:
            InvalidCodeError: If ATC code is invalid or inactive.
            InteractionBlockedError: If Contraindicated DDI without ack.
        """
        atc_code = drug_data["atc_code"]

        # Step 1: Validate ATC code exists and is active
        await _code_catalog.validate_code(db, CatalogType.ATC, atc_code)

        # Step 2: Get patient's active medication ATC codes for DDI check
        active_meds = await self._get_active_medication_codes(
            db, patient_id
        )

        # Step 3: Check drug interactions (stub — returns [] for now)
        interactions = await check_drug_interactions(
            patient_id=patient_id,
            atc_code=atc_code,
            active_medications=active_meds,
        )

        # Step 4: Block if Contraindicated and not acknowledged
        contraindicated = [
            i for i in interactions
            if i.get("severity") == "Contraindicated"
        ]
        if contraindicated and not drug_data.get("interaction_acknowledged"):
            raise InteractionBlockedError(
                interaction_details=contraindicated
            )

        # Step 5: Create the prescription record
        prescription = Prescription(
            tenant_id=tenant_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            drug_name=drug_data["drug_name"],
            atc_code=atc_code,
            dosage=drug_data["dosage"],
            frequency=drug_data["frequency"],
            duration_days=drug_data.get("duration_days"),
            route=drug_data["route"],
            status=PrescriptionStatus.ACTIVE,
            refills_allowed=drug_data.get("refills_allowed", 0),
            refills_remaining=drug_data.get("refills_allowed", 0),
            prescribed_by=user_id,
            interaction_acknowledged=drug_data.get(
                "interaction_acknowledged", False
            ),
            interaction_justification=drug_data.get(
                "interaction_justification"
            ),
        )
        db.add(prescription)
        await db.flush()

        # Step 6: Publish PrescriptionWritten domain event
        await event_bus.publish(
            PrescriptionWritten(
                correlation_id=get_request_id() or str(uuid.uuid4()),
                tenant_id=tenant_id,
                patient_id=patient_id,
                prescription_id=prescription.id,
                encounter_id=encounter_id,
            )
        )

        # Step 7: Audit log — prescription_id only, no PHI
        await _audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="prescription.create",
            resource_type="prescription",
            resource_id=prescription.id,
        )

        logger.info(
            "prescription_written",
            prescription_id=str(prescription.id),
            patient_id=str(patient_id),
        )

        return prescription

    # -----------------------------------------------------------------------
    # Get Prescription (with dispensing history)
    # -----------------------------------------------------------------------
    async def get_prescription(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
    ) -> Prescription:
        """
        Retrieve a prescription with its dispensing history.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription.

        Returns:
            Prescription with dispensings eagerly loaded.

        Raises:
            PrescriptionNotFoundError: If not found.
        """
        stmt = (
            select(Prescription)
            .options(selectinload(Prescription.dispensings))
            .where(Prescription.id == prescription_id)
        )
        result = await db.execute(stmt)
        prescription = result.scalar_one_or_none()

        if prescription is None:
            raise PrescriptionNotFoundError(str(prescription_id))

        return prescription

    # -----------------------------------------------------------------------
    # Discontinue Prescription
    # -----------------------------------------------------------------------
    async def discontinue_prescription(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> Prescription:
        """
        Discontinue an active or on_hold prescription.

        Records who discontinued, when, and why. The prescription
        cannot be refilled after discontinuation.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription.
            user_id: UUID of the clinician discontinuing.
            reason: Clinical reason for discontinuation (stored, not logged).

        Returns:
            Updated Prescription.

        Raises:
            PrescriptionNotFoundError: If not found.
            InvalidPrescriptionStatusError: If already completed/discontinued.
        """
        prescription = await self._get_prescription(db, prescription_id)

        # Can discontinue from active or on_hold
        allowed = {PrescriptionStatus.ACTIVE, PrescriptionStatus.ON_HOLD}
        if prescription.status not in allowed:
            raise InvalidPrescriptionStatusError(
                prescription_id=str(prescription_id),
                current_status=prescription.status,
                required_status="active or on_hold",
                operation="discontinue",
            )

        prescription.status = PrescriptionStatus.DISCONTINUED
        prescription.discontinued_by = user_id
        prescription.discontinued_at = datetime.now(timezone.utc)
        prescription.discontinuation_reason = reason
        await db.flush()

        # Audit log — no PHI (reason is stored but not logged)
        await _audit.log(
            db=db,
            tenant_id=prescription.tenant_id,
            user_id=user_id,
            action="prescription.discontinue",
            resource_type="prescription",
            resource_id=prescription.id,
        )

        logger.info(
            "prescription_discontinued",
            prescription_id=str(prescription_id),
        )

        return prescription

    # -----------------------------------------------------------------------
    # Hold Prescription
    # -----------------------------------------------------------------------
    async def hold_prescription(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Prescription:
        """
        Place an active prescription on hold.

        Temporarily pauses the prescription (e.g., pending interaction
        review or patient request). Can be resumed later.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription.
            user_id: UUID of the clinician placing on hold.

        Returns:
            Updated Prescription.

        Raises:
            PrescriptionNotFoundError: If not found.
            InvalidPrescriptionStatusError: If not currently active.
        """
        prescription = await self._get_prescription(db, prescription_id)

        if prescription.status != PrescriptionStatus.ACTIVE:
            raise InvalidPrescriptionStatusError(
                prescription_id=str(prescription_id),
                current_status=prescription.status,
                required_status=PrescriptionStatus.ACTIVE.value,
                operation="hold",
            )

        prescription.status = PrescriptionStatus.ON_HOLD
        await db.flush()

        await _audit.log(
            db=db,
            tenant_id=prescription.tenant_id,
            user_id=user_id,
            action="prescription.hold",
            resource_type="prescription",
            resource_id=prescription.id,
        )

        logger.info(
            "prescription_held",
            prescription_id=str(prescription_id),
        )

        return prescription

    # -----------------------------------------------------------------------
    # Resume Prescription
    # -----------------------------------------------------------------------
    async def resume_prescription(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Prescription:
        """
        Resume a prescription that is currently on hold.

        Only prescriptions with status=on_hold can be resumed.
        Sets status back to active.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription.
            user_id: UUID of the clinician resuming.

        Returns:
            Updated Prescription.

        Raises:
            PrescriptionNotFoundError: If not found.
            InvalidPrescriptionStatusError: If not on_hold.
        """
        prescription = await self._get_prescription(db, prescription_id)

        if prescription.status != PrescriptionStatus.ON_HOLD:
            raise InvalidPrescriptionStatusError(
                prescription_id=str(prescription_id),
                current_status=prescription.status,
                required_status=PrescriptionStatus.ON_HOLD.value,
                operation="resume",
            )

        prescription.status = PrescriptionStatus.ACTIVE
        await db.flush()

        await _audit.log(
            db=db,
            tenant_id=prescription.tenant_id,
            user_id=user_id,
            action="prescription.resume",
            resource_type="prescription",
            resource_id=prescription.id,
        )

        logger.info(
            "prescription_resumed",
            prescription_id=str(prescription_id),
        )

        return prescription

    # -----------------------------------------------------------------------
    # List Patient Prescriptions (paginated)
    # -----------------------------------------------------------------------
    async def list_patient_prescriptions(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        status_filter: PrescriptionStatus | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Prescription]:
        """
        List prescriptions for a patient with optional status filter.

        Returns paginated results ordered by creation date (newest first).
        Uses the (tenant_id, patient_id, status) index for performance.

        Args:
            db: Async database session.
            patient_id: UUID of the patient.
            status_filter: Optional status to filter by (e.g., only active).
            limit: Max results per page (default 25, max 100).
            offset: Number of records to skip for pagination.

        Returns:
            List of Prescription records matching the criteria.
        """
        # Clamp limit to max 100 per API design standards
        limit = min(limit, 100)

        stmt = (
            select(Prescription)
            .where(Prescription.patient_id == patient_id)
            .order_by(Prescription.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        # Apply optional status filter
        if status_filter is not None:
            stmt = stmt.where(Prescription.status == status_filter)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------
    async def _get_prescription(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
    ) -> Prescription:
        """
        Fetch a prescription by ID or raise PrescriptionNotFoundError.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription.

        Returns:
            The Prescription model instance.

        Raises:
            PrescriptionNotFoundError: If not found.
        """
        stmt = select(Prescription).where(
            Prescription.id == prescription_id
        )
        result = await db.execute(stmt)
        prescription = result.scalar_one_or_none()

        if prescription is None:
            raise PrescriptionNotFoundError(str(prescription_id))

        return prescription

    async def _get_active_medication_codes(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> list[str]:
        """
        Get ATC codes of all active prescriptions for a patient.

        Used to check drug interactions against the patient's current
        medication regimen before writing a new prescription.

        Args:
            db: Async database session.
            patient_id: UUID of the patient.

        Returns:
            List of ATC code strings for active prescriptions.
        """
        stmt = (
            select(Prescription.atc_code)
            .where(
                Prescription.patient_id == patient_id,
                Prescription.status == PrescriptionStatus.ACTIVE,
            )
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]
