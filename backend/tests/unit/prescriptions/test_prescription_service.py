"""
Unit tests for PrescriptionService business logic.

Tests the service methods with mocked database to verify status
transitions (hold, resume, discontinue) and error handling.

Validates:
- hold_prescription rejects non-active prescriptions
- hold_prescription succeeds for active prescriptions
- resume_prescription rejects non-on_hold prescriptions
- resume_prescription succeeds for on_hold prescriptions
- discontinue_prescription rejects already-discontinued prescriptions
- _get_prescription raises PrescriptionNotFoundError
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InvalidPrescriptionStatusError,
    PrescriptionNotFoundError,
)
from app.modules.prescriptions.service import PrescriptionService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def rx_service():
    """Create a PrescriptionService instance for testing."""
    return PrescriptionService()


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test: Hold prescription
# ---------------------------------------------------------------------------
class TestHoldPrescription:
    """Verify hold_prescription enforces active-only rule."""

    @pytest.mark.asyncio
    async def test_rejects_non_active_prescription(self, rx_service, mock_db):
        """hold_prescription raises error if prescription is not active."""
        rx_id = uuid.uuid4()
        mock_rx = SimpleNamespace(
            id=rx_id,
            status=PrescriptionStatus.DISCONTINUED,
            tenant_id=uuid.uuid4(),
        )

        with patch.object(
            rx_service, "_get_prescription", new_callable=AsyncMock, return_value=mock_rx
        ):
            with pytest.raises(InvalidPrescriptionStatusError):
                await rx_service.hold_prescription(
                    db=mock_db,
                    prescription_id=rx_id,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_succeeds_for_active_prescription(self, rx_service, mock_db):
        """hold_prescription sets status to ON_HOLD for active prescriptions."""
        rx_id = uuid.uuid4()
        mock_rx = SimpleNamespace(
            id=rx_id,
            status=PrescriptionStatus.ACTIVE,
            tenant_id=uuid.uuid4(),
        )

        with patch.object(
            rx_service, "_get_prescription", new_callable=AsyncMock, return_value=mock_rx
        ):
            with patch("app.modules.prescriptions.service._audit") as mock_audit:
                mock_audit.log = AsyncMock()
                result = await rx_service.hold_prescription(
                    db=mock_db,
                    prescription_id=rx_id,
                    user_id=uuid.uuid4(),
                )

        assert result.status == PrescriptionStatus.ON_HOLD


# ---------------------------------------------------------------------------
# Test: Resume prescription
# ---------------------------------------------------------------------------
class TestResumePrescription:
    """Verify resume_prescription enforces on_hold-only rule."""

    @pytest.mark.asyncio
    async def test_rejects_non_on_hold_prescription(self, rx_service, mock_db):
        """resume_prescription raises error if not on_hold."""
        rx_id = uuid.uuid4()
        mock_rx = SimpleNamespace(
            id=rx_id,
            status=PrescriptionStatus.ACTIVE,
            tenant_id=uuid.uuid4(),
        )

        with patch.object(
            rx_service, "_get_prescription", new_callable=AsyncMock, return_value=mock_rx
        ):
            with pytest.raises(InvalidPrescriptionStatusError):
                await rx_service.resume_prescription(
                    db=mock_db,
                    prescription_id=rx_id,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_succeeds_for_on_hold_prescription(self, rx_service, mock_db):
        """resume_prescription sets status to ACTIVE for on_hold prescriptions."""
        rx_id = uuid.uuid4()
        mock_rx = SimpleNamespace(
            id=rx_id,
            status=PrescriptionStatus.ON_HOLD,
            tenant_id=uuid.uuid4(),
        )

        with patch.object(
            rx_service, "_get_prescription", new_callable=AsyncMock, return_value=mock_rx
        ):
            with patch("app.modules.prescriptions.service._audit") as mock_audit:
                mock_audit.log = AsyncMock()
                result = await rx_service.resume_prescription(
                    db=mock_db,
                    prescription_id=rx_id,
                    user_id=uuid.uuid4(),
                )

        assert result.status == PrescriptionStatus.ACTIVE


# ---------------------------------------------------------------------------
# Test: Discontinue prescription
# ---------------------------------------------------------------------------
class TestDiscontinuePrescription:
    """Verify discontinue_prescription enforces allowed statuses."""

    @pytest.mark.asyncio
    async def test_rejects_already_discontinued(self, rx_service, mock_db):
        """discontinue_prescription raises error if already discontinued."""
        rx_id = uuid.uuid4()
        mock_rx = SimpleNamespace(
            id=rx_id,
            status=PrescriptionStatus.DISCONTINUED,
            tenant_id=uuid.uuid4(),
        )

        with patch.object(
            rx_service, "_get_prescription", new_callable=AsyncMock, return_value=mock_rx
        ):
            with pytest.raises(InvalidPrescriptionStatusError):
                await rx_service.discontinue_prescription(
                    db=mock_db,
                    prescription_id=rx_id,
                    user_id=uuid.uuid4(),
                    reason="No longer needed",
                )


# ---------------------------------------------------------------------------
# Test: _get_prescription raises for missing
# ---------------------------------------------------------------------------
class TestGetPrescription:
    """Verify _get_prescription raises PrescriptionNotFoundError."""

    @pytest.mark.asyncio
    async def test_raises_for_missing_prescription(self, rx_service, mock_db):
        """_get_prescription raises PrescriptionNotFoundError when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(PrescriptionNotFoundError):
            await rx_service._get_prescription(mock_db, uuid.uuid4())
