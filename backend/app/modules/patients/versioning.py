"""
PrescpHealth Backend — Patient Versioning Service.

Manages the immutable version history for patient profile changes.
Every create, update, soft-delete, and restore operation creates a
PatientVersion record with:
- Sequential version number (per patient)
- Change type (create, update, soft_delete, restore)
- Diff of what changed ({field: {old, new}})
- Full snapshot of patient state at that point

This enables:
- Complete audit trail of all profile modifications
- Point-in-time recovery (restore patient to any previous state)
- Timeline view of patient history

HIPAA Compliance:
- Version records are IMMUTABLE (never updated or deleted)
- Protected by same RLS as the patient record
- Only patient_id UUID logged — never PHI
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.patients.exceptions import PatientVersionNotFoundError
from app.modules.patients.models import PatientChangeType, PatientVersion

# ---------------------------------------------------------------------------
# Module logger — logs versioning operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


async def get_next_version_number(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> int:
    """
    Get the next sequential version number for a patient.

    Version numbers are per-patient, starting at 1 for the initial
    creation. This provides a simple human-readable ordering
    independent of timestamps.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: The patient to get the next version for.

    Returns:
        The next version number (1 if no versions exist yet).
    """
    result = await db.execute(
        select(func.coalesce(func.max(PatientVersion.version_number), 0)).where(
            PatientVersion.patient_id == patient_id
        )
    )
    current_max = result.scalar_one()
    return current_max + 1


async def create_version(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    user_id: uuid.UUID,
    change_type: PatientChangeType,
    changes: dict[str, Any],
    snapshot: dict[str, Any],
) -> PatientVersion:
    """
    Create an immutable version record for a patient change.

    This is called by every CUD operation on a patient to maintain
    the complete audit/version history.

    Args:
        db: Database session (tenant-scoped via RLS).
        tenant_id: Tenant UUID for RLS.
        patient_id: The patient being versioned.
        user_id: The user who made the change.
        change_type: Type of change (create, update, soft_delete, restore).
        changes: Diff dict ({field: {old, new}}).
        snapshot: Full patient state at this version.

    Returns:
        The created PatientVersion record.
    """
    version_number = await get_next_version_number(db, patient_id)

    version = PatientVersion(
        tenant_id=tenant_id,
        patient_id=patient_id,
        version_number=version_number,
        changed_by=user_id,
        changed_at=datetime.now(timezone.utc),
        change_type=change_type,
        changes=changes,
        snapshot=snapshot,
    )

    db.add(version)
    await db.flush()

    logger.info(
        "patient_version_created",
        patient_id=str(patient_id),
        version_number=version_number,
        change_type=change_type.value,
    )

    return version


async def get_versions(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list[PatientVersion]:
    """
    Get all version records for a patient, ordered newest first.

    Returns the complete version history for timeline display
    and audit review.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: The patient to get versions for.

    Returns:
        List of PatientVersion records, newest first.
    """
    result = await db.execute(
        select(PatientVersion)
        .where(PatientVersion.patient_id == patient_id)
        .order_by(PatientVersion.version_number.desc())
    )
    return list(result.scalars().all())


async def get_version_at(
    db: AsyncSession,
    patient_id: uuid.UUID,
    version_number: int,
) -> PatientVersion:
    """
    Get a specific version record by version number.

    Used for point-in-time recovery — the snapshot field contains
    the full patient state at that version.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: The patient to look up.
        version_number: The specific version to retrieve.

    Returns:
        The PatientVersion record at that version number.

    Raises:
        PatientVersionNotFoundError: If the version doesn't exist.
    """
    result = await db.execute(
        select(PatientVersion).where(
            PatientVersion.patient_id == patient_id,
            PatientVersion.version_number == version_number,
        )
    )
    version = result.scalar_one_or_none()

    if version is None:
        raise PatientVersionNotFoundError(patient_id, version_number)

    return version
