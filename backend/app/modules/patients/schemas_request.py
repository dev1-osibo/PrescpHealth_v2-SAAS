"""
PrescpHealth Backend — Patient Request Schemas.

Input validation schemas for patient profile management API endpoints:
- PatientCreate: Validates all required fields for new patient creation
- PatientUpdate: Partial update — all fields optional

Extracted from schemas.py to comply with the ~150 lines of logic per
file rule. Re-exported from schemas.py for backward compatibility.

HIPAA Compliance:
- Schemas contain PHI fields (names, DOB, contact info) — these are
  protected by RBAC at the router level and Cache-Control headers
- Never expose PHI in error messages (Pydantic validation errors
  are sanitized before returning to client)
"""

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.modules.patients.enums import PatientGender, PatientStatus


# ---------------------------------------------------------------------------
# PatientCreate — Input for creating a new patient record
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


# ---------------------------------------------------------------------------
# PatientUpdate — Input for updating an existing patient record
# ---------------------------------------------------------------------------
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
