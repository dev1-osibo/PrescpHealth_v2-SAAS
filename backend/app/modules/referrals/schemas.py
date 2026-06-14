"""
Referrals Module — Pydantic Schemas
=====================================
Request/response schemas for the referrals API.
Uses Pydantic v2 model_config for ORM serialisation.
"""

import uuid
from datetime import datetime, date
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict

from .enums import ReferralUrgency, ReferralStatus


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class ReferralCreate(BaseModel):
    """Payload for creating a new referral."""

    patient_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    receiving_clinician_id: Optional[uuid.UUID] = None
    specialty: str
    urgency: ReferralUrgency
    reason: str
    clinical_summary: Optional[str] = None
    referral_letter: Optional[dict[str, Any]] = None
    scheduled_date: Optional[date] = None


class ReferralStatusUpdate(BaseModel):
    """Payload for updating a referral's status."""

    new_status: ReferralStatus


class ReferralCompletion(BaseModel):
    """Payload for recording specialist findings on referral completion."""

    specialist_findings: str
    specialist_recommendations: str


# ---------------------------------------------------------------------------
# Response Schema
# ---------------------------------------------------------------------------

class ReferralResponse(BaseModel):
    """Read schema — returned in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    referring_clinician_id: uuid.UUID
    receiving_clinician_id: Optional[uuid.UUID] = None
    specialty: str
    urgency: ReferralUrgency
    status: ReferralStatus
    reason: str
    clinical_summary: Optional[str] = None
    referral_letter: Optional[dict[str, Any]] = None
    specialist_findings: Optional[str] = None
    specialist_recommendations: Optional[str] = None
    scheduled_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Paginated list wrapper
# ---------------------------------------------------------------------------

class ReferralListResponse(BaseModel):
    """Wrapper for paginated referral lists."""

    items: list[ReferralResponse]
    total: int
    limit: int
    offset: int
