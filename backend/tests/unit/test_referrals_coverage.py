"""
Coverage tests: Referrals Module — uncovered service paths, schemas, enums, exceptions.

Targets paths not exercised by test_referrals_unit.py:
  - ReferralService.list_referrals (with/without filters)
  - ReferralService.get_referral (happy path + not-found)
  - ReferralService.complete_referral (from ACCEPTED / SCHEDULED auto-transitions)
  - ReferralService.complete_referral (invalid state guard)
  - ReferralService.update_status — all remaining valid transitions
    (PENDING→DECLINED, PENDING→CANCELLED, ACCEPTED→CANCELLED,
     SCHEDULED→IN_PROGRESS, SCHEDULED→CANCELLED, IN_PROGRESS→COMPLETED)
  - Pydantic schemas
  - Custom exceptions
  - Enum / VALID_TRANSITIONS completeness
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.referrals.enums import (
    VALID_TRANSITIONS,
    ReferralStatus,
    ReferralUrgency,
)
from app.modules.referrals.exceptions import (
    InvalidStatusTransitionError,
    ReferralNotFoundError,
)
from app.modules.referrals.schemas import (
    ReferralCompletion,
    ReferralCreate,
    ReferralListResponse,
    ReferralResponse,
    ReferralStatusUpdate,
)

# ---------------------------------------------------------------------------
# Shared mock audit
# ---------------------------------------------------------------------------
_mock_audit = MagicMock()
_mock_audit.log_action = AsyncMock()


def _make_referral(**kw):
    """Return a mock Referral ORM object with sensible defaults."""
    ref = MagicMock()
    ref.id = kw.get("id", uuid.uuid4())
    ref.tenant_id = kw.get("tenant_id", uuid.uuid4())
    ref.patient_id = kw.get("patient_id", uuid.uuid4())
    ref.referring_clinician_id = kw.get("referring_clinician_id", uuid.uuid4())
    ref.receiving_clinician_id = kw.get("receiving_clinician_id", None)
    ref.specialty = kw.get("specialty", "Cardiology")
    ref.urgency = kw.get("urgency", ReferralUrgency.ROUTINE)
    ref.reason = kw.get("reason", "Cardiac evaluation")
    ref.status = kw.get("status", ReferralStatus.PENDING)
    ref.clinical_summary = kw.get("clinical_summary", None)
    ref.specialist_findings = kw.get("specialist_findings", None)
    ref.specialist_recommendations = kw.get("specialist_recommendations", None)
    ref.completed_at = kw.get("completed_at", None)
    return ref


def _mock_db_returning(ref):
    """Return mock AsyncSession that returns given referral from execute."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = ref
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ===========================================================================
# ReferralService.get_referral — happy path + not found
# ===========================================================================
class TestGetReferral:
    """Verify single-referral fetch and not-found handling."""

    @pytest.mark.asyncio
    async def test_get_referral_returns_ref(self):
        """get_referral returns the Referral ORM object when found."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral()
        db = _mock_db_returning(ref)
        svc = ReferralService()

        result = await svc.get_referral(db=db, referral_id=ref.id)

        assert result is ref

    @pytest.mark.asyncio
    async def test_get_referral_not_found_raises(self):
        """get_referral raises ReferralNotFoundError for unknown UUID."""
        from app.modules.referrals.service import ReferralService

        db = _mock_db_returning(None)
        svc = ReferralService()

        with pytest.raises(ReferralNotFoundError):
            await svc.get_referral(db=db, referral_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_referral_not_found_stores_id(self):
        """ReferralNotFoundError includes the queried UUID in the message."""
        from app.modules.referrals.service import ReferralService

        db = _mock_db_returning(None)
        svc = ReferralService()
        target_id = uuid.uuid4()

        with pytest.raises(ReferralNotFoundError) as exc:
            await svc.get_referral(db=db, referral_id=target_id)

        assert str(target_id) in str(exc.value)


# ===========================================================================
# ReferralService.list_referrals
# ===========================================================================
class TestListReferrals:
    """Verify paginated referral listing with optional filters."""

    @pytest.mark.asyncio
    async def test_list_referrals_no_filters(self):
        """list_referrals returns all referrals for a tenant."""
        from app.modules.referrals.service import ReferralService

        refs = [_make_referral(), _make_referral()]
        db = AsyncMock()

        call_count = [0]
        async def _side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.all.return_value = refs
            else:
                result.scalar_one.return_value = len(refs)
            return result

        db.execute = AsyncMock(side_effect=_side_effect)

        svc = ReferralService()
        items, total = await svc.list_referrals(
            db=db,
            tenant_id=uuid.uuid4(),
        )

        assert len(items) == 2
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_referrals_with_patient_filter(self):
        """list_referrals includes patient_id in query when provided."""
        from app.modules.referrals.service import ReferralService

        db = AsyncMock()
        call_count = [0]
        async def _side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.all.return_value = []
            else:
                result.scalar_one.return_value = 0
            return result

        db.execute = AsyncMock(side_effect=_side_effect)

        svc = ReferralService()
        items, total = await svc.list_referrals(
            db=db,
            tenant_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            limit=10,
            offset=0,
        )

        assert db.execute.called
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_referrals_with_status_filter(self):
        """list_referrals includes status in query when provided."""
        from app.modules.referrals.service import ReferralService

        db = AsyncMock()
        call_count = [0]
        async def _side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.all.return_value = []
            else:
                result.scalar_one.return_value = 0
            return result

        db.execute = AsyncMock(side_effect=_side_effect)

        svc = ReferralService()
        items, total = await svc.list_referrals(
            db=db,
            tenant_id=uuid.uuid4(),
            status=ReferralStatus.PENDING,
        )

        assert db.execute.call_count == 2


# ===========================================================================
# ReferralService.complete_referral — auto-transition paths
# ===========================================================================
class TestCompleteReferralTransitions:
    """Verify complete_referral auto-advances ACCEPTED/SCHEDULED → IN_PROGRESS → COMPLETED."""

    @pytest.mark.asyncio
    async def test_complete_from_accepted_auto_transitions(self):
        """complete_referral from ACCEPTED auto-advances to IN_PROGRESS then COMPLETED."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.ACCEPTED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.complete_referral(
                db=db,
                referral_id=ref.id,
                specialist_findings="No obstruction found.",
                specialist_recommendations="Reduce medication dose.",
                user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.COMPLETED
        assert ref.specialist_findings == "No obstruction found."
        assert ref.completed_at is not None

    @pytest.mark.asyncio
    async def test_complete_from_scheduled_auto_transitions(self):
        """complete_referral from SCHEDULED auto-advances to IN_PROGRESS then COMPLETED."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.SCHEDULED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.complete_referral(
                db=db,
                referral_id=ref.id,
                specialist_findings="Stable condition.",
                specialist_recommendations="Monitor monthly.",
                user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_complete_from_pending_raises(self):
        """complete_referral from PENDING raises InvalidStatusTransitionError."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.PENDING)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with pytest.raises(InvalidStatusTransitionError):
            with patch("app.modules.referrals.service._audit", _mock_audit):
                await svc.complete_referral(
                    db=db,
                    referral_id=ref.id,
                    specialist_findings="Something",
                    specialist_recommendations="Something",
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_complete_from_cancelled_raises(self):
        """complete_referral from CANCELLED raises InvalidStatusTransitionError."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.CANCELLED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with pytest.raises(InvalidStatusTransitionError):
            with patch("app.modules.referrals.service._audit", _mock_audit):
                await svc.complete_referral(
                    db=db,
                    referral_id=ref.id,
                    specialist_findings="x",
                    specialist_recommendations="y",
                    user_id=uuid.uuid4(),
                )


# ===========================================================================
# ReferralService.update_status — remaining valid transitions
# ===========================================================================
class TestAdditionalStatusTransitions:
    """Verify all valid status transitions not covered by existing tests."""

    @pytest.mark.asyncio
    async def test_pending_to_declined(self):
        """PENDING → DECLINED is a valid transition."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.PENDING)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.DECLINED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.DECLINED

    @pytest.mark.asyncio
    async def test_pending_to_cancelled(self):
        """PENDING → CANCELLED is a valid transition."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.PENDING)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.CANCELLED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_accepted_to_cancelled(self):
        """ACCEPTED → CANCELLED is a valid transition."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.ACCEPTED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.CANCELLED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_scheduled_to_in_progress(self):
        """SCHEDULED → IN_PROGRESS is a valid transition."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.SCHEDULED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.IN_PROGRESS, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_scheduled_to_cancelled(self):
        """SCHEDULED → CANCELLED is a valid transition."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.SCHEDULED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.CANCELLED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_in_progress_to_completed(self):
        """IN_PROGRESS → COMPLETED is a valid transition."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.IN_PROGRESS)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with patch("app.modules.referrals.service._audit", _mock_audit):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.COMPLETED, user_id=uuid.uuid4(),
            )

        assert ref.status == ReferralStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_declined_is_terminal(self):
        """DECLINED is terminal — any outbound transition raises error."""
        from app.modules.referrals.service import ReferralService

        ref = _make_referral(status=ReferralStatus.DECLINED)
        db = _mock_db_returning(ref)
        svc = ReferralService()

        with pytest.raises(InvalidStatusTransitionError):
            await svc.update_status(
                db=db, referral_id=ref.id,
                new_status=ReferralStatus.PENDING, user_id=uuid.uuid4(),
            )


# ===========================================================================
# Pydantic Schemas
# ===========================================================================
class TestReferralSchemas:
    """Verify request/response schemas validate correctly."""

    def test_referral_create_valid(self):
        """ReferralCreate accepts a valid payload with required fields."""
        obj = ReferralCreate(
            patient_id=uuid.uuid4(),
            specialty="Neurology",
            urgency=ReferralUrgency.URGENT,
            reason="Persistent migraines unresponsive to treatment",
        )
        assert obj.specialty == "Neurology"
        assert obj.encounter_id is None

    def test_referral_create_with_clinical_summary(self):
        """ReferralCreate stores clinical_summary."""
        obj = ReferralCreate(
            patient_id=uuid.uuid4(),
            specialty="Cardiology",
            urgency=ReferralUrgency.ROUTINE,
            reason="Follow-up",
            clinical_summary="Patient has well-controlled BP on three medications.",
        )
        assert obj.clinical_summary is not None

    def test_referral_status_update_valid(self):
        """ReferralStatusUpdate stores the new status."""
        obj = ReferralStatusUpdate(new_status=ReferralStatus.ACCEPTED)
        assert obj.new_status == ReferralStatus.ACCEPTED

    def test_referral_completion_valid(self):
        """ReferralCompletion stores findings and recommendations."""
        obj = ReferralCompletion(
            specialist_findings="No structural abnormality.",
            specialist_recommendations="Continue current therapy.",
        )
        assert obj.specialist_findings == "No structural abnormality."

    def test_referral_list_response_valid(self):
        """ReferralListResponse holds pagination metadata."""
        obj = ReferralListResponse(items=[], total=0, limit=25, offset=0)
        assert obj.total == 0


# ===========================================================================
# Enum completeness and VALID_TRANSITIONS
# ===========================================================================
class TestReferralEnums:
    """Verify enum values and transition map completeness."""

    def test_referral_urgency_values(self):
        """ReferralUrgency contains all three urgency levels."""
        assert {e.value for e in ReferralUrgency} == {"routine", "urgent", "emergent"}

    def test_referral_status_values(self):
        """ReferralStatus contains all seven lifecycle states."""
        expected = {
            "pending", "accepted", "scheduled", "in_progress",
            "completed", "cancelled", "declined",
        }
        assert {e.value for e in ReferralStatus} == expected

    def test_valid_transitions_covers_all_non_terminal(self):
        """VALID_TRANSITIONS has an entry for every non-terminal status."""
        for status in [
            ReferralStatus.PENDING,
            ReferralStatus.ACCEPTED,
            ReferralStatus.SCHEDULED,
            ReferralStatus.IN_PROGRESS,
        ]:
            assert status in VALID_TRANSITIONS
            assert len(VALID_TRANSITIONS[status]) > 0

    def test_terminal_states_have_empty_transitions(self):
        """Terminal states (COMPLETED, CANCELLED, DECLINED) have empty transition lists."""
        for status in [ReferralStatus.COMPLETED, ReferralStatus.CANCELLED, ReferralStatus.DECLINED]:
            assert VALID_TRANSITIONS[status] == []


# ===========================================================================
# Custom Exceptions
# ===========================================================================
class TestReferralExceptions:
    """Verify exception constructors and PHI-safe messages."""

    def test_referral_not_found_stores_id(self):
        """ReferralNotFoundError stores referral_id attribute."""
        ref_id = str(uuid.uuid4())
        err = ReferralNotFoundError(ref_id)
        assert err.referral_id == ref_id
        assert ref_id in str(err)
        assert isinstance(err, Exception)

    def test_invalid_transition_stores_fields(self):
        """InvalidStatusTransitionError stores referral_id, from_status, to_status."""
        ref_id = str(uuid.uuid4())
        err = InvalidStatusTransitionError(
            ref_id,
            ReferralStatus.COMPLETED,
            ReferralStatus.PENDING,
        )
        assert err.referral_id == ref_id
        assert err.from_status == ReferralStatus.COMPLETED
        assert err.to_status == ReferralStatus.PENDING
        assert isinstance(err, Exception)

    def test_invalid_transition_message_contains_statuses(self):
        """InvalidStatusTransitionError message references both transition states."""
        err = InvalidStatusTransitionError(
            str(uuid.uuid4()),
            ReferralStatus.CANCELLED,
            ReferralStatus.ACCEPTED,
        )
        msg = str(err)
        # Message may render as enum name (e.g. 'ReferralStatus.CANCELLED') or value
        assert "CANCELLED" in msg.upper() or "cancelled" in msg
        assert "ACCEPTED" in msg.upper() or "accepted" in msg
