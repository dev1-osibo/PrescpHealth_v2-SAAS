"""
PrescpHealth Backend — Diagnosis Service.

Handles recording coded diagnoses for encounters with ICD-10 validation
and chronic condition synchronization to the patient record.

Key Responsibilities:
- Validate ICD-10 codes via CodeCatalogService before persistence
- Record diagnoses linked to encounters and patients
- Sync chronic conditions to patient.chronic_conditions JSONB
- Audit log all diagnosis operations (without PHI content)

HIPAA Compliance:
- NEVER log diagnosis details (icd10_code + patient = PHI)
- Only log diagnosis_id (UUID) and action metadata
- Audit trail captures the action but not the clinical content

Integration Points:
- CodeCatalogService: Validates ICD-10 codes exist and are active
- Patient model: Updates chronic_conditions JSONB for chronic diagnoses
- AuditService: Logs all CUD operations

Usage:
    from app.modules.encounters.service_diagnosis import DiagnosisService

    dx_service = DiagnosisService()
    diagnosis = await dx_service.record_diagnosis(db, encounter_id, ...)
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.service import CodeCatalogService
from app.modules.encounters.diagnosis_model import Diagnosis
from app.modules.encounters.encounter_model import Encounter
from app.modules.encounters.enums import EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
)

# ---------------------------------------------------------------------------
# Module logger — NEVER log diagnosis details (PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Service instances
_audit = AuditService()
_code_catalog = CodeCatalogService()


class DiagnosisService:
    """
    Service for recording and managing coded clinical diagnoses.

    Each diagnosis is validated against the ICD-10 code catalog before
    persistence. If marked as chronic, the diagnosis is also synced to
    the patient's chronic_conditions JSONB field for longitudinal tracking.

    This dual-write pattern ensures:
    1. Encounter-level: Complete record of what was diagnosed during the visit
    2. Patient-level: Running list of chronic conditions for risk computation
    """

    async def record_diagnosis(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
        patient_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        icd10_code: str,
        is_chronic: bool = False,
        is_primary: bool = False,
    ) -> Diagnosis:
        """
        Record a coded diagnosis for an encounter.

        Workflow:
        1. Validate encounter is modifiable (not completed)
        2. Validate ICD-10 code via CodeCatalogService
        3. Look up display name for the code
        4. Create Diagnosis record
        5. If chronic, sync to patient.chronic_conditions JSONB
        6. Audit log the action

        Args:
            db: Async database session.
            encounter_id: Parent encounter UUID.
            patient_id: Patient UUID (for chronic condition sync).
            tenant_id: Tenant context for RLS isolation.
            user_id: Clinician recording the diagnosis.
            icd10_code: ICD-10 code string (e.g., "E11.9").
            is_chronic: Whether this is a chronic condition.
            is_primary: Whether this is the primary diagnosis.

        Returns:
            The newly created Diagnosis instance.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist.
            EncounterAlreadyCompletedError: If encounter is completed.
            InvalidCodeError: If ICD-10 code is invalid or inactive.
        """
        # Step 1: Validate encounter is modifiable
        await self._validate_encounter_modifiable(db, encounter_id)

        # Step 2: Validate ICD-10 code exists and is active
        # Raises InvalidCodeError if code is invalid or inactive
        await _code_catalog.validate_code(db, CatalogType.ICD10, icd10_code)

        # Step 3: Look up display name for the validated code
        code_info = await _code_catalog.lookup_code(
            db, CatalogType.ICD10, icd10_code
        )
        display_name = code_info["display_name"]

        # Step 4: Create the diagnosis record
        diagnosis = Diagnosis(
            encounter_id=encounter_id,
            patient_id=patient_id,
            tenant_id=tenant_id,
            recorded_by=user_id,
            icd10_code=icd10_code,
            display_name=display_name,
            is_chronic=is_chronic,
            is_primary=is_primary,
        )

        db.add(diagnosis)
        await db.flush()

        # Step 5: Sync chronic condition to patient record if applicable
        if is_chronic:
            await self._sync_chronic_condition(
                db, patient_id, icd10_code, display_name
            )

        # Step 6: Audit log — NEVER log diagnosis content (PHI)
        await _audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="diagnosis.record",
            resource_type="diagnosis",
            resource_id=diagnosis.id,
        )

        logger.info(
            "diagnosis_recorded",
            diagnosis_id=str(diagnosis.id),
            encounter_id=str(encounter_id),
            tenant_id=str(tenant_id),
            is_chronic=is_chronic,
        )

        return diagnosis

    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------

    async def _validate_encounter_modifiable(
        self, db: AsyncSession, encounter_id: uuid.UUID
    ) -> None:
        """
        Ensure the encounter exists and is not in a terminal state.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist.
            EncounterAlreadyCompletedError: If encounter is completed.
        """
        stmt = select(Encounter.id, Encounter.status).where(
            Encounter.id == encounter_id
        )
        result = await db.execute(stmt)
        row = result.one_or_none()

        if row is None:
            raise EncounterNotFoundError(encounter_id)

        if row.status == EncounterStatus.COMPLETED:
            raise EncounterAlreadyCompletedError(encounter_id)

    async def _sync_chronic_condition(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        icd10_code: str,
        display_name: str,
    ) -> None:
        """
        Add a chronic condition to the patient's chronic_conditions JSONB.

        Uses a SELECT + conditional append pattern to avoid duplicates.
        If the ICD-10 code already exists in the patient's chronic conditions
        list, it is not added again (idempotent).

        This keeps the patient record's chronic_conditions in sync with
        diagnoses marked as chronic across all encounters.

        Args:
            db: Async database session.
            patient_id: Patient UUID to update.
            icd10_code: The ICD-10 code to add.
            display_name: Human-readable condition name.
        """
        # Import here to avoid circular dependency at module level
        from app.modules.patients.patient_model import Patient

        stmt = select(Patient).where(Patient.id == patient_id)
        result = await db.execute(stmt)
        patient = result.scalar_one_or_none()

        if patient is None:
            # Patient not found — log warning but don't crash the diagnosis flow
            logger.warning(
                "chronic_condition_sync_skipped",
                patient_id=str(patient_id),
                reason="patient_not_found",
            )
            return

        # Get current chronic conditions (default to empty list)
        conditions = list(patient.chronic_conditions or [])

        # Check for duplicate — don't add the same code twice
        existing_codes = {c.get("code") for c in conditions if isinstance(c, dict)}
        if icd10_code in existing_codes:
            return  # Already tracked — idempotent

        # Append the new chronic condition
        conditions.append({"code": icd10_code, "display_name": display_name})
        patient.chronic_conditions = conditions

        await db.flush()

        logger.info(
            "chronic_condition_synced",
            patient_id=str(patient_id),
            condition_count=len(conditions),
        )
