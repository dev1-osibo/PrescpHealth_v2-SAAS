"""
PrescpHealth Backend — Prescription Pydantic Schemas.

Input validation schemas for prescription management API endpoints:
- PrescriptionCreate: Write a new prescription (triggers DDI check)
- PrescriptionStatusUpdate: Change prescription status
- RefillRequest: Process a prescription refill

HIPAA Compliance:
- Schemas contain PHI fields (drug_name, dosage, frequency)
- Protected by RBAC at the router level + Cache-Control headers
- Never expose PHI in validation error messages
"""

import uuid
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Prescription Create — Write a new prescription
# ---------------------------------------------------------------------------
class PrescriptionCreate(BaseModel):
    """
    Input schema for writing a new prescription.

    Triggers ATC code validation and drug interaction check.
    If a Contraindicated interaction is found and not acknowledged,
    the request is rejected with InteractionBlockedError.
    """

    patient_id: uuid.UUID = Field(
        ..., description="Patient receiving the medication"
    )
    encounter_id: Optional[uuid.UUID] = Field(
        None, description="Originating encounter (nullable)"
    )
    drug_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="PHI: Medication name (e.g., Metformin)",
    )
    atc_code: str = Field(
        ...,
        min_length=3,
        max_length=10,
        description="ATC classification code (validated against catalog)",
    )
    dosage: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="PHI: Dosage amount (e.g., '500mg')",
    )
    frequency: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="PHI: Dosing frequency (e.g., 'twice daily')",
    )
    duration_days: Optional[int] = Field(
        None, ge=1, le=3650, description="Duration in days (NULL for chronic)"
    )
    route: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Route of administration (oral, IV, topical, etc.)",
    )
    refills_allowed: int = Field(
        default=0, ge=0, le=12, description="Number of refills permitted"
    )
    interaction_acknowledged: bool = Field(
        default=False,
        description="True if Doctor acknowledged a DDI warning",
    )
    interaction_justification: Optional[str] = Field(
        None,
        max_length=2000,
        description="PHI: Justification for overriding DDI warning",
    )


# ---------------------------------------------------------------------------
# Prescription Status Update — Discontinue, hold, or resume
# ---------------------------------------------------------------------------
class PrescriptionStatusUpdate(BaseModel):
    """Input schema for changing prescription status."""

    action: str = Field(
        ...,
        description="Action to perform: discontinue, hold, or resume",
        pattern="^(discontinue|hold|resume)$",
    )
    reason: Optional[str] = Field(
        None,
        max_length=2000,
        description="PHI: Reason for status change (required for discontinue)",
    )


# ---------------------------------------------------------------------------
# Refill Request — Process a prescription refill
# ---------------------------------------------------------------------------
class RefillRequest(BaseModel):
    """Input schema for processing a prescription refill."""

    dispensed_quantity: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="PHI: Quantity dispensed (e.g., '30 tablets')",
    )
