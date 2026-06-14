"""
Appointments Module — Pydantic Schemas
========================================
Request/response schemas for the appointments API.
Uses Pydantic v2 model_config for ORM serialisation.
"""

import uuid
from datetime import datetime, date, time
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import AppointmentType, AppointmentStatus, WaitlistStatus


# ---------------------------------------------------------------------------
# Appointment Schemas
# ---------------------------------------------------------------------------

class AppointmentCreate(BaseModel):
    """Payload for booking a new appointment."""

    patient_id: uuid.UUID
    clinician_id: uuid.UUID
    appointment_type: AppointmentType
    scheduled_start: datetime
    scheduled_end: datetime
    reason: str = Field(..., max_length=500)
    notes: Optional[str] = None
    is_recurring: bool = False
    recurrence_rule: Optional[dict[str, Any]] = None


class AppointmentReschedule(BaseModel):
    """Payload for rescheduling an existing appointment."""

    new_start: datetime
    new_end: datetime


class AppointmentCancel(BaseModel):
    """Payload for cancelling an appointment."""

    reason: str = Field(..., max_length=500)


class AppointmentResponse(BaseModel):
    """Read schema — returned in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    clinician_id: uuid.UUID
    appointment_type: AppointmentType
    status: AppointmentStatus
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    reason: str
    notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    is_recurring: bool
    recurrence_rule: Optional[dict[str, Any]] = None
    parent_appointment_id: Optional[uuid.UUID] = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Waitlist Schemas
# ---------------------------------------------------------------------------

class WaitlistCreate(BaseModel):
    """Payload for adding a patient to the waitlist."""

    patient_id: uuid.UUID
    appointment_type: AppointmentType
    preferred_date_start: date
    preferred_date_end: Optional[date] = None
    preferred_time_start: Optional[time] = None
    preferred_time_end: Optional[time] = None
    clinician_id: Optional[uuid.UUID] = None
    priority: int = Field(default=0, ge=0)
    notes: Optional[str] = None


class WaitlistResponse(BaseModel):
    """Read schema for waitlist entries."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    clinician_id: Optional[uuid.UUID] = None
    appointment_type: AppointmentType
    preferred_date_start: date
    preferred_date_end: Optional[date] = None
    preferred_time_start: Optional[time] = None
    preferred_time_end: Optional[time] = None
    priority: int
    status: WaitlistStatus
    notes: Optional[str] = None
    created_at: datetime
