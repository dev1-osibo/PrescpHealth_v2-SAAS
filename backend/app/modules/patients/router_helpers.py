"""
PrescpHealth Backend — Patient Router Serialization Helpers.

Provides serialization functions for converting SQLAlchemy model instances
to JSON-serializable dictionaries for API responses.

These helpers are used by the patient router endpoints to convert
Patient and PatientVersion models into the response envelope format.

Design Decisions:
- UUID fields serialized as strings for JSON compatibility
- Date/datetime fields serialized as ISO-8601 strings
- Enum fields serialized as their string values
- JSONB fields (allergies, conditions, etc.) passed through as-is
- None values preserved (not stripped) for explicit null representation

HIPAA Note:
    These serialized dicts contain PHI. They are only used within
    router endpoints that have already passed RBAC checks, and the
    responses include Cache-Control: no-store headers.
"""

from datetime import date, datetime
from typing import Any

from app.modules.patients.models import Patient, PatientVersion


def serialize_patient(patient: Patient) -> dict[str, Any]:
    """
    Convert a Patient SQLAlchemy model to a JSON-serializable dict.

    Handles UUID, date, datetime, and enum serialization.
    Matches the PatientResponse schema structure.

    Args:
        patient: Patient model instance from the database.

    Returns:
        Dict matching the PatientResponse schema fields.
    """
    return {
        "id": str(patient.id),
        "tenant_id": str(patient.tenant_id),
        "medical_record_number": patient.medical_record_number,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "date_of_birth": (
            patient.date_of_birth.isoformat()
            if patient.date_of_birth
            else None
        ),
        "gender": (
            patient.gender.value
            if hasattr(patient.gender, "value")
            else patient.gender
        ),
        "phone_number": patient.phone_number,
        "email": patient.email,
        "address": patient.address,
        "emergency_contact": patient.emergency_contact,
        "blood_type": patient.blood_type,
        "allergies": patient.allergies,
        "chronic_conditions": patient.chronic_conditions,
        "current_medications": patient.current_medications,
        "insurance_info": patient.insurance_info,
        "notes": patient.notes,
        "status": (
            patient.status.value
            if hasattr(patient.status, "value")
            else patient.status
        ),
        "created_by": str(patient.created_by),
        "deleted_at": (
            patient.deleted_at.isoformat()
            if patient.deleted_at
            else None
        ),
        "created_at": (
            patient.created_at.isoformat()
            if getattr(patient, "created_at", None)
            else None
        ),
        "updated_at": (
            patient.updated_at.isoformat()
            if getattr(patient, "updated_at", None)
            else None
        ),
    }


def serialize_version(version: PatientVersion) -> dict[str, Any]:
    """
    Convert a PatientVersion SQLAlchemy model to a JSON-serializable dict.

    Handles UUID and datetime serialization for version history responses.
    Matches the PatientVersionResponse schema structure.

    Args:
        version: PatientVersion model instance from the database.

    Returns:
        Dict matching the PatientVersionResponse schema fields.
    """
    return {
        "id": str(version.id),
        "patient_id": str(version.patient_id),
        "version_number": version.version_number,
        "changed_by": str(version.changed_by),
        "changed_at": (
            version.changed_at.isoformat()
            if version.changed_at
            else None
        ),
        "change_type": (
            version.change_type.value
            if hasattr(version.change_type, "value")
            else version.change_type
        ),
        "changes": version.changes or {},
        "snapshot": version.snapshot or {},
    }
