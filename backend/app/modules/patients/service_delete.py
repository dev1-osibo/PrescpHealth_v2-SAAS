"""
PrescpHealth Backend — Patient Delete/Restore Service.

Contains soft_delete_patient() and restore_patient() logic extracted
from PatientService. Handles soft-deletion and restoration with
versioning and audit logging.

Extracted from service.py to comply with the ~150 lines of logic per
file rule. The PatientService orchestrator delegates to this module.

HIPAA Compliance:
- HIPAA requires 7-year retention — we never hard-delete patient data
- Soft-deleted patients are excluded from search by default
- Every delete/restore creates an immutable version record
- Every delete/restore logs to the audit trail
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.patients.enums import PatientChangeType
from app.modules.patients.exceptions import (
    PatientAlreadyDeletedError,
    PatientNotDeletedError,
)
from app.modules.patients.patient_model import Patient
from app.modules.patients.serialization import compute_diff, patient_to_snapshot
from app.modules.patients.versioning import create_version

# ---------------------------------------------------------------------------
# Module logger — logs patient operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


async def soft_delete_patient(
    db: AsyncSession,
    patient: Patient,
    user_id: uuid.UUID,
    audit_service: AuditService,
) -> Patient:
    """
    Soft-delete a patient (set deleted_at timestamp).

    HIPAA requires 7-year retention — we never hard-delete patient data.
    Soft-deleted patients are excluded from search by default but
    remain accessible for audit and compliance purposes.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient: The Patient model instance to delete (already loaded).
        user_id: UUID of the user performing the deletion.
        audit_service: AuditService instance for HIPAA audit logging.

    Returns:
        The soft-deleted Patient model instance.

    Raises:
        PatientAlreadyDeletedError: If already soft-deleted.
    """
    # Prevent double-deletion (would corrupt audit trail)
    if patient.deleted_at is not None:
        raise PatientAlreadyDeletedError(patient.id)

    # Snapshot before deletion
    old_snapshot = patient_to_snapshot(patient)

    # Apply soft delete
    patient.deleted_at = datetime.now(timezone.utc)

    await db.flush()

    # Snapshot after deletion
    new_snapshot = patient_to_snapshot(patient)
    changes = compute_diff(old_snapshot, new_snapshot)

    # Create version with soft_delete change type
    await create_version(
        db=db,
        tenant_id=patient.tenant_id,
        patient_id=patient.id,
        user_id=user_id,
        change_type=PatientChangeType.SOFT_DELETE,
        changes=changes,
        snapshot=new_snapshot,
    )

    # Audit log
    await audit_service.log(
        db=db,
        tenant_id=patient.tenant_id,
        user_id=user_id,
        action="patient.soft_delete",
        resource_type="patient",
        resource_id=patient.id,
    )

    await db.commit()

    logger.info("patient_soft_deleted", patient_id=str(patient.id))

    return patient


async def restore_patient(
    db: AsyncSession,
    patient: Patient,
    user_id: uuid.UUID,
    audit_service: AuditService,
) -> Patient:
    """
    Restore a soft-deleted patient (clear deleted_at).

    Reverses a soft-delete operation. The patient becomes visible
    in search results again and can be modified normally.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient: The Patient model instance to restore (already loaded).
        user_id: UUID of the user performing the restoration.
        audit_service: AuditService instance for HIPAA audit logging.

    Returns:
        The restored Patient model instance.

    Raises:
        PatientNotDeletedError: If patient isn't currently deleted.
    """
    # Can only restore a deleted patient
    if patient.deleted_at is None:
        raise PatientNotDeletedError(patient.id)

    # Snapshot before restore
    old_snapshot = patient_to_snapshot(patient)

    # Clear the soft-delete marker
    patient.deleted_at = None

    await db.flush()

    # Snapshot after restore
    new_snapshot = patient_to_snapshot(patient)
    changes = compute_diff(old_snapshot, new_snapshot)

    # Create version with restore change type
    await create_version(
        db=db,
        tenant_id=patient.tenant_id,
        patient_id=patient.id,
        user_id=user_id,
        change_type=PatientChangeType.RESTORE,
        changes=changes,
        snapshot=new_snapshot,
    )

    # Audit log
    await audit_service.log(
        db=db,
        tenant_id=patient.tenant_id,
        user_id=user_id,
        action="patient.restore",
        resource_type="patient",
        resource_id=patient.id,
    )

    await db.commit()

    logger.info("patient_restored", patient_id=str(patient.id))

    return patient
