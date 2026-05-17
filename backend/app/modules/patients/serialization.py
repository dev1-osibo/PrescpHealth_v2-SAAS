"""
PrescpHealth Backend — Patient Serialization Helpers.

Provides utilities for converting Patient model instances to/from
dictionary representations used in versioning (snapshots and diffs).

These helpers are critical for the versioning system:
- snapshot: Full patient state at a point in time (for recovery)
- diff: What changed between versions ({field: {old, new}})

Design Decisions:
- UUID fields serialized as strings for JSON compatibility
- Date/datetime fields serialized as ISO-8601 strings
- JSONB fields (allergies, conditions, etc.) stored as-is
- PHI fields ARE included in snapshots (they're stored in the same
  tenant-scoped, encrypted-at-rest table as the patient itself)
- Snapshots never leave the database without proper RBAC authorization

HIPAA Note:
    Snapshots contain PHI but are protected by:
    1. RLS (same tenant_id as the patient)
    2. Encryption at rest (PostgreSQL TDE)
    3. RBAC (only authorized roles can access version history)
    4. Audit logging (every access is recorded)
"""

from datetime import date, datetime
from typing import Any

from app.modules.patients.models import Patient


# ---------------------------------------------------------------------------
# Fields to include in patient snapshots
# ---------------------------------------------------------------------------
# These are the fields that represent the patient's state.
# Excludes: id, tenant_id, created_at, updated_at (metadata, not state)
SNAPSHOT_FIELDS: list[str] = [
    "medical_record_number",
    "first_name",
    "last_name",
    "date_of_birth",
    "gender",
    "phone_number",
    "email",
    "address",
    "emergency_contact",
    "blood_type",
    "allergies",
    "chronic_conditions",
    "current_medications",
    "insurance_info",
    "notes",
    "status",
    "created_by",
    "deleted_at",
]


def serialize_value(value: Any) -> Any:
    """
    Serialize a single field value for JSON storage.

    Handles type conversions needed for JSONB columns:
    - UUID -> string
    - date -> ISO string
    - datetime -> ISO string
    - Enum -> string value
    - None, str, int, float, list, dict -> as-is

    Args:
        value: The raw Python value from the model attribute.

    Returns:
        JSON-serializable representation of the value.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):
        # Enum types — serialize to their string value
        return value.value
    if hasattr(value, "hex"):
        # UUID types — serialize to string
        return str(value)
    # str, int, float, list, dict pass through unchanged
    return value


def patient_to_snapshot(patient: Patient) -> dict[str, Any]:
    """
    Create a full snapshot of the patient's current state.

    Used when creating a PatientVersion record. The snapshot captures
    every field value at this point in time, enabling point-in-time
    recovery without needing to replay all previous diffs.

    Args:
        patient: The Patient model instance to snapshot.

    Returns:
        Dict mapping field names to their serialized values.
    """
    snapshot: dict[str, Any] = {}
    for field in SNAPSHOT_FIELDS:
        raw_value = getattr(patient, field, None)
        snapshot[field] = serialize_value(raw_value)
    return snapshot


def compute_diff(
    old_snapshot: dict[str, Any],
    new_snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Compute the diff between two patient snapshots.

    Compares each field and records changes in the format:
    {field_name: {"old": old_value, "new": new_value}}

    Only fields that actually changed are included in the diff.
    This enables efficient audit queries ("what changed in this version?").

    Args:
        old_snapshot: The patient state before the change.
        new_snapshot: The patient state after the change.

    Returns:
        Dict of changed fields with their old and new values.
        Empty dict if nothing changed.
    """
    changes: dict[str, dict[str, Any]] = {}

    for field in SNAPSHOT_FIELDS:
        old_val = old_snapshot.get(field)
        new_val = new_snapshot.get(field)

        if old_val != new_val:
            changes[field] = {"old": old_val, "new": new_val}

    return changes
