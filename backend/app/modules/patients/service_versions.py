"""
PrescpHealth Backend — Patient Versioning Service Delegation.

Contains get_patient_versions(), get_patient_at_version(), and
get_patient_timeline() logic extracted from PatientService.

Extracted from service.py to comply with the ~150 lines of logic per
file rule. The PatientService orchestrator delegates to this module.

These methods provide:
- Complete version history for a patient
- Point-in-time recovery (snapshot at specific version)
- Timeline view (formatted version history as events)
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.patients.enums import PatientChangeType
from app.modules.patients.versioning import get_version_at, get_versions

# ---------------------------------------------------------------------------
# Module logger — logs versioning operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


async def get_patient_versions(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list:
    """
    Get all version records for a patient.

    Returns the complete version history ordered newest first.
    Each version includes: version_number, change_type, changes,
    snapshot, changed_by, changed_at.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient.

    Returns:
        List of PatientVersion records, newest first.
    """
    return await get_versions(db, patient_id)


async def get_patient_at_version(
    db: AsyncSession,
    patient_id: uuid.UUID,
    version_number: int,
):
    """
    Get the patient snapshot at a specific version number.

    Used for point-in-time recovery — returns the full patient
    state as it existed at that version.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient.
        version_number: The version to retrieve (1-based).

    Returns:
        PatientVersion record with snapshot at that version.

    Raises:
        PatientVersionNotFoundError: If version number doesn't exist.
    """
    return await get_version_at(db, patient_id, version_number)


async def get_patient_timeline(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """
    Get the patient timeline as a list of events.

    Currently returns version history formatted as timeline events.
    Will be extended in future phases to include:
    - Measurements recorded
    - Risk score computations
    - Alerts generated
    - AI assistant interactions

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient.

    Returns:
        List of timeline event dicts, newest first.
        Each event has: type, timestamp, description, metadata.
    """
    # Get version history as timeline events
    versions = await get_versions(db, patient_id)

    timeline_events: list[dict[str, Any]] = []
    for version in versions:
        event = {
            "type": "profile_change",
            "subtype": version.change_type.value,
            "timestamp": version.changed_at.isoformat(),
            "version_number": version.version_number,
            "changed_by": str(version.changed_by),
            "description": _describe_change(
                version.change_type, version.changes
            ),
        }
        timeline_events.append(event)

    return timeline_events


def _describe_change(
    change_type: PatientChangeType,
    changes: dict[str, Any],
) -> str:
    """
    Generate a human-readable description of a patient change.

    Used in timeline display to summarize what happened without
    exposing PHI values. Only mentions field names, not values.

    Args:
        change_type: The type of change (create, update, etc.).
        changes: The diff dict ({field: {old, new}}).

    Returns:
        Human-readable description string.
    """
    if change_type == PatientChangeType.CREATE:
        return "Patient record created"
    elif change_type == PatientChangeType.SOFT_DELETE:
        return "Patient record deleted"
    elif change_type == PatientChangeType.RESTORE:
        return "Patient record restored"
    elif change_type == PatientChangeType.UPDATE:
        field_count = len(changes)
        field_names = ", ".join(changes.keys())
        return f"Updated {field_count} field(s): {field_names}"
    return "Unknown change"
