"""
Appointments Module — AppointmentService
==========================================
Core CRUD and workflow operations for appointments.
Double-booking is checked before every create/reschedule.
All mutations are audit-logged. No PHI in log messages.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .models import Appointment
from .enums import AppointmentStatus, AppointmentType
from .exceptions import (
    AppointmentNotFoundError,
    DoubleBookingError,
    InvalidAppointmentStateError,
)

log = structlog.get_logger(__name__)
_audit = AuditService()


class AppointmentService:
    """Service layer for appointment lifecycle management."""

    async def _check_double_booking(
        self,
        db: AsyncSession,
        clinician_id: uuid.UUID,
        tenant_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Raise DoubleBookingError if clinician has an overlapping active appointment."""
        stmt = select(Appointment).where(
            and_(
                Appointment.clinician_id == clinician_id,
                Appointment.tenant_id == tenant_id,
                Appointment.status.in_(
                    [AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED,
                     AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS]
                ),
                Appointment.scheduled_start < end,
                Appointment.scheduled_end > start,
            )
        )
        if exclude_id:
            stmt = stmt.where(Appointment.id != exclude_id)
        result = await db.execute(stmt)
        if result.scalars().first():
            raise DoubleBookingError(str(clinician_id))

    async def book_appointment(
        self, db: AsyncSession, tenant_id: uuid.UUID, patient_id: uuid.UUID,
        clinician_id: uuid.UUID, appt_type: AppointmentType, start: datetime,
        end: datetime, reason: str, created_by: uuid.UUID,
        notes: Optional[str] = None,
    ) -> Appointment:
        """Create a new appointment after verifying no double-booking exists."""
        await self._check_double_booking(db, clinician_id, tenant_id, start, end)
        appt = Appointment(
            tenant_id=tenant_id, patient_id=patient_id, clinician_id=clinician_id,
            appointment_type=appt_type, scheduled_start=start, scheduled_end=end,
            reason=reason, notes=notes, created_by=created_by,
            status=AppointmentStatus.SCHEDULED,
        )
        db.add(appt)
        await db.flush()
        await _audit.log_action(
            db, action="appointment.created", resource_id=str(appt.id),
            tenant_id=str(tenant_id), user_id=str(created_by),
        )
        await db.commit()
        await db.refresh(appt)
        return appt

    async def reschedule(
        self, db: AsyncSession, appointment_id: uuid.UUID,
        new_start: datetime, new_end: datetime, user_id: uuid.UUID,
    ) -> Appointment:
        """Reschedule an appointment to a new time window after conflict check."""
        appt = await self.get_appointment(db, appointment_id)
        if appt.status in (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED):
            raise InvalidAppointmentStateError(str(appointment_id), appt.status, "reschedule")
        await self._check_double_booking(
            db, appt.clinician_id, appt.tenant_id, new_start, new_end,
            exclude_id=appointment_id,
        )
        appt.scheduled_start = new_start
        appt.scheduled_end = new_end
        await db.flush()
        await _audit.log_action(
            db, action="appointment.rescheduled", resource_id=str(appt.id),
            tenant_id=str(appt.tenant_id), user_id=str(user_id),
        )
        await db.commit()
        await db.refresh(appt)
        return appt

    async def cancel(
        self, db: AsyncSession, appointment_id: uuid.UUID,
        reason: str, user_id: uuid.UUID,
    ) -> Appointment:
        """Cancel an appointment and attempt to promote the highest-priority waitlist entry."""
        from .service_waitlist import WaitlistService
        appt = await self.get_appointment(db, appointment_id)
        if appt.status == AppointmentStatus.CANCELLED:
            raise InvalidAppointmentStateError(str(appointment_id), appt.status, "cancel")
        appt.status = AppointmentStatus.CANCELLED
        appt.cancellation_reason = reason
        await db.flush()
        await _audit.log_action(
            db, action="appointment.cancelled", resource_id=str(appt.id),
            tenant_id=str(appt.tenant_id), user_id=str(user_id),
        )
        wl_svc = WaitlistService()
        await wl_svc.promote_from_waitlist(
            db, appt.tenant_id, appt.clinician_id,
            appt.scheduled_start, appt.scheduled_end,
        )
        await db.commit()
        await db.refresh(appt)
        return appt

    async def check_in(
        self, db: AsyncSession, appointment_id: uuid.UUID, user_id: uuid.UUID,
    ) -> Appointment:
        """Mark appointment as checked-in and record actual start time."""
        appt = await self.get_appointment(db, appointment_id)
        if appt.status not in (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED):
            raise InvalidAppointmentStateError(str(appointment_id), appt.status, "check_in")
        appt.status = AppointmentStatus.CHECKED_IN
        appt.actual_start = datetime.now(timezone.utc)
        await db.flush()
        await _audit.log_action(
            db, action="appointment.checked_in", resource_id=str(appt.id),
            tenant_id=str(appt.tenant_id), user_id=str(user_id),
        )
        await db.commit()
        await db.refresh(appt)
        return appt

    async def complete(
        self, db: AsyncSession, appointment_id: uuid.UUID, user_id: uuid.UUID,
    ) -> Appointment:
        """Mark appointment completed and record actual end time."""
        appt = await self.get_appointment(db, appointment_id)
        if appt.status not in (AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS):
            raise InvalidAppointmentStateError(str(appointment_id), appt.status, "complete")
        appt.status = AppointmentStatus.COMPLETED
        appt.actual_end = datetime.now(timezone.utc)
        await db.flush()
        await _audit.log_action(
            db, action="appointment.completed", resource_id=str(appt.id),
            tenant_id=str(appt.tenant_id), user_id=str(user_id),
        )
        await db.commit()
        await db.refresh(appt)
        return appt

    async def get_schedule(
        self, db: AsyncSession, clinician_id: uuid.UUID,
        date_from: datetime, date_to: datetime,
    ) -> list[Appointment]:
        """Return all appointments for a clinician within the given date range."""
        stmt = (
            select(Appointment)
            .where(
                and_(
                    Appointment.clinician_id == clinician_id,
                    Appointment.scheduled_start >= date_from,
                    Appointment.scheduled_end <= date_to,
                )
            )
            .order_by(Appointment.scheduled_start)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_appointment(
        self, db: AsyncSession, appointment_id: uuid.UUID,
    ) -> Appointment:
        """Fetch a single appointment by primary key or raise AppointmentNotFoundError."""
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        result = await db.execute(stmt)
        appt = result.scalars().first()
        if not appt:
            raise AppointmentNotFoundError(str(appointment_id))
        return appt
