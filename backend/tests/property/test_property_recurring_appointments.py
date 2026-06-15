"""
Property Test: Recurring Appointment Generation (Property 10).

Invariant:
    The recurrence engine generates exactly `count - 1` child appointments
    (parent is occurrence #1), each spaced by the correct frequency-interval
    delta. All children share the same clinician_id, patient_id, and duration.

Why this matters (Clinical Scheduling):
    Patients with chronic conditions need regular follow-ups. If the
    recurrence engine miscounts, skips intervals, or drifts in timing,
    patients may miss critical appointments or be double-booked.

Tested service: app.modules.appointments.service_recurrence.RecurrenceService
Method: generate_recurring(db, appointment_id, rule, user_id)

Supported frequencies: daily, weekly (biweekly = weekly + interval 2), monthly
Count range tested: 1–12 instances

**Validates: Requirement — Recurring appointment generation correctness**
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.appointments.enums import AppointmentStatus, AppointmentType

# Import models so SQLAlchemy mappers resolve correctly
import app.modules.appointments.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate recurrence rule parameters
# ---------------------------------------------------------------------------

# Frequency options (biweekly is weekly with interval=2)
frequency_strategy = st.sampled_from(["daily", "weekly", "monthly"])
count_strategy = st.integers(min_value=1, max_value=12)
interval_strategy = st.integers(min_value=1, max_value=4)

# Start times in a reasonable clinical range
start_datetime_strategy = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2026, 6, 30),
)

# Appointment duration in minutes (15 min to 2 hours)
duration_minutes_strategy = st.integers(min_value=15, max_value=120)

# Frequency label → timedelta factory (mirrors service logic)
_FREQUENCY_DELTAS = {
    "daily": lambda interval: timedelta(days=interval),
    "weekly": lambda interval: timedelta(weeks=interval),
    "monthly": lambda interval: timedelta(days=30 * interval),
}


# ---------------------------------------------------------------------------
# Property Tests: Recurring Appointment Generation
# ---------------------------------------------------------------------------
class TestRecurringAppointments:
    """
    Property-based tests proving recurrence generation correctness.

    Core invariants:
    1. Exactly count-1 child appointments generated
    2. Each child's scheduled_start matches expected interval from previous
    3. All children share the same duration as the original
    """

    @given(
        frequency=frequency_strategy,
        count=count_strategy,
        interval=interval_strategy,
        start_time=start_datetime_strategy,
        duration_min=duration_minutes_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_correct_count_generated(
        self, frequency, count, interval, start_time, duration_min
    ):
        """
        Property: generate_recurring produces exactly count-1 child
        appointments. The parent appointment itself is occurrence #1,
        so the service creates N-1 additional instances.
        """
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent_id = uuid.uuid4()
        user_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        end_time = start_time + timedelta(minutes=duration_min)

        # Mock the parent appointment object
        mock_parent = MagicMock()
        mock_parent.id = parent_id
        mock_parent.tenant_id = tenant_id
        mock_parent.patient_id = patient_id
        mock_parent.clinician_id = clinician_id
        mock_parent.appointment_type = AppointmentType.FOLLOW_UP
        mock_parent.scheduled_start = start_time
        mock_parent.scheduled_end = end_time
        mock_parent.reason = "Recurring follow-up"
        mock_parent.notes = None
        mock_parent.is_recurring = False
        mock_parent.recurrence_rule = None

        rule = {"frequency": frequency, "interval": interval, "count": count}

        # Mock DB and service dependencies
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.modules.appointments.service_recurrence.AppointmentService"
        ) as MockApptSvc, patch(
            "app.modules.appointments.service_recurrence._audit",
            new_callable=MagicMock,
        ) as mock_audit:
            mock_audit.log_action = AsyncMock()
            mock_svc_instance = AsyncMock()
            mock_svc_instance.get_appointment.return_value = mock_parent
            MockApptSvc.return_value = mock_svc_instance

            service = RecurrenceService()
            children = await service.generate_recurring(
                db=mock_db,
                appointment_id=parent_id,
                rule=rule,
                user_id=user_id,
            )

        # INVARIANT: Exactly count-1 children generated
        expected_children = max(0, count - 1)
        assert len(children) == expected_children, (
            f"Expected {expected_children} children for count={count}, "
            f"got {len(children)}"
        )

    @given(
        frequency=frequency_strategy,
        count=st.integers(min_value=2, max_value=12),
        interval=interval_strategy,
        start_time=start_datetime_strategy,
        duration_min=duration_minutes_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_correct_interval_spacing(
        self, frequency, count, interval, start_time, duration_min
    ):
        """
        Property: Each child appointment's scheduled_start is exactly
        one frequency-interval delta after the previous occurrence.

        For daily/interval=2: each child is 2 days after the prior.
        For weekly/interval=1: each child is 7 days after the prior.
        For weekly/interval=2 (biweekly): each child is 14 days after prior.
        For monthly/interval=1: each child is 30 days after the prior.
        """
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent_id = uuid.uuid4()
        user_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        end_time = start_time + timedelta(minutes=duration_min)
        expected_delta = _FREQUENCY_DELTAS[frequency](interval)

        mock_parent = MagicMock()
        mock_parent.id = parent_id
        mock_parent.tenant_id = tenant_id
        mock_parent.patient_id = patient_id
        mock_parent.clinician_id = clinician_id
        mock_parent.appointment_type = AppointmentType.FOLLOW_UP
        mock_parent.scheduled_start = start_time
        mock_parent.scheduled_end = end_time
        mock_parent.reason = "Recurring follow-up"
        mock_parent.notes = None
        mock_parent.is_recurring = False
        mock_parent.recurrence_rule = None

        rule = {"frequency": frequency, "interval": interval, "count": count}

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.modules.appointments.service_recurrence.AppointmentService"
        ) as MockApptSvc, patch(
            "app.modules.appointments.service_recurrence._audit",
            new_callable=MagicMock,
        ) as mock_audit:
            mock_audit.log_action = AsyncMock()
            mock_svc_instance = AsyncMock()
            mock_svc_instance.get_appointment.return_value = mock_parent
            MockApptSvc.return_value = mock_svc_instance

            service = RecurrenceService()
            children = await service.generate_recurring(
                db=mock_db,
                appointment_id=parent_id,
                rule=rule,
                user_id=user_id,
            )

        # INVARIANT: Each child is spaced by exactly one delta from previous
        previous_start = start_time
        for i, child in enumerate(children):
            expected_start = previous_start + expected_delta
            assert child.scheduled_start == expected_start, (
                f"Child {i}: expected start {expected_start}, "
                f"got {child.scheduled_start}"
            )
            previous_start = child.scheduled_start

    @given(
        frequency=frequency_strategy,
        count=st.integers(min_value=2, max_value=12),
        interval=interval_strategy,
        start_time=start_datetime_strategy,
        duration_min=duration_minutes_strategy,
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_children_same_duration(
        self, frequency, count, interval, start_time, duration_min
    ):
        """
        Property: All generated children have the same duration as
        the parent appointment.

        Duration = scheduled_end - scheduled_start must be constant
        across all occurrences in the series.
        """
        from app.modules.appointments.service_recurrence import RecurrenceService

        parent_id = uuid.uuid4()
        user_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        end_time = start_time + timedelta(minutes=duration_min)
        expected_duration = end_time - start_time

        mock_parent = MagicMock()
        mock_parent.id = parent_id
        mock_parent.tenant_id = tenant_id
        mock_parent.patient_id = patient_id
        mock_parent.clinician_id = clinician_id
        mock_parent.appointment_type = AppointmentType.FOLLOW_UP
        mock_parent.scheduled_start = start_time
        mock_parent.scheduled_end = end_time
        mock_parent.reason = "Recurring follow-up"
        mock_parent.notes = None
        mock_parent.is_recurring = False
        mock_parent.recurrence_rule = None

        rule = {"frequency": frequency, "interval": interval, "count": count}

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch(
            "app.modules.appointments.service_recurrence.AppointmentService"
        ) as MockApptSvc, patch(
            "app.modules.appointments.service_recurrence._audit",
            new_callable=MagicMock,
        ) as mock_audit:
            mock_audit.log_action = AsyncMock()
            mock_svc_instance = AsyncMock()
            mock_svc_instance.get_appointment.return_value = mock_parent
            MockApptSvc.return_value = mock_svc_instance

            service = RecurrenceService()
            children = await service.generate_recurring(
                db=mock_db,
                appointment_id=parent_id,
                rule=rule,
                user_id=user_id,
            )

        # INVARIANT: All children have the same duration as parent
        for i, child in enumerate(children):
            child_duration = child.scheduled_end - child.scheduled_start
            assert child_duration == expected_duration, (
                f"Child {i}: duration {child_duration} != {expected_duration}"
            )
