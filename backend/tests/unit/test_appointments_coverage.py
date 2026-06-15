"""
Coverage tests: Appointments Module — uncovered service paths, schemas, enums, exceptions.

Targets paths not exercised by test_appointments_unit.py:
  - AppointmentService.book_appointment (happy path — no conflict)
  - AppointmentService.reschedule (happy path + invalid-state guard)
  - AppointmentService.cancel (already-cancelled guard)
  - AppointmentService.check_in (from CONFIRMED)
  - AppointmentService.complete (from IN_PROGRESS)
  - AppointmentService.get_schedule
  - AppointmentService.get_appointment not-found
  - WaitlistService.add_to_waitlist
  - WaitlistService.promote_from_waitlist (no candidates)
  - RecurrenceService.generate_recurring (count=1, invalid frequency)
  - Pydantic schemas
  - Custom exceptions
  - Enum value completeness
"""

import uuid
from datetime import datetime, date, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.appointments.enums import (
    AppointmentStatus,
    AppointmentType,
    WaitlistStatus,
)
from app.modules.appointments.exceptions import (
    AppointmentNotFoundError,
    DoubleBookingError,
    InvalidAppointmentStateError,
)
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentReschedule,
    AppointmentCancel,
    AppointmentResponse,
    WaitlistCreate,
    WaitlistResponse,
)

# ---------------------------------------------------------------------------
# Shared mock audit to patch across all service modules
# ---------------------------------------------------------------------------
_mock_audit = MagicMock()
_mock_audit.log_action = AsyncMock()

_START = datetime(2025, 8, 1, 9, 0, tzinfo=timezone.utc)
_END = datetime(2025, 8, 1, 10, 0, tzinfo=timezone.utc)


def _make_appt(**kw):
    """Return a mock Appointment with sensible defaults."""
    a = MagicMock()
    a.id = kw.get("id", uuid.uuid4())
    a.tenant_id = kw.get("tenant_id", uuid.uuid4())
    a.patient_id = kw.get("patient_id", uuid.uuid4())
    a.clinician_id = kw.get("clinician_id", uuid.uuid4())
    a.appointment_type = kw.get("appointment_type", AppointmentType.CONSULTATION)
    a.status = kw.get("status", AppointmentStatus.SCHEDULED)
    a.scheduled_start = kw.get("scheduled_start", _START)
    a.scheduled_end = kw.get("scheduled_end", _END)
    a.reason = kw.get("reason", "Routine checkup")
    a.notes = kw.get("notes", None)
    a.cancellation_reason = kw.get("cancellation_reason", None)
    a.created_by = kw.get("created_by", uuid.uuid4())
    a.is_recurring = kw.get("is_recurring", False)
    a.recurrence_rule = kw.get("recurrence_rule", None)
    a.parent_appointment_id = kw.get("parent_appointment_id", None)
    a.actual_start = kw.get("actual_start", None)
    a.actual_end = kw.get("actual_end", None)
    return a


def _mock_db(**kw):
    """Return mock AsyncSession with configurable execute return values."""
    db = AsyncMock()
    first_val = kw.get("first_val", None)
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = first_val
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ===========================================================================
# AppointmentService.book_appointment — happy path
# ===========================================================================
class TestBookAppointmentHappyPath:
    """Verify successful booking when no conflicting appointment exists."""

    @pytest.mark.asyncio
    async def test_book_creates_appointment_record(self):
        """book_appointment adds a new Appointment to the session when no conflict exists."""
        from app.modules.appointments.service import AppointmentService

        db = _mock_db(first_val=None)  # No conflict
        svc = AppointmentService()

        with patch("app.modules.appointments.service._audit", _mock_audit):
            result = await svc.book_appointment(
                db=db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                clinician_id=uuid.uuid4(),
                appt_type=AppointmentType.FOLLOW_UP,
                start=_START,
                end=_END,
                reason="Scheduled follow-up",
                created_by=uuid.uuid4(),
            )

        # An object was added to the session
        assert db.add.called
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_book_with_notes(self):
        """book_appointment stores optional notes field."""
        from app.modules.appointments.service import AppointmentService

        db = _mock_db(first_val=None)
        svc = AppointmentService()

        with patch("app.modules.appointments.service._audit", _mock_audit):
            await svc.book_appointment(
                db=db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                clinician_id=uuid.uuid4(),
                appt_type=AppointmentType.PROCEDURE,
                start=_START,
                end=_END,
                reason="Minor procedure",
                created_by=uuid.uuid4(),
                notes="Patient allergic to latex",
            )

        added = db.add.call_args[0][0]
        assert added.notes == "Patient allergic to latex"

    @pytest.mark.asyncio
    async def test_book_sets_scheduled_status(self):
        """Newly booked appointment starts in SCHEDULED status."""
        from app.modules.appointments.service import AppointmentService

        db = _mock_db(first_val=None)
        svc = AppointmentService()

        with patch("app.modules.appointments.service._audit", _mock_audit):
            await svc.book_appointment(
                db=db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                clinician_id=uuid.uuid4(),
                appt_type=AppointmentType.SCREENING,
                start=_START,
                end=_END,
                reason="Annual screening",
                created_by=uuid.uuid4(),
            )

        added = db.add.call_args[0][0]
        assert added.status == AppointmentStatus.SCHEDULED


# ===========================================================================
# AppointmentService.reschedule
# ===========================================================================
class TestReschedule:
    """Verify reschedule happy path and invalid-state guards."""

    @pytest.mark.asyncio
    async def test_reschedule_updates_times(self):
        """reschedule updates scheduled_start and scheduled_end on the appointment."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.SCHEDULED)
        db = _mock_db(first_val=None)  # for double-booking check
        svc = AppointmentService()
        svc.get_appointment = AsyncMock(return_value=appt)

        new_start = _START + timedelta(hours=2)
        new_end = _END + timedelta(hours=2)

        with patch("app.modules.appointments.service._audit", _mock_audit):
            await svc.reschedule(
                db=db,
                appointment_id=appt.id,
                new_start=new_start,
                new_end=new_end,
                user_id=uuid.uuid4(),
            )

        assert appt.scheduled_start == new_start
        assert appt.scheduled_end == new_end

    @pytest.mark.asyncio
    async def test_reschedule_completed_raises(self):
        """Rescheduling a COMPLETED appointment raises InvalidAppointmentStateError."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.COMPLETED)
        svc = AppointmentService()
        svc.get_appointment = AsyncMock(return_value=appt)

        with pytest.raises(InvalidAppointmentStateError):
            await svc.reschedule(
                db=AsyncMock(),
                appointment_id=appt.id,
                new_start=_START + timedelta(days=1),
                new_end=_END + timedelta(days=1),
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_reschedule_cancelled_raises(self):
        """Rescheduling a CANCELLED appointment raises InvalidAppointmentStateError."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.CANCELLED)
        svc = AppointmentService()
        svc.get_appointment = AsyncMock(return_value=appt)

        with pytest.raises(InvalidAppointmentStateError):
            await svc.reschedule(
                db=AsyncMock(),
                appointment_id=appt.id,
                new_start=_START + timedelta(days=1),
                new_end=_END + timedelta(days=1),
                user_id=uuid.uuid4(),
            )


# ===========================================================================
# AppointmentService.cancel — already-cancelled guard
# ===========================================================================
class TestCancelGuard:
    """Verify cancel raises when appointment is already CANCELLED."""

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_raises(self):
        """Cancelling an already-CANCELLED appointment raises InvalidAppointmentStateError."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.CANCELLED)
        svc = AppointmentService()
        svc.get_appointment = AsyncMock(return_value=appt)

        with pytest.raises(InvalidAppointmentStateError):
            await svc.cancel(
                db=AsyncMock(),
                appointment_id=appt.id,
                reason="Duplicate cancellation",
                user_id=uuid.uuid4(),
            )


# ===========================================================================
# AppointmentService.check_in — from CONFIRMED
# ===========================================================================
class TestCheckInFromConfirmed:
    """Verify check-in succeeds from CONFIRMED status."""

    @pytest.mark.asyncio
    async def test_check_in_from_confirmed(self):
        """check_in from CONFIRMED sets status to CHECKED_IN."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.CONFIRMED)
        db = _mock_db(first_val=appt)
        svc = AppointmentService()

        with patch("app.modules.appointments.service._audit", _mock_audit):
            await svc.check_in(db=db, appointment_id=appt.id, user_id=uuid.uuid4())

        assert appt.status == AppointmentStatus.CHECKED_IN
        assert appt.actual_start is not None


# ===========================================================================
# AppointmentService.complete — from IN_PROGRESS
# ===========================================================================
class TestCompleteFromInProgress:
    """Verify completion succeeds from IN_PROGRESS status."""

    @pytest.mark.asyncio
    async def test_complete_from_in_progress(self):
        """complete from IN_PROGRESS sets status to COMPLETED."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.IN_PROGRESS)
        db = _mock_db(first_val=appt)
        svc = AppointmentService()

        with patch("app.modules.appointments.service._audit", _mock_audit):
            await svc.complete(db=db, appointment_id=appt.id, user_id=uuid.uuid4())

        assert appt.status == AppointmentStatus.COMPLETED
        assert appt.actual_end is not None

    @pytest.mark.asyncio
    async def test_complete_from_scheduled_raises(self):
        """complete from SCHEDULED raises InvalidAppointmentStateError."""
        from app.modules.appointments.service import AppointmentService

        appt = _make_appt(status=AppointmentStatus.SCHEDULED)
        db = _mock_db(first_val=appt)
        svc = AppointmentService()

        with pytest.raises(InvalidAppointmentStateError):
            await svc.complete(db=db, appointment_id=appt.id, user_id=uuid.uuid4())


# ===========================================================================
# AppointmentService.get_schedule
# ===========================================================================
class TestGetSchedule:
    """Verify get_schedule returns appointments in order."""

    @pytest.mark.asyncio
    async def test_get_schedule_returns_list(self):
        """get_schedule returns all appointments for clinician in date range."""
        from app.modules.appointments.service import AppointmentService

        appts = [_make_appt(), _make_appt(), _make_appt()]
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = appts
        db.execute = AsyncMock(return_value=mock_result)

        svc = AppointmentService()
        result = await svc.get_schedule(
            db=db,
            clinician_id=uuid.uuid4(),
            date_from=_START,
            date_to=_START + timedelta(days=7),
        )

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_schedule_empty(self):
        """get_schedule returns empty list when no appointments exist."""
        from app.modules.appointments.service import AppointmentService

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        svc = AppointmentService()
        result = await svc.get_schedule(
            db=db,
            clinician_id=uuid.uuid4(),
            date_from=_START,
            date_to=_END,
        )

        assert result == []


# ===========================================================================
# AppointmentService.get_appointment — not found
# ===========================================================================
class TestGetAppointmentNotFound:
    """Verify get_appointment raises when UUID does not exist."""

    @pytest.mark.asyncio
    async def test_get_appointment_not_found(self):
        """get_appointment raises AppointmentNotFoundError for unknown UUID."""
        from app.modules.appointments.service import AppointmentService

        db = _mock_db(first_val=None)
        svc = AppointmentService()

        with pytest.raises(AppointmentNotFoundError):
            await svc.get_appointment(db=db, appointment_id=uuid.uuid4())


# ===========================================================================
# WaitlistService.add_to_waitlist
# ===========================================================================
class TestAddToWaitlist:
    """Verify waitlist entry creation."""

    @pytest.mark.asyncio
    async def test_add_creates_entry_with_waiting_status(self):
        """add_to_waitlist creates a Waitlist entry with WAITING status."""
        from app.modules.appointments.service_waitlist import WaitlistService

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        svc = WaitlistService()
        with patch("app.modules.appointments.service_waitlist._audit", _mock_audit):
            result = await svc.add_to_waitlist(
                db=db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                appt_type=AppointmentType.CONSULTATION,
                preferred_date_start=date(2025, 9, 1),
                created_by=uuid.uuid4(),
                priority=1,
                notes="Urgent follow-up",
            )

        assert db.add.called
        added = db.add.call_args[0][0]
        assert added.status == WaitlistStatus.WAITING
        assert added.priority == 1

    @pytest.mark.asyncio
    async def test_add_with_clinician_preference(self):
        """add_to_waitlist stores optional clinician preference."""
        from app.modules.appointments.service_waitlist import WaitlistService

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        clinician = uuid.uuid4()
        svc = WaitlistService()
        with patch("app.modules.appointments.service_waitlist._audit", _mock_audit):
            await svc.add_to_waitlist(
                db=db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                appt_type=AppointmentType.FOLLOW_UP,
                preferred_date_start=date(2025, 9, 15),
                created_by=uuid.uuid4(),
                clinician_id=clinician,
            )

        added = db.add.call_args[0][0]
        assert added.clinician_id == clinician


# ===========================================================================
# WaitlistService.promote_from_waitlist — no candidates
# ===========================================================================
class TestPromoteWaitlistNoCandidates:
    """Verify promote_from_waitlist returns None when no WAITING entries exist."""

    @pytest.mark.asyncio
    async def test_promote_returns_none_when_empty(self):
        """promote_from_waitlist returns None when no matching WAITING entries exist."""
        from app.modules.appointments.service_waitlist import WaitlistService

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        svc = WaitlistService()
        result = await svc.promote_from_waitlist(
            db=db,
            tenant_id=uuid.uuid4(),
            clinician_id=uuid.uuid4(),
            freed_slot_start=_START,
            freed_slot_end=_END,
        )

        assert result is None


# ===========================================================================
# RecurrenceService — edge cases
# ===========================================================================
class TestRecurrenceEdgeCases:
    """Verify recurrence generation edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_frequency_raises_value_error(self):
        """generate_recurring with unknown frequency raises ValueError."""
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent = _make_appt()
        db = _mock_db(first_val=parent)
        svc = RecurrenceService()

        with patch("app.modules.appointments.service_recurrence._audit", _mock_audit), \
             patch("app.modules.appointments.service._audit", _mock_audit):
            with pytest.raises(ValueError, match="Unsupported recurrence frequency"):
                await svc.generate_recurring(
                    db=db,
                    appointment_id=parent.id,
                    rule={"frequency": "hourly", "interval": 1, "count": 3},
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_count_one_produces_no_children(self):
        """generate_recurring with count=1 creates zero children (parent is occurrence #1)."""
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent = _make_appt()
        db = _mock_db(first_val=parent)
        svc = RecurrenceService()

        with patch("app.modules.appointments.service_recurrence._audit", _mock_audit), \
             patch("app.modules.appointments.service._audit", _mock_audit):
            children = await svc.generate_recurring(
                db=db,
                appointment_id=parent.id,
                rule={"frequency": "weekly", "interval": 1, "count": 1},
                user_id=uuid.uuid4(),
            )

        assert children == []


# ===========================================================================
# Pydantic Schemas
# ===========================================================================
class TestAppointmentSchemas:
    """Verify request/response schemas validate and serialize correctly."""

    def test_appointment_create_valid(self):
        """AppointmentCreate accepts a well-formed payload."""
        obj = AppointmentCreate(
            patient_id=uuid.uuid4(),
            clinician_id=uuid.uuid4(),
            appointment_type=AppointmentType.CONSULTATION,
            scheduled_start=_START,
            scheduled_end=_END,
            reason="Annual checkup",
        )
        assert obj.appointment_type == AppointmentType.CONSULTATION
        assert obj.is_recurring is False

    def test_appointment_reschedule_valid(self):
        """AppointmentReschedule parses new time window."""
        obj = AppointmentReschedule(
            new_start=_START + timedelta(days=1),
            new_end=_END + timedelta(days=1),
        )
        assert obj.new_start > _START

    def test_appointment_cancel_valid(self):
        """AppointmentCancel accepts a reason string."""
        obj = AppointmentCancel(reason="Patient requested cancellation")
        assert obj.reason == "Patient requested cancellation"

    def test_waitlist_create_default_priority(self):
        """WaitlistCreate defaults priority to 0."""
        obj = WaitlistCreate(
            patient_id=uuid.uuid4(),
            appointment_type=AppointmentType.FOLLOW_UP,
            preferred_date_start=date(2025, 9, 1),
        )
        assert obj.priority == 0

    def test_waitlist_create_rejects_negative_priority(self):
        """WaitlistCreate rejects negative priority values."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            WaitlistCreate(
                patient_id=uuid.uuid4(),
                appointment_type=AppointmentType.FOLLOW_UP,
                preferred_date_start=date(2025, 9, 1),
                priority=-1,
            )

    def test_appointment_reason_max_length(self):
        """AppointmentCreate rejects reason longer than 500 chars."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            AppointmentCreate(
                patient_id=uuid.uuid4(),
                clinician_id=uuid.uuid4(),
                appointment_type=AppointmentType.CONSULTATION,
                scheduled_start=_START,
                scheduled_end=_END,
                reason="x" * 501,
            )


# ===========================================================================
# Enum completeness
# ===========================================================================
class TestEnumValues:
    """Verify all enum members are present."""

    def test_appointment_type_values(self):
        """AppointmentType contains all expected clinical types."""
        expected = {"consultation", "follow_up", "procedure", "screening", "urgent"}
        assert {e.value for e in AppointmentType} == expected

    def test_appointment_status_values(self):
        """AppointmentStatus contains all lifecycle states."""
        expected = {
            "scheduled", "confirmed", "checked_in",
            "in_progress", "completed", "cancelled", "no_show",
        }
        assert {e.value for e in AppointmentStatus} == expected

    def test_waitlist_status_values(self):
        """WaitlistStatus contains all waitlist lifecycle states."""
        expected = {"waiting", "offered", "booked", "expired", "cancelled"}
        assert {e.value for e in WaitlistStatus} == expected


# ===========================================================================
# Custom Exceptions
# ===========================================================================
class TestExceptions:
    """Verify exception constructors store fields and messages are PHI-safe."""

    def test_appointment_not_found_stores_id(self):
        """AppointmentNotFoundError stores appointment_id attribute."""
        appt_id = str(uuid.uuid4())
        err = AppointmentNotFoundError(appt_id)
        assert err.appointment_id == appt_id
        assert appt_id in str(err)

    def test_double_booking_stores_clinician_id(self):
        """DoubleBookingError stores clinician_id attribute."""
        clin_id = str(uuid.uuid4())
        err = DoubleBookingError(clin_id)
        assert err.clinician_id == clin_id
        assert clin_id in str(err)

    def test_invalid_state_stores_fields(self):
        """InvalidAppointmentStateError stores all three diagnostic fields."""
        appt_id = str(uuid.uuid4())
        err = InvalidAppointmentStateError(
            appt_id, AppointmentStatus.COMPLETED, "reschedule"
        )
        assert err.appointment_id == appt_id
        assert err.current_status == AppointmentStatus.COMPLETED
        assert err.attempted_action == "reschedule"

    def test_appointment_not_found_is_exception(self):
        """AppointmentNotFoundError inherits from Exception."""
        assert isinstance(AppointmentNotFoundError("x"), Exception)

    def test_double_booking_is_exception(self):
        """DoubleBookingError inherits from Exception."""
        assert isinstance(DoubleBookingError("x"), Exception)

    def test_invalid_state_is_exception(self):
        """InvalidAppointmentStateError inherits from Exception."""
        assert isinstance(
            InvalidAppointmentStateError("x", "scheduled", "cancel"), Exception
        )
