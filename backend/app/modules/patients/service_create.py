"""
PrescpHealth Backend — Patient Create Service.

Contains the create_patient() logic extracted from PatientService.
Handles creating a new patient record with initial version and audit log.

Extracted from service.py to comply with the ~150 lines of logic per
file rule. The PatientService orchestrator delegates to this module.

HIPAA Compliance:
- Never logs PHI (only patient_id UUID in log messages)
- Every creation creates an immutable version record
- Every creation logs to the audit trail
- RLS enforces tenant isolation at the database level
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.patients.enums import PatientChangeType
from app.modules.patients.exceptions import DuplicateMRNError
from app.modules.patients.patient_model import Patient
from app.modules.patients.serialization import patient_to_snapshot
from app.modules.patients.versioning import create_version

# ---------------------------------------------------------------------------
# Module logger — logs patient operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


async def create_patient(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: dict[str, Any],
    audit_service: AuditService,
) -> Patient:
    """
    Create a new patient record with initial version.

    Flow:
    1. Create Patient model instance
    2. Flush to get the generated ID
    3. Create version 1 (change_type=create, full snapshot)
    4. Log to audit trail
    5. Commit transaction

    Args:
        db: Database session (tenant-scoped via RLS).
        tenant_id: Tenant UUID for the new patient.
        user_id: UUID of the user creating the patient.
        data: Patient field values (validated by caller/schema).
        audit_service: AuditService instance for HIPAA audit logging.

    Returns:
        The created Patient model instance.

    Raises:
        DuplicateMRNError: If MRN already exists for this tenant.
    """
    # Build the patient model from provided data
    patient = Patient(
        tenant_id=tenant_id,
        created_by=user_id,
        **data,
    )

    db.add(patient)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Check if it's a duplicate MRN violation
        if "uq_patient_tenant_mrn" in str(exc.orig):
            raise DuplicateMRNError(data.get("medical_record_number", ""))
        raise

    # Create initial version (version 1) with full snapshot
    snapshot = patient_to_snapshot(patient)
    await create_version(
        db=db,
        tenant_id=tenant_id,
        patient_id=patient.id,
        user_id=user_id,
        change_type=PatientChangeType.CREATE,
        changes={},  # No diff for creation — snapshot IS the initial state
        snapshot=snapshot,
    )

    # Audit log — HIPAA requirement for all CUD operations
    await audit_service.log(
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="patient.create",
        resource_type="patient",
        resource_id=patient.id,
    )

    await db.commit()

    logger.info(
        "patient_created",
        patient_id=str(patient.id),
        tenant_id=str(tenant_id),
    )

    return patient
