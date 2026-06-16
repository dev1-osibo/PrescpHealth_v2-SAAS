"""
PrescpHealth Backend — Bed Management Pydantic Schemas.

Request bodies and response models for the bed management API.
PHI fields (discharge plans, nursing notes content) are included in
responses but never echoed in log messages.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.modules.bed_management.enums import (
    AdmissionStatus,
    BedStatus,
    BedType,
    DischargeType,
    NoteType,
)


# ---------------------------------------------------------------------------
# Admission Schemas
# ---------------------------------------------------------------------------

class AdmitPatientRequest(BaseModel):
    """Body for POST /api/v1/admissions — admit a patient to a bed."""

    patient_id: uuid.UUID
    bed_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    reason: str = Field(..., min_length=1, max_length=2048,
                        description="Reason for admission (PHI — not logged)")
    notes: Optional[str] = Field(None, max_length=4096)


class DischargeRequest(BaseModel):
    """Body for POST /api/v1/admissions/{id}/discharge."""

    discharge_type: DischargeType
    discharge_plan: Optional[dict[str, Any]] = Field(
        None, description="Structured discharge instructions (PHI)"
    )
    notes: Optional[str] = Field(None, max_length=4096)


class TransferRequest(BaseModel):
    """Body for transferring a patient to a new bed."""

    new_bed_id: uuid.UUID
    reason: Optional[str] = Field(None, max_length=1024)


class AdmissionOut(BaseModel):
    """Full admission response object."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    bed_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    admitting_doctor_id: uuid.UUID
    admitted_at: datetime
    discharged_at: Optional[datetime] = None
    discharge_type: Optional[DischargeType] = None
    discharge_plan: Optional[dict[str, Any]] = None
    status: AdmissionStatus
    reason: str
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Bed Schemas
# ---------------------------------------------------------------------------

class BedOut(BaseModel):
    """Bed availability response object."""

    id: uuid.UUID
    ward_id: uuid.UUID
    bed_number: str
    status: BedStatus
    bed_type: BedType
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class BedAvailabilityOut(BaseModel):
    """Availability summary for a ward."""

    ward_id: uuid.UUID
    ward_name: str
    available: int
    occupied: int
    maintenance: int
    reserved: int
    beds: list[BedOut]


# ---------------------------------------------------------------------------
# Nursing Note Schemas
# ---------------------------------------------------------------------------

class NursingNoteRequest(BaseModel):
    """Body for POST /api/v1/admissions/{id}/nursing-notes."""

    content: str = Field(..., min_length=1, max_length=8192,
                         description="Nursing note content (PHI — not logged)")
    note_type: NoteType
    recorded_at: Optional[datetime] = None  # Defaults to now(utc) in service


class NursingNoteOut(BaseModel):
    """Nursing note response object."""

    id: uuid.UUID
    admission_id: uuid.UUID
    nurse_id: uuid.UUID
    note_type: NoteType
    recorded_at: datetime
    created_at: datetime
    # content included in responses but guarded by RBAC
    content: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Vitals Schemas
# ---------------------------------------------------------------------------

class VitalsRequest(BaseModel):
    """
    Body for POST /api/v1/admissions/{id}/vitals.

    Delegates to the Measurement module — this schema captures the wrapper.
    """

    systolic_bp: Optional[int] = Field(None, ge=0, le=300, description="mmHg")
    diastolic_bp: Optional[int] = Field(None, ge=0, le=200, description="mmHg")
    heart_rate: Optional[int] = Field(None, ge=0, le=300, description="bpm")
    temperature: Optional[float] = Field(None, ge=30.0, le=45.0, description="Celsius")
    oxygen_saturation: Optional[float] = Field(None, ge=0.0, le=100.0, description="%")
    respiratory_rate: Optional[int] = Field(None, ge=0, le=100, description="breaths/min")
    notes: Optional[str] = Field(None, max_length=1024)
