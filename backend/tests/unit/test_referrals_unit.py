"""
Unit Tests: Referrals Module (Task 11.6).

Tests cover:
- Referral creation with clinical summary
- Valid status transitions: pending → accepted → scheduled → completed
- Invalid transitions: completed → pending, cancelled → any
- Specialist findings recording via complete_referral

All tests use mocked AsyncSession — no real DB connections.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.referrals.enums import (
    ReferralStatus,
    ReferralUrgency,
    VALID_TRANSITIONS,
)
from app.modules.referrals.exceptions import (
    InvalidStatusTransitionError,
    ReferralNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_referral(**overrides):
    """Create a mock Referral object with sensible defaults."""
    ref = MagicMock()
    ref.id = overrides.get("id", uuid.uuid4())
    ref.tenant_id = overrides.get("tenant_id", uuid.uuid4())
    ref.patient_id = overrides.get("patient_id", uuid.uuid4())
    ref.referring_clinician_id = overrides.get("referring_clinician_id", uuid.uuid4())
    ref.receiving_clinician_id = overrides.get("receiving_clinician_id", None)
    ref.specialty = overrides.get("specialty", "Cardiology")
    ref.urgency = overrides.get("urgency", ReferralUrgency.ROUTINE)
    ref.reason = overrides.get("reason", "Elevated BP")
    ref.status = overrides.get("status", ReferralStatus.PENDING)
    ref.clinical_summary = overrides.get("clinical_summary", None)
    ref.specialist_findings = overrides.get("specialist_findings", None)
    ref.specialist_recommendations = overrides.get("specialist_recommendations", None)
    ref.completed_at = overrides.get("completed_at", None)
    return ref


def _mock_db_returning_referral(ref):
    """Return mock DB that returns the given referral from execute."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = ref
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


class TestReferralCreation:
    """Verify referral creation stores clinical summary."""

    @pytest.mark.asyncio
    async def test_create_referral_stores_clinical_summary(self):
        """Creating a referral with clinical_summary persists it on the model."""
        from app.modules.referrals.service import ReferralService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = ReferralService()
        summary = "Patient presents with chronic hypertension, 3 medications tried."

        with patch("app.modules.referrals.service._audit", MagicMock(log_action=AsyncMock())):
            result = await service.create_referral(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                referring_clinician_id=uuid.uuid4(),
                specialty="Cardiology",
                urgency=ReferralUrgency.URGENT,
                reason="Resistant hypertension",
                clinical_summary=summary,
            )

        # Verify the model was added with clinical_summary
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.clinical_summary == summary
        assert added_obj.status == ReferralStatus.PENDING


class TestValidStatusTransitions:
    """Verify the happy-path transition chain works correctly."""

    @pytest.mark.asyncio
    async def test_pending_to_accepted(self):
        """Transition from PENDING to ACCEPTED succeeds."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.PENDING)
        mock_db = _mock_db_returning_referral(ref)
        service = ReferralService()

        with patch("app.modules.referrals.service._audit", MagicMock(log_action=AsyncMock())):
            await service.update_status(
                db=mock_db, referral_id=ref.id,
                new_status=ReferralStatus.ACCEPTED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.ACCEPTED

    @pytest.mark.asyncio
    async def test_accepted_to_scheduled(self):
        """Transition from ACCEPTED to SCHEDULED succeeds."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.ACCEPTED)
        mock_db = _mock_db_returning_referral(ref)
        service = ReferralService()

        with patch("app.modules.referrals.service._audit", MagicMock(log_action=AsyncMock())):
            await service.update_status(
                db=mock_db, referral_id=ref.id,
                new_status=ReferralStatus.SCHEDULED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.SCHEDULED

    @pytest.mark.asyncio
    async def test_complete_referral_records_findings(self):
        """complete_referral sets specialist_findings and transitions to COMPLETED."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.IN_PROGRESS)
        mock_db = _mock_db_returning_referral(ref)
        service = ReferralService()

        with patch("app.modules.referrals.service._audit", MagicMock(log_action=AsyncMock())):
            await service.complete_referral(
                db=mock_db, referral_id=ref.id,
                specialist_findings="No significant stenosis found.",
                specialist_recommendations="Continue current medication.",
                user_id=uuid.uuid4(),
            )

        assert ref.specialist_findings == "No significant stenosis found."
        assert ref.specialist_recommendations == "Continue current medication."
        assert ref.status == ReferralStatus.COMPLETED


class TestInvalidStatusTransitions:
    """Verify invalid transitions raise InvalidStatusTransitionError."""

    @pytest.mark.asyncio
    async def test_completed_to_pending_raises(self):
        """Transition from COMPLETED to PENDING raises error (terminal state)."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.COMPLETED)
        mock_db = _mock_db_returning_referral(ref)
        service = ReferralService()

        with pytest.raises(InvalidStatusTransitionError):
            await service.update_status(
                db=mock_db, referral_id=ref.id,
                new_status=ReferralStatus.PENDING, user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_cancelled_to_accepted_raises(self):
        """Transition from CANCELLED to ACCEPTED raises error (terminal state)."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.CANCELLED)
        mock_db = _mock_db_returning_referral(ref)
        service = ReferralService()

        with pytest.raises(InvalidStatusTransitionError):
            await service.update_status(
                db=mock_db, referral_id=ref.id,
                new_status=ReferralStatus.ACCEPTED, user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_cancelled_to_scheduled_raises(self):
        """Transition from CANCELLED to SCHEDULED raises error."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.CANCELLED)
        mock_db = _mock_db_returning_referral(ref)
        service = ReferralService()

        with pytest.raises(InvalidStatusTransitionError):
            await service.update_status(
                db=mock_db, referral_id=ref.id,
                new_status=ReferralStatus.SCHEDULED, user_id=uuid.uuid4(),
            )
