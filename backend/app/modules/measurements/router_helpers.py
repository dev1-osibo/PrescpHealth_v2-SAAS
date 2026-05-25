"""
PrescpHealth Backend — Measurement Router Serialization Helpers.

Provides serialization functions for converting Measurement SQLAlchemy
model instances to JSON-serializable dictionaries for API responses.

Design Decisions:
- UUID fields serialized as strings for JSON compatibility
- Datetime fields serialized as ISO-8601 strings
- None values preserved (not stripped) for explicit null representation
- Keeps router files focused on request handling, not serialization

HIPAA Note:
    These serialized dicts contain PHI (measurement values, notes).
    They are only used within router endpoints that have already
    passed RBAC checks, and responses include Cache-Control: no-store.
"""

from typing import Any

from app.modules.measurements.models import Measurement


def serialize_measurement(measurement: Measurement) -> dict[str, Any]:
    """
    Convert a Measurement SQLAlchemy model to a JSON-serializable dict.

    Handles UUID, datetime, and enum serialization.
    Matches the MeasurementResponse schema structure.

    Args:
        measurement: Measurement model instance from the database.

    Returns:
        Dict matching the MeasurementResponse schema fields.
    """
    return {
        "id": str(measurement.id),
        "tenant_id": str(measurement.tenant_id),
        "patient_id": str(measurement.patient_id),
        "measurement_type": measurement.measurement_type,
        "value": measurement.value,
        "unit": measurement.unit,
        "recorded_at": (
            measurement.recorded_at.isoformat()
            if measurement.recorded_at
            else None
        ),
        "recorded_by": str(measurement.recorded_by),
        "source": measurement.source,
        "is_validated": measurement.is_validated,
        "validated_by": (
            str(measurement.validated_by)
            if measurement.validated_by
            else None
        ),
        "validated_at": (
            measurement.validated_at.isoformat()
            if measurement.validated_at
            else None
        ),
        "is_flagged": measurement.is_flagged,
        "flag_reason": measurement.flag_reason,
        "notes": measurement.notes,
        "created_at": (
            measurement.created_at.isoformat()
            if getattr(measurement, "created_at", None)
            else None
        ),
        "updated_at": (
            measurement.updated_at.isoformat()
            if getattr(measurement, "updated_at", None)
            else None
        ),
    }
