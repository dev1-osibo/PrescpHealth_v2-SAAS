"""
PrescpHealth Backend — Patient Response Schemas.

Output schemas for patient profile management API endpoints:
- PatientResponse: Single patient output (serialized from model)
- PatientListResponse: Paginated list with cursor metadata
- PatientVersionResponse: Version history entry
- PatientTimelineResponse: Timeline event

Extracted from schemas.py to comply with the ~150 lines of logic per
file rule. Re-exported from schemas.py for backward compatibility.

Per API design steering rule:
- All responses use the standard envelope format
- Cursor-based pagination for list endpoints
- Timestamps are ISO-8601 UTC
"""

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PatientResponse — Single patient output
# ---------------------------------------------------------------------------
class PatientResponse(BaseModel):
    """
    Single patient response schema.

    Serializes a Patient model instance for API output.
    Includes all fields that the requesting role is authorized to see.

    PHI fields are included because RBAC is enforced at the router level —
    if you can call the endpoint, you're authorized to see the data.
    """

    id: uuid.UUID = Field(..., description="Patient UUID (immutable)")
    tenant_id: uuid.UUID = Field(..., description="Tenant UUID")
    medical_record_number: str = Field(..., description="Clinic-assigned MRN")
    first_name: str = Field(..., description="Patient first name (PHI)")
    last_name: str = Field(..., description="Patient last name (PHI)")
    date_of_birth: date = Field(..., description="Date of birth (PHI)")
    gender: str = Field(..., description="Patient gender")
    phone_number: Optional[str] = Field(None, description="Phone (PHI)")
    email: Optional[str] = Field(None, description="Email (PHI)")
    address: Optional[dict[str, Any]] = Field(None, description="Address (PHI)")
    emergency_contact: Optional[dict[str, Any]] = Field(None)
    blood_type: Optional[str] = Field(None, description="Blood type")
    allergies: Optional[list] = Field(None, description="Allergies list")
    chronic_conditions: Optional[list] = Field(None)
    current_medications: Optional[list] = Field(None)
    insurance_info: Optional[dict[str, Any]] = Field(None)
    notes: Optional[str] = Field(None, description="Clinician notes (PHI)")
    status: str = Field(..., description="Patient lifecycle status")
    created_by: uuid.UUID = Field(..., description="Creator user UUID")
    deleted_at: Optional[datetime] = Field(None, description="Soft-delete timestamp")
    created_at: Optional[datetime] = Field(None, description="Record creation time")
    updated_at: Optional[datetime] = Field(None, description="Last update time")

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# PatientListResponse — Paginated list of patients
# ---------------------------------------------------------------------------
class PatientListResponse(BaseModel):
    """
    Paginated list of patients with cursor metadata.

    Used by the GET /api/v1/patients endpoint. Wraps a list of
    PatientResponse items with pagination state for the client.
    """

    items: list[PatientResponse] = Field(
        ...,
        description="List of patient records for the current page",
    )
    cursor: Optional[str] = Field(
        None,
        description="Cursor for the next page (None if no more pages)",
    )
    has_more: bool = Field(
        ...,
        description="Whether there are more patients after this page",
    )


# ---------------------------------------------------------------------------
# PatientVersionResponse — Version history entry
# ---------------------------------------------------------------------------
class PatientVersionResponse(BaseModel):
    """
    Version history entry for a patient record.

    Each version captures: who changed what, when, and the full
    patient state at that point (for point-in-time recovery).
    """

    id: uuid.UUID = Field(..., description="Version record UUID")
    patient_id: uuid.UUID = Field(..., description="Patient UUID")
    version_number: int = Field(..., description="Sequential version number")
    changed_by: uuid.UUID = Field(..., description="User who made the change")
    changed_at: datetime = Field(..., description="When the change was made (UTC)")
    change_type: str = Field(..., description="Type: create, update, soft_delete, restore")
    changes: dict[str, Any] = Field(..., description="Diff: {field: {old, new}}")
    snapshot: dict[str, Any] = Field(..., description="Full patient state at this version")

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# PatientTimelineResponse — Timeline event
# ---------------------------------------------------------------------------
class PatientTimelineResponse(BaseModel):
    """
    Timeline event for a patient.

    Currently represents profile changes. Will be extended to include
    measurements, risk scores, alerts, and AI interactions.
    """

    type: str = Field(..., description="Event type (e.g., 'profile_change')")
    subtype: str = Field(..., description="Event subtype (e.g., 'create', 'update')")
    timestamp: str = Field(..., description="When the event occurred (ISO-8601)")
    version_number: int = Field(..., description="Associated version number")
    changed_by: str = Field(..., description="UUID of user who triggered the event")
    description: str = Field(..., description="Human-readable event description")
