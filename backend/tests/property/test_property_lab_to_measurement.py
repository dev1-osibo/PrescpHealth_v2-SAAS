"""
Property Test: Lab Result to Measurement Pipeline (Property 8).

Invariant:
    When a lab result is recorded for a LOINC code that maps to a
    MeasurementType:
    1. Exactly one Measurement record is created with the same value
    2. Exactly one MeasurementSaved domain event is published

    When a lab result is recorded for an UNMAPPED LOINC code:
    - No Measurement record is created
    - No MeasurementSaved event is published

Clinical Safety:
    The lab-to-measurement pipeline feeds the risk computation engine.
    Missing measurements → inaccurate risk scores → missed clinical alerts.
    Duplicate measurements → inflated risk scores → false alarms.

Validates: Requirement 3.7
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.lab_orders.loinc_to_measurement import _LOINC_TO_MEASUREMENT
from app.modules.lab_orders.service_results import LabResultService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_mapped_loinc_st = st.sampled_from(list(_LOINC_TO_MEASUREMENT.keys()))

_unmapped_loinc_st = st.sampled_from([
    "58410-2", "6690-2", "718-7", "789-8", "1742-6",
    "1920-8", "2532-0", "5902-2", "3094-0", "2951-2",
])

_numeric_value_st = st.floats(
    min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_mock_db():
    """Create a mock AsyncSession that tracks added objects."""
    db = AsyncMock()
    db.added = []

    def _track_add(obj):
        db.added.append(obj)

    db.add = MagicMock(side_effect=_track_add)
    db.flush = AsyncMock()
    return db


def _build_mock_lab_order(loinc_code: str, patient_id: uuid.UUID):
    """Create a mock lab order with the specified LOINC code."""
    order = MagicMock()
    order.id = uuid.uuid4()
    order.loinc_code = loinc_code
    order.patient_id = patient_id
    order.status = "ordered"
    return order


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestLabToMeasurementPipeline:
    """Property 8: Lab results create Measurements + publish events correctly."""

    @given(loinc_code=_mapped_loinc_st, numeric_value=_numeric_value_st)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_mapped_loinc_creates_measurement_and_event(
        self, loinc_code, numeric_value
    ):
        """Mapped LOINC codes produce exactly one Measurement + one MeasurementSaved event."""
        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        order_id = uuid.uuid4()

        mock_db = _build_mock_db()
        mock_order = _build_mock_lab_order(loinc_code, patient_id)
        mock_order.id = order_id

        # Patch dependencies to isolate the service
        with (
            patch.object(
                LabResultService, "__init__", lambda self: None
            ),
            patch(
                "app.modules.lab_orders.service_results.event_bus"
            ) as mock_event_bus,
            patch(
                "app.modules.lab_orders.service_results.AuditService"
            ) as MockAudit,
            patch(
                "app.modules.lab_orders.service_results.get_request_id",
                return_value="test-corr-id",
            ),
        ):
            mock_event_bus.publish = AsyncMock()
            MockAudit.return_value.log = AsyncMock()

            svc = LabResultService()
            svc._lab_order_service = MagicMock()
            svc._lab_order_service.get_lab_order = AsyncMock(return_value=mock_order)
            svc._audit = MockAudit.return_value

            result = await svc.record_result(
                db=mock_db,
                order_id=order_id,
                tenant_id=tenant_id,
                user_id=user_id,
                value=str(numeric_value),
                numeric_value=numeric_value,
                unit="mg/dL",
                reference_range_low=50.0,
                reference_range_high=200.0,
                resulted_at=datetime.now(timezone.utc),
            )

            # Count Measurement objects added to the session
            from app.modules.measurements.models import Measurement
            measurements = [
                obj for obj in mock_db.added if isinstance(obj, Measurement)
            ]

            # INVARIANT: Exactly one Measurement created
            assert len(measurements) == 1, (
                f"Expected 1 Measurement, got {len(measurements)} "
                f"for LOINC {loinc_code}"
            )
            assert measurements[0].value == numeric_value

            # INVARIANT: MeasurementSaved event published
            from app.core.events import MeasurementSaved
            event_calls = mock_event_bus.publish.call_args_list
            measurement_events = [
                c for c in event_calls
                if isinstance(c[0][0], MeasurementSaved)
            ]
            assert len(measurement_events) == 1, (
                f"Expected 1 MeasurementSaved event, got {len(measurement_events)}"
            )

    @given(loinc_code=_unmapped_loinc_st, numeric_value=_numeric_value_st)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_unmapped_loinc_no_measurement_no_event(
        self, loinc_code, numeric_value
    ):
        """Unmapped LOINC codes produce NO Measurement and NO MeasurementSaved event."""
        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        order_id = uuid.uuid4()

        mock_db = _build_mock_db()
        mock_order = _build_mock_lab_order(loinc_code, patient_id)
        mock_order.id = order_id

        with (
            patch.object(
                LabResultService, "__init__", lambda self: None
            ),
            patch(
                "app.modules.lab_orders.service_results.event_bus"
            ) as mock_event_bus,
            patch(
                "app.modules.lab_orders.service_results.AuditService"
            ) as MockAudit,
            patch(
                "app.modules.lab_orders.service_results.get_request_id",
                return_value="test-corr-id",
            ),
        ):
            mock_event_bus.publish = AsyncMock()
            MockAudit.return_value.log = AsyncMock()

            svc = LabResultService()
            svc._lab_order_service = MagicMock()
            svc._lab_order_service.get_lab_order = AsyncMock(return_value=mock_order)
            svc._audit = MockAudit.return_value

            await svc.record_result(
                db=mock_db,
                order_id=order_id,
                tenant_id=tenant_id,
                user_id=user_id,
                value=str(numeric_value),
                numeric_value=numeric_value,
                unit="mg/dL",
                reference_range_low=50.0,
                reference_range_high=200.0,
                resulted_at=datetime.now(timezone.utc),
            )

            # Count Measurement objects — should be zero
            from app.modules.measurements.models import Measurement
            measurements = [
                obj for obj in mock_db.added if isinstance(obj, Measurement)
            ]
            assert len(measurements) == 0, (
                f"Unmapped LOINC {loinc_code} should create 0 Measurements, "
                f"got {len(measurements)}"
            )

            # No MeasurementSaved event should be published
            from app.core.events import MeasurementSaved
            event_calls = mock_event_bus.publish.call_args_list
            measurement_events = [
                c for c in event_calls
                if isinstance(c[0][0], MeasurementSaved)
            ]
            assert len(measurement_events) == 0, (
                f"Unmapped LOINC {loinc_code} should publish 0 MeasurementSaved events"
            )
