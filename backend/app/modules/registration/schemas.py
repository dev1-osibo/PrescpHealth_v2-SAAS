"""
Registration Module — Pydantic Schemas
========================================
Request/response schemas for intake, consent, and identity verification APIs.

PHI NOTICE: digital_signature field is accepted but NEVER included in logs.
"""

import uuid
from datetime import datetime, date
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import ConsentType, VerificationType


# ---------------------------------------------------------------------------
# Registration Schemas
# ---------------------------------------------------------------------------

class IntakeCreate(BaseModel):
    """Minimal payload to start patient intake (name + DOB only)."""

    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    date_of_birth: date


class RegistrationUpdate(BaseModel):
    """Partial update of registration fields — all fields optional."""

    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    date_of_birth: Optional[date] = None
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    emergency_contact_name: Optional[str] = Field(None, max_length=255)
    emergency_contact_phone: Optional[str] = Field(None, max_length=30)
    insurance_number: Optional[str] = Field(None, max_length=100)
    extra: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Consent Schemas
# ---------------------------------------------------------------------------

class ConsentCapture(BaseModel):
    """Payload for recording a patient consent event."""

    consent_type: ConsentType
    version: str = Field(..., max_length=50)
    is_granted: bool
    # digital_signature: PHI — accepted but NEVER logged
    digital_signature: Optional[str] = None
    witness_name: Optional[str] = Field(None, max_length=255)
    expires_at: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None


class ConsentResponse(BaseModel):
    """Read schema for a consent record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    consent_type: ConsentType
    version: str
    is_granted: bool
    granted_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Identity Verification Schemas
# ---------------------------------------------------------------------------

class IdentityVerificationCreate(BaseModel):
    """Payload for recording identity verification during registration."""

    verification_type: VerificationType
    # document_number: PHI — accepted but NEVER logged
    document_number: Optional[str] = Field(None, max_length=100)
    issuing_authority: Optional[str] = Field(None, max_length=255)
    expiry_date: Optional[date] = None
    notes: Optional[str] = None


class IdentityVerificationResponse(BaseModel):
    """Read schema for identity verification. Omits document_number."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    verification_type: VerificationType
    issuing_authority: Optional[str] = None
    expiry_date: Optional[date] = None
    is_verified: bool
    verified_at: Optional[datetime] = None
    created_at: datetime
