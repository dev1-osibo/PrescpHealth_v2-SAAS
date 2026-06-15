"""
Property Test: Appointment Double-Booking Prevention (Property 9).

Invariant:
    Overlapping appointments for the same clinician are ALWAYS rejected
    with DoubleBookingError. Non-overlapping appointments succeed.
    Adjacent appointments (end of one = start of next) are ALLOWED.

    Overlap definition: new_start < existing_end AND new_end > existing_start

Why this matters (Patient Safety & Scheduling Integrity):
    Double-booking a clinician means a patient may not receive the care
    they were promised, or the clinician is stretched between two
    simultaneous obligations. The system must enforce mutual exclusion
    at the service layer regardless of what time ranges are generated.

Tested service: app.modules.appointments.service.AppointmentService
Method: book_appointment(db, ...)

**Validates: Requirement — Appointment double-booking prevention**
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume, strategies as st

from app.modules.appointments.enums import AppointmentStatus, AppointmentType
from app.modules.appointments.exceptions import DoubleBookingError

# Import models so SQLAlchemy mappers resolve correctly
import app.modules.appointments.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate appointment time ranges
# ---------------------------------------------------------------------------

# Base datetimes in a reasonable clinical range (2024–2026)
base_datetime_strategy = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2026, 12, 31),
)

# Duration in minutes (15 min to 4 hours — realistic appointment lengths)
duration_minutes_strategy = st.integers(min_value=15, max_value=240)


# ---------------------------------------------------------------------------
# Property Tests: Double-Booking Prevention
# ---------------------------------------------------------------------------
class TestDoubleBookingPrevention:
    """
    Property-based tests proving the double-booking guard correctness.

    Core invariants:
    1. Overlapping time ranges → DoubleBookingError raised
    2. Non-overlapping time ranges → booking succeeds
    3. Adjacent appointments (end == start of next) → allowed
    """

    @given(
        existing_start=base_datetime_strategy,
        existing_duration=duration_minutes_strategy,
        offset_minutes=st.integers(min_value=1, max_value=239),
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_overlapping_rejected(
        self, existing_start, existing_duration, offset_minutes
    ):
        """
        Property: If a new appointment's time range overlaps with an
        existing appointment for the same clinician, booking MUST raise
        DoubleBookingError.

        We construct overlap by starting the new appointment before the
        existing one ends (offset < existing_duration ensures overlap).
        """
        from app.modules.appointments.service import AppointmentService

        # Ensure offset is strictly less than duration to guarantee overlap
        assume(offset_minutes < existing_duration)

        existing_end = existing_start + timedelta(minutes=existing_duration)

        # New appointment starts during the existing appointment
        new_start = existing_start + timedelta(minutes=offset_minutes)
        new_end = new_start + timedelta(minutes=30)

        # Verify the overlap condition holds
        assert new_start < existing_end and new_end > existing_start

        clinician_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Mock: DB returns an existing conflicting appointment
        mock_existing = MagicMock()
        mock_existing.id = uuid.uuid4()
        mock_existing.clinician_id = clinician_id
        mock_existing.status = AppointmentStatus.SCHEDULED
        mock_existing.scheduled_start = existing_start
        mock_existing.scheduled_end = existing_end

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_existing
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service = AppointmentService()

        # INVARIANT: Must raise DoubleBookingError for overlapping times
        with pytest.raises(DoubleBookingError):
            await service.book_appointment(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=uuid.uuid4(),
                clinician_id=clinician_id,
                appt_type=AppointmentType.CONSULTATION,
                start=new_start,
                end=new_end,
                reason="Test appointment",
                created_by=uuid.uuid4(),
            )

    @given(
        existing_start=base_datetime_strategy,
        existing_duration=duration_minutes_strategy,
        gap_minutes=st.integers(min_value=1, max_value=480),
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_non_overlapping_succeeds(
        self, existing_start, existing_duration, gap_minutes
    ):
        """
        Property: If a new appointment's time range does NOT overlap
        with any existing appointment for the clinician, booking
        succeeds and returns an Appointment object.

        We ensure no overlap by starting the new appointment after
        the existing one ends (with a positive gap).
        """
        from app.modules.appointments.service import AppointmentService

        existing_end = existing_start + timedelta(minutes=existing_duration)

        # New appointment starts AFTER existing ends (gap guarantees no overlap)
        new_start = existing_end + timedelta(minutes=gap_minutes)
        new_end = new_start + timedelta(minutes=30)

        # Verify non-overlap condition holds
        assert not (new_start < existing_end and new_end > existing_start)

        clinician_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Mock: DB conflict check returns NO existing appointment
        mock_db = AsyncMock()
        mock_conflict_result = MagicMock()
        mock_conflict_scalars = MagicMock()
        mock_conflict_scalars.first.return_value = None
        mock_conflict_result.scalars.return_value = mock_conflict_scalars
        mock_db.execute.return_value = mock_conflict_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch(
            "app.modules.appointments.service._audit",
            new_callable=MagicMock,
        ) as mock_audit:
            mock_audit.log_action = AsyncMock()
            service = AppointmentService()
            # INVARIANT: Booking must succeed (no exception raised)
            await service.book_appointment(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=uuid.uuid4(),
                clinician_id=clinician_id,
                appt_type=AppointmentType.CONSULTATION,
                start=new_start,
                end=new_end,
                reason="Test appointment",
                created_by=uuid.uuid4(),
            )

        # Verify appointment was persisted
        assert mock_db.add.called, "Appointment not added to DB session"
        assert mock_db.commit.called, "Transaction not committed"

    @given(
        existing_start=base_datetime_strategy,
        existing_duration=duration_minutes_strategy,
        new_duration=duration_minutes_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_adjacent_appointments_allowed(
        self, existing_start, existing_duration, new_duration
    ):
        """
        Property (Edge Case): Adjacent appointments where end of one
        equals start of next are ALLOWED. This is the boundary condition
        — a clinician can have back-to-back appointments with zero gap.

        The overlap check uses strict inequality (start < end AND end > start),
        so when new_start == existing_end there is no overlap.
        """
        from app.modules.appointments.service import AppointmentService

        existing_end = existing_start + timedelta(minutes=existing_duration)

        # New appointment starts exactly when existing ends (adjacent)
        new_start = existing_end
        new_end = new_start + timedelta(minutes=new_duration)

        # Verify adjacency: NOT overlapping (new_start == existing_end
        # means new_start < existing_end is False)
        assert not (new_start < existing_end)

        clinician_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Mock: DB conflict check returns NO conflict (adjacent is not overlap)
        mock_db = AsyncMock()
        mock_conflict_result = MagicMock()
        mock_conflict_scalars = MagicMock()
        mock_conflict_scalars.first.return_value = None
        mock_conflict_result.scalars.return_value = mock_conflict_scalars
        mock_db.execute.return_value = mock_conflict_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch(
            "app.modules.appointments.service._audit",
            new_callable=MagicMock,
        ) as mock_audit:
            mock_audit.log_action = AsyncMock()
            service = AppointmentService()
            # INVARIANT: Adjacent booking must succeed (no exception)
            await service.book_appointment(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=uuid.uuid4(),
                clinician_id=clinician_id,
                appt_type=AppointmentType.FOLLOW_UP,
                start=new_start,
                end=new_end,
                reason="Adjacent follow-up",
                created_by=uuid.uuid4(),
            )

        # Verify appointment was persisted
        assert mock_db.add.called, "Adjacent appointment not added to DB"
        assert mock_db.commit.called, "Adjacent transaction not committed"
