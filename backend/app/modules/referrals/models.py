"""
Referrals Module — SQLAlchemy Models
======================================
Defines the Referral ORM model.
Tenant-isolated via RLS (see migration 0019).
TenantMixin provides: tenant_id, created_at, updated_at.
"""

import uuid
from datetime import datetime, date
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin
from .enums import ReferralUrgency, ReferralStatus


class Referral(TenantMixin, Base):
    """
    Represents a clinical referral from one clinician to a specialist.

    Status transitions are enforced by ReferralService.update_status().
    Terminal states: completed, cancelled, declined.
    """

    __tablename__ = "referrals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("encounters.id"), nullable=True
    )
    referring_clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True
    )
    receiving_clinician_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
    )
    specialty: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    urgency: Mapped[str] = mapped_column(
        sa.Enum(ReferralUrgency, name="referralurgency"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.Enum(ReferralStatus, name="referralstatus"),
        nullable=False,
        default=ReferralStatus.PENDING,
    )
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    clinical_summary: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    referral_letter: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    specialist_findings: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    specialist_recommendations: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    scheduled_date: Mapped[Optional[date]] = mapped_column(sa.Date, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
