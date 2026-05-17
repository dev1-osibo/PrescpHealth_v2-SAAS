"""
PrescpHealth Backend — Patient Pydantic Schemas.

Request/response schemas for the patient profile management API.
These schemas enforce input validation at the API boundary and
structure outgoing data in a consistent format.

Schema Design:
- PatientCreate: Validates all required fields for new patient creation
- PatientUpdate: Partial update — all fields optional
- PatientResponse: Single patient output (serialized from model)
- PatientListResponse: Paginated list with cursor metadata
- PatientVersionResponse: Version history entry
- PatientTimelineResponse: Timeline event
- PatientSearchParams: Query parameter validation for search/filter

HIPAA Compliance:
- Schemas contain PHI fields (names, DOB, contact info) — these are
  protected by RBAC at the router level and Cache-Control headers
- Never expose PHI in error messages (Pydantic validation errors
  are sanitized before returning to client)
- All responses include request_id for correlation without PHI

Per API design steering rule:
- All responses use the standard envelope format
- Cursor-based pagination for list endpoints
- Timestamps are ISO-8601 UTC
"""

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.modules.patients.models import PatientGender, PatientStatus


# ---------------------------------------------------------------------------
# Request Schemas — Input Validation
# ---------------------------------------------------------------------------
class PatientCreate(BaseModel):
    """
    Input schema for creating a new patient record.

    All required fields must be provided. Optional fields (contact info,
    medical history) can be added later via PatientUpdate.

    Validation:
    - MRN: Required, unique per tenant (enforced at DB level)
    - Names: Required, max 255 chars
    - DOB: Required, must be a valid date
    - Gender: Required, must be one of the defined enum values
    """

    medical_record_number: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Clinic-assigned medical record number (unique per tenant)",
        examples=["MRN-2025-001"],
    )
    first_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Patient first name (PHI)",
        examples=["Test Patient"],
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Patient last name (PHI)",
        examples=["Alpha"],
    )
    date_of_birth: date = Field(
        ...,
        description="Patient date of birth (PHI, ISO-8601 format)",
        examples=["1985-03-15"],
    )
    gender: PatientGender = Field(
        ...,
        description="Patient gender",
        examples=["Male"],
    )

    # Optional fields — can be provided at creation or added later
    phone_number: Optional[str] = Field(
        None,
        max_length=50,
        description="Patient phone number (PHI, optional)",
    )
    email: Optional[str] = Field(
        None,
        max_length=255,
        description="Patient email address (PHI, optional)",
    )
    address: Optional[dict[str, Any]] = Field(
        None,
        description="Structured address {street, city, state, country, postal_code}",
    )
    emergency_contact: Optional[dict[str, Any]] = Field(
        None,
        description="Emergency contact {name, phone, relationship}",
    )
    blood_type: Optional[str] = Field(
        None,
        max_length=10,
        description="Blood type (e.g., A+, O-, AB+)",
    )
    allergies: Optional[list[str]] = Field(
        None,
        description="List of allergy strings",
        examples=[["Penicillin", "Latex"]],
    )
    chronic_conditions: Optional[list[dict[str, Any]]] = Field(
        None,
        description="List of conditions [{code, display_name}]",
    )
    current_medications: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Active medications [{name, dosage, frequency, start_date}]",
    )
    insurance_info: Optional[dict[str, Any]] = Field(
        None,
        description="Insurance details {provider, policy_number, group_number}",
    )
    notes: Optional[str] = Field(
        None,
        description="Free-text clinician notes (PHI)",
    )
    status: PatientStatus = Field(
        default=PatientStatus.ACTIVE,
        description="Patient lifecycle status (defaults to Active)",
    )


class PatientUpdate(BaseModel):
    """
    Input schema for updating an existing patient record.

    All fields are optional — only provided fields are updated.
    This enables partial updates without requiring the full patient payload.

    The service layer computes a diff between old and new state,
    creates a version record, and logs the change to the audit trail.
    """

    medical_record_number: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Updated MRN (unique per tenant)",
    )
    first_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Updated first name (PHI)",
    )
    last_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Updated last name (PHI)",
    )
    date_of_birth: Optional[date] = Field(
        None,
        description="Updated date of birth (PHI)",
    )
    gender: Optional[PatientGender] = Field(
        None,
        description="Updated gender",
    )
    phone_number: Optional[str] = Field(
        None,
        max_length=50,
        description="Updated phone number (PHI)",
    )
    email: Optional[str] = Field(
        None,
        max_length=255,
        description="Updated email (PHI)",
    )
    address: Optional[dict[str, Any]] = Field(
        None,
        description="Updated address",
    )
    emergency_contact: Optional[dict[str, Any]] = Field(
        None,
        description="Updated emergency contact",
    )
    blood_type: Optional[str] = Field(
        None,
        max_length=10,
        description="Updated blood type",
    )
    allergies: Optional[list[str]] = Field(
        None,
        description="Updated allergies list",
    )
    chronic_conditions: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Updated chronic conditions",
    )
    current_medications: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Updated medications",
    )
    insurance_info: Optional[dict[str, Any]] = Field(
        None,
        description="Updated insurance info",
    )
    notes: Optional[str] = Field(
        None,
        description="Updated clinician notes (PHI)",
    )
    status: Optional[PatientStatus] = Field(
        None,
        description="Updated patient status",
    )


# ---------------------------------------------------------------------------
# Response Schemas — Output Formatting
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


# ---------------------------------------------------------------------------
# Query Parameter Schema
# ---------------------------------------------------------------------------
class PatientSearchParams(BaseModel):
    """
    Query parameters for patient search/filter.

    All fields are optional — omitting a field means no filter on that
    dimension. Multiple filters combine with AND logic.

    Used to validate and parse query parameters from the URL before
    converting to PatientSearchFilters for the service layer.
    """

    name: Optional[str] = Field(
        None,
        description="Partial name match (searches first_name OR last_name)",
    )
    mrn: Optional[str] = Field(
        None,
        description="Partial MRN match",
    )
    status: Optional[PatientStatus] = Field(
        None,
        description="Filter by patient status (Active, Inactive, etc.)",
    )
    created_after: Optional[datetime] = Field(
        None,
        description="Only patients created after this datetime (UTC)",
    )
    created_before: Optional[datetime] = Field(
        None,
        description="Only patients created before this datetime (UTC)",
    )
    include_deleted: bool = Field(
        default=False,
        description="Whether to include soft-deleted patients",
    )
