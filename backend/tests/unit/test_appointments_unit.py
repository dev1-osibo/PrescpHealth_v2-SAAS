"""
Unit Tests: Appointments Module (Task 11.5).

Tests cover:
- Double-booking rejection (clinician overlap detection)
- Waitlist promotion on cancellation
- Recurring appointment generation (daily, weekly, biweekly, monthly)
- Check-in and completion status transitions

All tests use mocked AsyncSession — no real DB connections.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.appointments.enums import (
    AppointmentStatus,
    AppointmentType,
    WaitlistStatus,
)
from app.modules.appointments.exceptions import (
    DoubleBookingError,
    InvalidAppointmentStateError,
)

# ---------------------------------------------------------------------------
# Create a mock audit service to replace the module-level _audit instance.
# The real AuditService.log_action doesn't exist on the class — services
# call it dynamically so we mock the entire _audit object.
# ---------------------------------------------------------------------------
_mock_audit = MagicMock()
_mock_audit.log_action = AsyncMock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_appointment(**overrides):
    """Create a mock Appointment object with sensible defaults."""
    appt = MagicMock()
    appt.id = overrides.get("id", uuid.uuid4())
    appt.tenant_id = overrides.get("tenant_id", uuid.uuid4())
    appt.patient_id = overrides.get("patient_id", uuid.uuid4())
    appt.clinician_id = overrides.get("clinician_id", uuid.uuid4())
    appt.appointment_type = overrides.get("appointment_type", AppointmentType.CONSULTATION)
    appt.status = overrides.get("status", AppointmentStatus.SCHEDULED)
    appt.scheduled_start = overrides.get("scheduled_start", datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc))
    appt.scheduled_end = overrides.get("scheduled_end", datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc))
    appt.reason = overrides.get("reason", "Follow-up")
    appt.notes = overrides.get("notes", None)
    appt.created_by = overrides.get("created_by", uuid.uuid4())
    appt.is_recurring = overrides.get("is_recurring", False)
    appt.recurrence_rule = overrides.get("recurrence_rule", None)
    appt.parent_appointment_id = overrides.get("parent_appointment_id", None)
    return appt


def _mock_db_with_conflict(has_conflict: bool):
    """Return mock DB session simulating double-booking check."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = _make_appointment() if has_conflict else None
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


class TestDoubleBookingRejection:
    """Verify clinician cannot be double-booked in overlapping time slot."""

    @pytest.mark.asyncio
    async def test_double_booking_raises_error(self):
        """Booking when clinician has existing appointment raises DoubleBookingError."""
        from app.modules.appointments.service import AppointmentService

        mock_db = _mock_db_with_conflict(has_conflict=True)
        service = AppointmentService()

        with pytest.raises(DoubleBookingError):
            await service.book_appointment(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                clinician_id=uuid.uuid4(),
                appt_type=AppointmentType.CONSULTATION,
                start=datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc),
                end=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
                reason="Checkup",
                created_by=uuid.uuid4(),
            )


class TestWaitlistPromotion:
    """Verify waitlist entry is promoted when an appointment is cancelled."""

    @pytest.mark.asyncio
    async def test_cancel_promotes_waitlisted_patient(self):
        """Cancelling appointment offers freed slot to highest-priority waitlisted patient."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appointment(status=AppointmentStatus.SCHEDULED)
        waitlist_entry = MagicMock()
        waitlist_entry.id = uuid.uuid4()
        waitlist_entry.status = WaitlistStatus.WAITING

        # Mock DB: first call returns the appointment, second call returns waitlist entry
        mock_db = AsyncMock()
        call_count = [0]

        async def _side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            scalars = MagicMock()
            if call_count[0] == 1:
                scalars.first.return_value = appt
            else:
                scalars.first.return_value = waitlist_entry
            result.scalars.return_value = scalars
            return result

        mock_db.execute = AsyncMock(side_effect=_side_effect)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = AppointmentService()
        with patch("app.modules.appointments.service._audit", _mock_audit), \
             patch("app.modules.appointments.service_waitlist._audit", _mock_audit):
            result = await service.cancel(
                db=mock_db, appointment_id=appt.id,
                reason="Patient requested", user_id=uuid.uuid4(),
            )

        assert appt.status == AppointmentStatus.CANCELLED
        # Waitlist entry was promoted to OFFERED
        assert waitlist_entry.status == WaitlistStatus.OFFERED


class TestRecurringAppointments:
    """Verify recurring appointment generation produces correct instance counts."""

    @pytest.mark.asyncio
    async def test_daily_recurrence_generates_7_instances(self):
        """Daily recurrence with count=7 generates 6 children (parent is #1)."""
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent = _make_appointment()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = parent
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        service = RecurrenceService()
        with patch("app.modules.appointments.service_recurrence._audit", _mock_audit), \
             patch("app.modules.appointments.service._audit", _mock_audit):
            children = await service.generate_recurring(
                db=mock_db, appointment_id=parent.id,
                rule={"frequency": "daily", "interval": 1, "count": 7},
                user_id=uuid.uuid4(),
            )

        assert len(children) == 6

    @pytest.mark.asyncio
    async def test_weekly_recurrence_generates_4_instances(self):
        """Weekly recurrence with count=4 generates 3 children."""
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent = _make_appointment()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = parent
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        service = RecurrenceService()
        with patch("app.modules.appointments.service_recurrence._audit", _mock_audit), \
             patch("app.modules.appointments.service._audit", _mock_audit):
            children = await service.generate_recurring(
                db=mock_db, appointment_id=parent.id,
                rule={"frequency": "weekly", "interval": 1, "count": 4},
                user_id=uuid.uuid4(),
            )

        assert len(children) == 3

    @pytest.mark.asyncio
    async def test_biweekly_recurrence_generates_4_instances(self):
        """Biweekly recurrence (interval=2) with count=4 generates 3 children."""
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent = _make_appointment()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = parent
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        service = RecurrenceService()
        with patch("app.modules.appointments.service_recurrence._audit", _mock_audit), \
             patch("app.modules.appointments.service._audit", _mock_audit):
            children = await service.generate_recurring(
                db=mock_db, appointment_id=parent.id,
                rule={"frequency": "weekly", "interval": 2, "count": 4},
                user_id=uuid.uuid4(),
            )

        assert len(children) == 3

    @pytest.mark.asyncio
    async def test_monthly_recurrence_generates_3_instances(self):
        """Monthly recurrence with count=3 generates 2 children."""
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent = _make_appointment()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = parent
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        service = RecurrenceService()
        with patch("app.modules.appointments.service_recurrence._audit", _mock_audit), \
             patch("app.modules.appointments.service._audit", _mock_audit):
            children = await service.generate_recurring(
                db=mock_db, appointment_id=parent.id,
                rule={"frequency": "monthly", "interval": 1, "count": 3},
                user_id=uuid.uuid4(),
            )

        assert len(children) == 2


class TestStatusTransitions:
    """Verify check-in and completion status transitions."""

    @pytest.mark.asyncio
    async def test_check_in_from_scheduled(self):
        """Check-in from SCHEDULED status succeeds and sets CHECKED_IN."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appointment(status=AppointmentStatus.SCHEDULED)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = appt
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = AppointmentService()
        with patch("app.modules.appointments.service._audit", _mock_audit):
            result = await service.check_in(db=mock_db, appointment_id=appt.id, user_id=uuid.uuid4())

        assert appt.status == AppointmentStatus.CHECKED_IN

    @pytest.mark.asyncio
    async def test_complete_from_checked_in(self):
        """Completion from CHECKED_IN status succeeds and sets COMPLETED."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appointment(status=AppointmentStatus.CHECKED_IN)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = appt
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = AppointmentService()
        with patch("app.modules.appointments.service._audit", _mock_audit):
            result = await service.complete(db=mock_db, appointment_id=appt.id, user_id=uuid.uuid4())

        assert appt.status == AppointmentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_check_in_from_completed_raises(self):
        """Check-in from COMPLETED status raises InvalidAppointmentStateError."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appointment(status=AppointmentStatus.COMPLETED)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = appt
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service = AppointmentService()
        with pytest.raises(InvalidAppointmentStateError):
            await service.check_in(db=mock_db, appointment_id=appt.id, user_id=uuid.uuid4())
