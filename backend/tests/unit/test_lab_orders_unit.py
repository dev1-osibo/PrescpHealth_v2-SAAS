"""
PrescpHealth Backend — Lab Orders Module Unit Tests (Task 5.11).

Tests lab order business logic with a fully mocked database layer:
1. LOINC code validation (valid and invalid)
2. Lab order status transitions (state machine enforcement)
3. Abnormal result alert/event pathway
4. Measurement creation from mapped LOINC lab results

All data is synthetic — no PHI. No real DB connections.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.lab_orders.enums import LabOrderStatus
from app.modules.lab_orders.exceptions import (
    InvalidLabOrderStatusTransitionError,
)
from app.modules.lab_orders.service import LabOrderService
from app.modules.lab_orders.service_results import LabResultService
from app.modules.code_catalogs.exceptions import InvalidCodeError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Async database session mock — no real DB connection."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def ids():
    """Synthetic UUIDs for test isolation."""
    return {
        "tenant": uuid.uuid4(),
        "patient": uuid.uuid4(),
        "user": uuid.uuid4(),
        "encounter": uuid.uuid4(),
        "order": uuid.uuid4(),
    }


# ---------------------------------------------------------------------------
# 1. LOINC Validation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_loinc_code_creates_order(mock_db, ids):
    """Valid LOINC codes pass validation and the lab order is created."""
    service = LabOrderService()

    with (
        patch.object(
            service._code_catalog, "validate_code", new_callable=AsyncMock
        ),
        patch.object(service._audit, "log", new_callable=AsyncMock),
    ):
        result = await service.create_lab_order(
            db=mock_db,
            tenant_id=ids["tenant"],
            patient_id=ids["patient"],
            user_id=ids["user"],
            encounter_id=ids["encounter"],
            test_name="Fasting Glucose",
            loinc_code="2345-7",
            priority="routine",
            clinical_indication="Diabetes screening",
        )

    assert result is not None
    assert result.loinc_code == "2345-7"
    assert result.status == LabOrderStatus.ORDERED.value


@pytest.mark.asyncio
async def test_invalid_loinc_code_raises(mock_db, ids):
    """Invalid LOINC codes raise InvalidCodeError before order creation."""
    service = LabOrderService()

    with patch.object(
        service._code_catalog,
        "validate_code",
        new_callable=AsyncMock,
        side_effect=InvalidCodeError(
            catalog_type="LOINC", code="INVALID-99", reason="Code not found"
        ),
    ):
        with pytest.raises(InvalidCodeError):
            await service.create_lab_order(
                db=mock_db,
                tenant_id=ids["tenant"],
                patient_id=ids["patient"],
                user_id=ids["user"],
                encounter_id=ids["encounter"],
                test_name="Unknown Test",
                loinc_code="INVALID-99",
                priority="routine",
            )

    # DB should never have been called — order not created
    mock_db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Status Transitions
# ---------------------------------------------------------------------------
class TestLabOrderStatusTransitions:
    """Validate the lab order state machine allows/rejects transitions."""

    @pytest.mark.asyncio
    async def test_ordered_to_specimen_collected_valid(self, mock_db, ids):
        """Ordered → specimen_collected is a valid transition."""
        service = LabOrderService()

        mock_order = MagicMock()
        mock_order.id = ids["order"]
        mock_order.status = LabOrderStatus.ORDERED.value
        mock_order.tenant_id = ids["tenant"]
        mock_order.results = []

        with (
            patch.object(service, "get_lab_order", return_value=mock_order),
            patch.object(service._audit, "log", new_callable=AsyncMock),
        ):
            result = await service.update_status(
                db=mock_db,
                order_id=ids["order"],
                new_status=LabOrderStatus.SPECIMEN_COLLECTED.value,
                user_id=ids["user"],
            )

        assert result.status == LabOrderStatus.SPECIMEN_COLLECTED.value

    @pytest.mark.asyncio
    async def test_specimen_collected_to_in_progress_valid(self, mock_db, ids):
        """Specimen_collected → in_progress is a valid transition."""
        service = LabOrderService()

        mock_order = MagicMock()
        mock_order.id = ids["order"]
        mock_order.status = LabOrderStatus.SPECIMEN_COLLECTED.value
        mock_order.tenant_id = ids["tenant"]

        with (
            patch.object(service, "get_lab_order", return_value=mock_order),
            patch.object(service._audit, "log", new_callable=AsyncMock),
        ):
            result = await service.update_status(
                db=mock_db,
                order_id=ids["order"],
                new_status=LabOrderStatus.IN_PROGRESS.value,
                user_id=ids["user"],
            )

        assert result.status == LabOrderStatus.IN_PROGRESS.value

    @pytest.mark.asyncio
    async def test_in_progress_to_resulted_valid(self, mock_db, ids):
        """In_progress → resulted is a valid transition."""
        service = LabOrderService()

        mock_order = MagicMock()
        mock_order.id = ids["order"]
        mock_order.status = LabOrderStatus.IN_PROGRESS.value
        mock_order.tenant_id = ids["tenant"]

        with (
            patch.object(service, "get_lab_order", return_value=mock_order),
            patch.object(service._audit, "log", new_callable=AsyncMock),
        ):
            result = await service.update_status(
                db=mock_db,
                order_id=ids["order"],
                new_status=LabOrderStatus.RESULTED.value,
                user_id=ids["user"],
            )

        assert result.status == LabOrderStatus.RESULTED.value

    @pytest.mark.asyncio
    async def test_resulted_to_ordered_invalid(self, mock_db, ids):
        """Resulted → ordered is invalid — resulted is a terminal state."""
        service = LabOrderService()

        mock_order = MagicMock()
        mock_order.id = ids["order"]
        mock_order.status = LabOrderStatus.RESULTED.value
        mock_order.tenant_id = ids["tenant"]

        with patch.object(service, "get_lab_order", return_value=mock_order):
            with pytest.raises(InvalidLabOrderStatusTransitionError):
                await service.update_status(
                    db=mock_db,
                    order_id=ids["order"],
                    new_status=LabOrderStatus.ORDERED.value,
                    user_id=ids["user"],
                )

    @pytest.mark.asyncio
    async def test_cancelled_to_any_invalid(self, mock_db, ids):
        """Cancelled → any status is invalid — cancelled is terminal."""
        service = LabOrderService()

        mock_order = MagicMock()
        mock_order.id = ids["order"]
        mock_order.status = LabOrderStatus.CANCELLED.value
        mock_order.tenant_id = ids["tenant"]

        with patch.object(service, "get_lab_order", return_value=mock_order):
            with pytest.raises(InvalidLabOrderStatusTransitionError):
                await service.update_status(
                    db=mock_db,
                    order_id=ids["order"],
                    new_status=LabOrderStatus.IN_PROGRESS.value,
                    user_id=ids["user"],
                )


# ---------------------------------------------------------------------------
# 3. Abnormal Result Alert Generation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_abnormal_result_publishes_event(mock_db, ids):
    """When a lab result is abnormal, LabResultReceived event is published
    with is_abnormal=True so downstream alert systems can react."""
    service = LabResultService()

    mock_order = MagicMock()
    mock_order.id = ids["order"]
    mock_order.status = LabOrderStatus.IN_PROGRESS.value
    mock_order.patient_id = ids["patient"]
    mock_order.tenant_id = ids["tenant"]
    mock_order.loinc_code = "2345-7"

    with (
        patch.object(
            service._lab_order_service, "get_lab_order", return_value=mock_order
        ),
        patch.object(service._audit, "log", new_callable=AsyncMock),
        patch(
            "app.modules.lab_orders.service_results.map_loinc_to_measurement",
            return_value=None,
        ),
        patch(
            "app.modules.lab_orders.service_results.event_bus.publish",
            new_callable=AsyncMock,
        ) as mock_publish,
    ):
        await service.record_result(
            db=mock_db,
            order_id=ids["order"],
            tenant_id=ids["tenant"],
            user_id=ids["user"],
            value="350",
            numeric_value=350.0,
            unit="mg/dL",
            reference_range_low=70.0,
            reference_range_high=100.0,
            resulted_at=datetime.now(timezone.utc),
        )

    # LabResultReceived event should have been published with is_abnormal=True
    assert mock_publish.called
    event_call = mock_publish.call_args_list[-1]
    event = event_call[0][0]
    assert event.is_abnormal is True


# ---------------------------------------------------------------------------
# 4. Measurement Creation from Lab Result
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mapped_loinc_creates_measurement(mock_db, ids):
    """When a lab result has a mapped LOINC code, a Measurement is created."""
    service = LabResultService()

    mock_order = MagicMock()
    mock_order.id = ids["order"]
    mock_order.status = LabOrderStatus.IN_PROGRESS.value
    mock_order.patient_id = ids["patient"]
    mock_order.tenant_id = ids["tenant"]
    mock_order.loinc_code = "2345-7"  # Maps to BLOOD_GLUCOSE_FASTING

    from app.modules.measurements.models import MeasurementType

    with (
        patch.object(
            service._lab_order_service, "get_lab_order", return_value=mock_order
        ),
        patch.object(service._audit, "log", new_callable=AsyncMock),
        patch(
            "app.modules.lab_orders.service_results.map_loinc_to_measurement",
            return_value=MeasurementType.BLOOD_GLUCOSE_FASTING,
        ),
        patch(
            "app.modules.lab_orders.service_results.event_bus.publish",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.lab_orders.service_results.get_request_id",
            return_value="test-correlation-id",
        ),
    ):
        result = await service.record_result(
            db=mock_db,
            order_id=ids["order"],
            tenant_id=ids["tenant"],
            user_id=ids["user"],
            value="95",
            numeric_value=95.0,
            unit="mg/dL",
            reference_range_low=70.0,
            reference_range_high=100.0,
            resulted_at=datetime.now(timezone.utc),
        )

    # db.add should have been called for both LabResult and Measurement
    assert mock_db.add.call_count >= 2
