"""
Property Test: Prescription Refill Guard (Property 6).

Invariant:
    Refill succeeds iff refills_remaining > 0 AND status == 'active'.
    After a successful refill, refills_remaining decreases by exactly 1.
    Refill with refills_remaining=0 → NoRefillsRemainingError.
    Refill with status != 'active' → InvalidPrescriptionStatusError.

Why this matters (Patient Safety):
    The refill guard prevents over-dispensing medication and ensures
    only valid, active prescriptions can be refilled. Without this:
    - Patients could receive unlimited refills beyond what was prescribed
    - Discontinued or expired prescriptions could be improperly dispensed
    - Controlled substance tracking would be compromised

Tested service: app.modules.prescriptions.service_refill.RefillService
Method: process_refill(db, prescription_id, user_id, dispensed_quantity)

**Validates: Requirement 2.4 — Prescription refill guard**
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InvalidPrescriptionStatusError,
    NoRefillsRemainingError,
)

# Import models so SQLAlchemy mappers resolve correctly
import app.modules.prescriptions.dispensing_model  # noqa: F401
import app.modules.prescriptions.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate refill-related test data
# ---------------------------------------------------------------------------

# Positive refill counts (valid for successful refill)
positive_refills_strategy = st.integers(min_value=1, max_value=12)

# Non-active statuses (should always block refills)
non_active_status_strategy = st.sampled_from([
    PrescriptionStatus.COMPLETED,
    PrescriptionStatus.DISCONTINUED,
    PrescriptionStatus.ON_HOLD,
])

# Dispensed quantity strings (synthetic pharmacy data)
dispensed_quantity_strategy = st.sampled_from([
    "30 tablets", "60 capsules", "90 tablets", "14 tablets",
    "28 tablets", "7 tablets", "120 mL", "240 mL",
])


# ---------------------------------------------------------------------------
# Property Tests: Refill Guard
# ---------------------------------------------------------------------------
class TestRefillGuard:
    """
    Property-based tests proving refill guard correctness.

    Core invariants:
    1. Active + refills_remaining > 0 → refill succeeds, decrements by 1
    2. refills_remaining == 0 → NoRefillsRemainingError
    3. status != active → InvalidPrescriptionStatusError
    """

    @given(
        refills_remaining=positive_refills_strategy,
        dispensed_quantity=dispensed_quantity_strategy,
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_refill_succeeds_active_with_remaining(
        self, refills_remaining, dispensed_quantity
    ):
        """
        Property: Refill succeeds when status='active' AND
        refills_remaining > 0. After success, refills_remaining
        decreases by exactly 1.

        This is the happy path — a valid prescription with available
        refills should always allow dispensing regardless of the
        specific refill count or quantity dispensed.
        """
        from app.modules.prescriptions.service_refill import RefillService

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()
        original_remaining = refills_remaining

        # Mock prescription: active with remaining refills
        mock_prescription = MagicMock()
        mock_prescription.id = prescription_id
        mock_prescription.tenant_id = uuid.uuid4()
        mock_prescription.status = PrescriptionStatus.ACTIVE
        mock_prescription.refills_remaining = refills_remaining

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_prescription
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service_refill._audit.log",
            new_callable=AsyncMock,
        ):
            service = RefillService()
            dispensing = await service.process_refill(
                db=mock_db,
                prescription_id=prescription_id,
                user_id=user_id,
                dispensed_quantity=dispensed_quantity,
            )

        # INVARIANT: refills_remaining decreased by exactly 1
        assert mock_prescription.refills_remaining == original_remaining - 1, (
            f"Expected {original_remaining - 1} remaining, "
            f"got {mock_prescription.refills_remaining}"
        )

        # INVARIANT: A dispensing record was created and added to session
        assert mock_db.add.called, "Dispensing record not added to DB"

    @given(status=non_active_status_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_refill_rejected_non_active_status(self, status):
        """
        Property: Refill with status != 'active' raises
        InvalidPrescriptionStatusError regardless of refills_remaining.

        Completed, discontinued, and on-hold prescriptions must never
        dispense medication. The status guard takes priority over the
        refill count check.
        """
        from app.modules.prescriptions.service_refill import RefillService

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock prescription: non-active but has remaining refills
        mock_prescription = MagicMock()
        mock_prescription.id = prescription_id
        mock_prescription.tenant_id = uuid.uuid4()
        mock_prescription.status = status
        mock_prescription.refills_remaining = 5

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_prescription
        mock_db.execute.return_value = mock_result

        service = RefillService()

        # INVARIANT: Must raise InvalidPrescriptionStatusError
        with pytest.raises(InvalidPrescriptionStatusError) as exc_info:
            await service.process_refill(
                db=mock_db,
                prescription_id=prescription_id,
                user_id=user_id,
                dispensed_quantity="30 tablets",
            )

        # Verify error context is correct
        assert exc_info.value.current_status == status
        assert exc_info.value.operation == "refill"

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_refill_rejected_zero_remaining(self, data):
        """
        Property: Refill with refills_remaining=0 raises
        NoRefillsRemainingError even when status is 'active'.

        This prevents over-dispensing beyond the prescribed refill count.
        The patient must obtain a new prescription from their Doctor.
        """
        from app.modules.prescriptions.service_refill import RefillService

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock prescription: active but zero refills remaining
        mock_prescription = MagicMock()
        mock_prescription.id = prescription_id
        mock_prescription.tenant_id = uuid.uuid4()
        mock_prescription.status = PrescriptionStatus.ACTIVE
        mock_prescription.refills_remaining = 0

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_prescription
        mock_db.execute.return_value = mock_result

        service = RefillService()

        # INVARIANT: Must raise NoRefillsRemainingError
        with pytest.raises(NoRefillsRemainingError) as exc_info:
            await service.process_refill(
                db=mock_db,
                prescription_id=prescription_id,
                user_id=user_id,
                dispensed_quantity="30 tablets",
            )

        # Verify error carries the prescription_id for debugging
        assert exc_info.value.prescription_id == str(prescription_id)

    @given(
        initial_refills=st.integers(min_value=2, max_value=10),
        num_refills=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_sequential_refills_decrement_correctly(
        self, initial_refills, num_refills
    ):
        """
        Property: After N sequential refills, refills_remaining equals
        initial_refills - N. Each refill decrements by exactly 1.

        This ensures the decrement logic is consistent across multiple
        consecutive refill operations on the same prescription object.
        """
        from app.modules.prescriptions.service_refill import RefillService

        # Ensure we don't exceed available refills
        num_refills = min(num_refills, initial_refills)

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        mock_prescription = MagicMock()
        mock_prescription.id = prescription_id
        mock_prescription.tenant_id = uuid.uuid4()
        mock_prescription.status = PrescriptionStatus.ACTIVE
        mock_prescription.refills_remaining = initial_refills

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_prescription
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service_refill._audit.log",
            new_callable=AsyncMock,
        ):
            service = RefillService()

            for _ in range(num_refills):
                await service.process_refill(
                    db=mock_db,
                    prescription_id=prescription_id,
                    user_id=user_id,
                    dispensed_quantity="30 tablets",
                )

        # INVARIANT: refills_remaining = initial - N
        expected = initial_refills - num_refills
        assert mock_prescription.refills_remaining == expected, (
            f"After {num_refills} refills from {initial_refills}, "
            f"expected {expected} remaining, "
            f"got {mock_prescription.refills_remaining}"
        )
