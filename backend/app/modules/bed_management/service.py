"""
PrescpHealth Backend — Bed Management Service (Core Operations).

Handles patient admission, discharge, transfer, and bed availability queries.

HIPAA:
    - reason/notes/discharge_plan are PHI — never logged (only IDs appear in logs).
    - All mutations are audit-logged via AuditService.

Usage:
    from app.modules.bed_management.service import BedManagementService
    svc = BedManagementService()
    admission = await svc.admit_patient(db, data, tenant_id, doctor_id)
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.audit.service import AuditService
from app.modules.bed_management.enums import (
    AdmissionStatus,
    BedStatus,
    DischargeType,
    NoteType,
)
from app.modules.bed_management.exceptions import (
    AdmissionAlreadyDischargedError,
    AdmissionNotFoundError,
    BedNotAvailableError,
    BedNotFoundError,
)
from app.modules.bed_management.models import Admission, Bed
from app.modules.bed_management.schemas import (
    AdmitPatientRequest,
    DischargeRequest,
)

logger = structlog.get_logger(__name__)
_audit = AuditService()


class BedManagementService:
    """Core service: admissions, discharges, transfers, bed availability."""

    async def admit_patient(
        self,
        db: AsyncSession,
        data: AdmitPatientRequest,
        tenant_id: uuid.UUID,
        doctor_id: uuid.UUID,
    ) -> Admission:
        """
        Admit a patient to a bed.

        1. Verify the bed exists and is AVAILABLE.
        2. Set bed status to OCCUPIED.
        3. Create Admission record in ACTIVE status.
        4. Audit-log the action.

        Raises:
            BedNotFoundError: Bed doesn't exist or hidden by RLS.
            BedNotAvailableError: Bed is not in AVAILABLE status.
        """
        bed = await self._load_bed(db, data.bed_id)

        # Guard: bed must be available before admission
        if bed.status != BedStatus.AVAILABLE:
            raise BedNotAvailableError(data.bed_id, bed.status.value)

        # Mark bed as occupied — atomic with the admission creation
        bed.status = BedStatus.OCCUPIED

        admission = Admission(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            patient_id=data.patient_id,
            bed_id=data.bed_id,
            encounter_id=data.encounter_id,
            admitting_doctor_id=doctor_id,
            admitted_at=datetime.now(timezone.utc),
            status=AdmissionStatus.ACTIVE,
            reason=data.reason,  # PHI — stored, never logged
            notes=data.notes,
        )
        db.add(admission)
        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=doctor_id,
            action="admission.create", resource_type="admission",
            resource_id=admission.id,
            changes={"bed_id": str(data.bed_id)},
        )
        logger.info("patient_admitted", admission_id=str(admission.id), tenant_id=str(tenant_id))
        return admission

    async def discharge_patient(
        self,
        db: AsyncSession,
        admission_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: DischargeRequest,
    ) -> Admission:
        """
        Discharge a patient from their current bed.

        1. Load and validate admission is ACTIVE.
        2. Generate discharge plan.
        3. Set bed back to AVAILABLE.
        4. Set admission status to DISCHARGED.

        Raises:
            AdmissionNotFoundError: Admission doesn't exist.
            AdmissionAlreadyDischargedError: Already discharged.
        """
        admission = await self._load_active_admission(db, admission_id)

        # Free the bed — critical for bed turnover
        bed = await self._load_bed(db, admission.bed_id)
        bed.status = BedStatus.AVAILABLE

        admission.discharged_at = datetime.now(timezone.utc)
        admission.discharge_type = data.discharge_type
        admission.status = AdmissionStatus.DISCHARGED
        # Merge caller-provided discharge plan with generated summary
        admission.discharge_plan = self._build_discharge_plan(admission, data)
        if data.notes:
            admission.notes = data.notes

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="admission.discharge", resource_type="admission",
            resource_id=admission.id,
            changes={"discharge_type": data.discharge_type.value},
        )
        logger.info("patient_discharged", admission_id=str(admission_id), tenant_id=str(tenant_id))
        return admission

    async def transfer_patient(
        self,
        db: AsyncSession,
        admission_id: uuid.UUID,
        new_bed_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Admission:
        """
        Transfer a patient to a different bed.

        Frees old bed, sets new bed to OCCUPIED, updates admission.

        Raises:
            AdmissionNotFoundError: If admission not found.
            BedNotAvailableError: If destination bed is not AVAILABLE.
        """
        admission = await self._load_active_admission(db, admission_id)
        new_bed = await self._load_bed(db, new_bed_id)

        if new_bed.status != BedStatus.AVAILABLE:
            raise BedNotAvailableError(new_bed_id, new_bed.status.value)

        # Release old bed
        old_bed = await self._load_bed(db, admission.bed_id)
        old_bed.status = BedStatus.AVAILABLE

        # Occupy new bed
        new_bed.status = BedStatus.OCCUPIED
        admission.bed_id = new_bed_id
        admission.status = AdmissionStatus.ACTIVE  # Remains active, just moved

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="admission.transfer", resource_type="admission",
            resource_id=admission.id,
            changes={"new_bed_id": str(new_bed_id)},
        )
        return admission

    async def get_bed_availability(
        self,
        db: AsyncSession,
        ward_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Return bed availability counts and bed list for a ward.

        Returns:
            Dict with counts per status and a list of bed objects.
        """
        stmt = select(Bed).where(Bed.ward_id == ward_id)
        beds = list((await db.execute(stmt)).scalars())

        counts: dict[str, int] = {
            "available": 0, "occupied": 0, "maintenance": 0, "reserved": 0,
        }
        for bed in beds:
            status_val = bed.status.value if hasattr(bed.status, "value") else bed.status
            if status_val in counts:
                counts[status_val] += 1

        return {"ward_id": str(ward_id), "counts": counts, "beds": beds}

    async def get_ward_overview(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """
        Return all wards with per-status bed counts for the tenant.

        Used by the bed management dashboard.
        """
        from app.modules.bed_management.models import Ward

        ward_stmt = select(Ward).where(Ward.tenant_id == tenant_id, Ward.is_active.is_(True))
        wards = list((await db.execute(ward_stmt)).scalars())

        overview = []
        for ward in wards:
            avail = await self.get_bed_availability(db, ward.id)
            overview.append({
                "ward_id": str(ward.id),
                "ward_name": ward.name,
                "floor": ward.floor,
                "specialty": ward.specialty,
                **avail["counts"],
            })
        return overview

    async def get_admission(
        self, db: AsyncSession, admission_id: uuid.UUID
    ) -> Admission:
        """
        Retrieve an admission with nursing notes eagerly loaded.

        Raises:
            AdmissionNotFoundError: If not found.
        """
        stmt = (
            select(Admission)
            .where(Admission.id == admission_id)
            .options(selectinload(Admission.nursing_notes))
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        if result is None:
            raise AdmissionNotFoundError(admission_id)
        return result

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _load_bed(self, db: AsyncSession, bed_id: uuid.UUID) -> Bed:
        """Load bed by PK; raise BedNotFoundError if missing."""
        result = (
            await db.execute(select(Bed).where(Bed.id == bed_id))
        ).scalar_one_or_none()
        if result is None:
            raise BedNotFoundError(bed_id)
        return result

    async def _load_active_admission(
        self, db: AsyncSession, admission_id: uuid.UUID
    ) -> Admission:
        """
        Load an admission that must be in ACTIVE status.

        Raises:
            AdmissionNotFoundError: If not found.
            AdmissionAlreadyDischargedError: If already discharged.
        """
        result = (
            await db.execute(select(Admission).where(Admission.id == admission_id))
        ).scalar_one_or_none()
        if result is None:
            raise AdmissionNotFoundError(admission_id)
        if result.status == AdmissionStatus.DISCHARGED:
            raise AdmissionAlreadyDischargedError(admission_id)
        return result

    def _build_discharge_plan(
        self, admission: Admission, data: DischargeRequest
    ) -> dict[str, Any]:
        """
        Build the discharge plan JSONB from admission context.

        Merges caller-provided plan with generated metadata.
        """
        plan: dict[str, Any] = {
            "admission_id": str(admission.id),
            "discharge_type": data.discharge_type.value,
            "discharged_at": datetime.now(timezone.utc).isoformat(),
            "follow_up_instructions": None,  # Clinician-filled via FHIR or UI
        }
        # Merge caller-provided plan data (may include follow-up instructions)
        if data.discharge_plan:
            plan.update(data.discharge_plan)
        return plan
