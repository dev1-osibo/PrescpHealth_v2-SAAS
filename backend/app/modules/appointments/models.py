"""
Appointments Module — SQLAlchemy Models
=========================================
Defines the Appointment and Waitlist ORM models.
Both tables are tenant-isolated via RLS (see migration 0018).
TenantMixin provides: tenant_id, created_at, updated_at.
"""

import uuid
from datetime import datetime, date, time
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin
from .enums import AppointmentType, AppointmentStatus, WaitlistStatus


class Appointment(TenantMixin, Base):
    """
    Represents a scheduled clinical appointment.

    Supports recurring appointments via parent_appointment_id self-FK.
    Double-booking prevention is enforced at the service layer.
    """

    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False, index=True
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True
    )
    appointment_type: Mapped[str] = mapped_column(
        sa.Enum(AppointmentType, name="appointmenttype"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.Enum(AppointmentStatus, name="appointmentstatus"),
        nullable=False,
        default=AppointmentStatus.SCHEDULED,
    )
    scheduled_start: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    actual_start: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    actual_end: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(
        sa.String(500), nullable=True
    )
    is_recurring: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    recurrence_rule: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    parent_appointment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("appointments.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )


class Waitlist(TenantMixin, Base):
    """
    Represents a patient's position on the appointment waitlist.

    Highest-priority (lowest integer value) entries are promoted first
    when a cancellation frees a matching slot.
    """

    __tablename__ = "waitlist"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False, index=True
    )
    clinician_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
    )
    appointment_type: Mapped[str] = mapped_column(
        sa.Enum(AppointmentType, name="appointmenttype"), nullable=False
    )
    preferred_date_start: Mapped[date] = mapped_column(sa.Date, nullable=False)
    preferred_date_end: Mapped[Optional[date]] = mapped_column(sa.Date, nullable=True)
    preferred_time_start: Mapped[Optional[time]] = mapped_column(sa.Time, nullable=True)
    preferred_time_end: Mapped[Optional[time]] = mapped_column(sa.Time, nullable=True)
    priority: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Enum(WaitlistStatus, name="waitliststatus"),
        nullable=False,
        default=WaitlistStatus.WAITING,
    )
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
