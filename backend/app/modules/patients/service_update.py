"""
PrescpHealth Backend — Patient Update Service.

Contains the update_patient() logic extracted from PatientService.
Handles updating patient fields with diff computation, versioning,
and audit logging.

Extracted from service.py to comply with the ~150 lines of logic per
file rule. The PatientService orchestrator delegates to this module.

HIPAA Compliance:
- Never logs PHI values (only field names that changed)
- Every update creates an immutable version record with diff
- Every update logs to the audit trail
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
from app.modules.patients.serialization import compute_diff, patient_to_snapshot
from app.modules.patients.versioning import create_version

# ---------------------------------------------------------------------------
# Module logger — logs patient operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


async def update_patient(
    db: AsyncSession,
    patient: Patient,
    user_id: uuid.UUID,
    data: dict[str, Any],
    audit_service: AuditService,
) -> Patient:
    """
    Update patient fields and create a new version with diff.

    Flow:
    1. Snapshot the current state (before changes)
    2. Apply field updates
    3. Snapshot the new state (after changes)
    4. Compute diff between old and new
    5. Create version record with diff and new snapshot
    6. Log to audit trail
    7. Commit transaction

    Args:
        db: Database session (tenant-scoped via RLS).
        patient: The Patient model instance to update (already loaded).
        user_id: UUID of the user making the change.
        data: Dict of field names to new values (partial update).
        audit_service: AuditService instance for HIPAA audit logging.

    Returns:
        The updated Patient model instance.

    Raises:
        DuplicateMRNError: If new MRN conflicts with existing.
    """
    # Snapshot BEFORE applying changes (for diff computation)
    old_snapshot = patient_to_snapshot(patient)

    # Apply updates to the model
    for field, value in data.items():
        if hasattr(patient, field):
            setattr(patient, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_patient_tenant_mrn" in str(exc.orig):
            raise DuplicateMRNError(data.get("medical_record_number", ""))
        raise

    # Snapshot AFTER changes
    new_snapshot = patient_to_snapshot(patient)

    # Compute what actually changed
    changes = compute_diff(old_snapshot, new_snapshot)

    # Only create a version if something actually changed
    if changes:
        await create_version(
            db=db,
            tenant_id=patient.tenant_id,
            patient_id=patient.id,
            user_id=user_id,
            change_type=PatientChangeType.UPDATE,
            changes=changes,
            snapshot=new_snapshot,
        )

        # Audit log with field names that changed (not values — no PHI)
        await audit_service.log(
            db=db,
            tenant_id=patient.tenant_id,
            user_id=user_id,
            action="patient.update",
            resource_type="patient",
            resource_id=patient.id,
            changes={"fields_changed": list(changes.keys())},
        )

    await db.commit()

    logger.info(
        "patient_updated",
        patient_id=str(patient.id),
        fields_changed=list(changes.keys()) if changes else [],
    )

    return patient
