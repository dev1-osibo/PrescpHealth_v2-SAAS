"""
Unit tests for LabOrderService business logic.

Tests the service methods with mocked database to verify status
transitions, specimen collection, and listing logic.

Validates:
- update_status rejects invalid transitions (resulted → in_progress)
- update_status accepts valid transitions (ordered → specimen_collected)
- collect_specimen rejects non-ordered orders
- collect_specimen succeeds for ordered orders
- get_lab_order raises LabOrderNotFoundError for missing order
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.lab_orders.enums import LabOrderStatus
from app.modules.lab_orders.exceptions import (
    InvalidLabOrderStatusTransitionError,
    LabOrderNotFoundError,
)
from app.modules.lab_orders.service import LabOrderService, _VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def lab_service():
    """Create a LabOrderService with mocked dependencies."""
    service = LabOrderService()
    service._audit = MagicMock()
    service._audit.log = AsyncMock()
    service._code_catalog = MagicMock()
    service._code_catalog.validate_code = AsyncMock()
    return service


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test: Status transition validation
# ---------------------------------------------------------------------------
class TestStatusTransitions:
    """Verify the lab order state machine enforces valid transitions."""

    def test_valid_transitions_map_has_all_statuses(self):
        """Every LabOrderStatus value must appear in the transitions map."""
        for status in LabOrderStatus:
            assert status.value in _VALID_TRANSITIONS

    def test_terminal_states_have_no_transitions(self):
        """Resulted and cancelled are terminal — no outgoing transitions."""
        assert _VALID_TRANSITIONS[LabOrderStatus.RESULTED.value] == set()
        assert _VALID_TRANSITIONS[LabOrderStatus.CANCELLED.value] == set()

    @pytest.mark.asyncio
    async def test_update_status_rejects_invalid_transition(self, lab_service, mock_db):
        """update_status raises error for resulted → in_progress."""
        order_id = uuid.uuid4()
        mock_order = SimpleNamespace(
            id=order_id,
            status=LabOrderStatus.RESULTED.value,
            tenant_id=uuid.uuid4(),
            results=[],
        )

        with patch.object(
            lab_service, "get_lab_order", new_callable=AsyncMock, return_value=mock_order
        ):
            with pytest.raises(InvalidLabOrderStatusTransitionError):
                await lab_service.update_status(
                    db=mock_db,
                    order_id=order_id,
                    new_status=LabOrderStatus.IN_PROGRESS.value,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_update_status_accepts_valid_transition(self, lab_service, mock_db):
        """update_status succeeds for ordered → specimen_collected."""
        order_id = uuid.uuid4()
        mock_order = SimpleNamespace(
            id=order_id,
            status=LabOrderStatus.ORDERED.value,
            tenant_id=uuid.uuid4(),
            results=[],
        )

        with patch.object(
            lab_service, "get_lab_order", new_callable=AsyncMock, return_value=mock_order
        ):
            result = await lab_service.update_status(
                db=mock_db,
                order_id=order_id,
                new_status=LabOrderStatus.SPECIMEN_COLLECTED.value,
                user_id=uuid.uuid4(),
            )

        assert result.status == LabOrderStatus.SPECIMEN_COLLECTED.value


# ---------------------------------------------------------------------------
# Test: Specimen collection
# ---------------------------------------------------------------------------
class TestCollectSpecimen:
    """Verify collect_specimen enforces ordered-only rule."""

    @pytest.mark.asyncio
    async def test_rejects_non_ordered_status(self, lab_service, mock_db):
        """collect_specimen raises error if order is not in 'ordered' status."""
        order_id = uuid.uuid4()
        mock_order = SimpleNamespace(
            id=order_id,
            status=LabOrderStatus.IN_PROGRESS.value,
            tenant_id=uuid.uuid4(),
            results=[],
        )

        with patch.object(
            lab_service, "get_lab_order", new_callable=AsyncMock, return_value=mock_order
        ):
            with pytest.raises(InvalidLabOrderStatusTransitionError):
                await lab_service.collect_specimen(
                    db=mock_db,
                    order_id=order_id,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_succeeds_for_ordered_status(self, lab_service, mock_db):
        """collect_specimen sets status and timestamp for ordered orders."""
        order_id = uuid.uuid4()
        mock_order = SimpleNamespace(
            id=order_id,
            status=LabOrderStatus.ORDERED.value,
            tenant_id=uuid.uuid4(),
            specimen_collected_at=None,
            results=[],
        )

        with patch.object(
            lab_service, "get_lab_order", new_callable=AsyncMock, return_value=mock_order
        ):
            result = await lab_service.collect_specimen(
                db=mock_db,
                order_id=order_id,
                user_id=uuid.uuid4(),
            )

        assert result.status == LabOrderStatus.SPECIMEN_COLLECTED.value
        assert result.specimen_collected_at is not None


# ---------------------------------------------------------------------------
# Test: get_lab_order raises for missing order
# ---------------------------------------------------------------------------
class TestGetLabOrder:
    """Verify get_lab_order raises LabOrderNotFoundError."""

    @pytest.mark.asyncio
    async def test_raises_for_missing_order(self, lab_service, mock_db):
        """get_lab_order raises LabOrderNotFoundError when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(LabOrderNotFoundError):
            await lab_service.get_lab_order(mock_db, uuid.uuid4())
