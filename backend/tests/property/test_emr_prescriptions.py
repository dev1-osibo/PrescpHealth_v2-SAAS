"""
Property Tests: Prescription Module — Interaction Blocks & Refill Guard.

Property 5 from design.md (Contraindicated Interaction Blocks Prescription):
    "If DDI returns severity='Contraindicated' and interaction_acknowledged=False
    → InteractionBlockedError raised. If acknowledged=True → prescription created.
    If severity is Major/Moderate/Minor → prescription created regardless."

Property 6 from design.md (Prescription Refill Guard):
    "Refill succeeds iff refills_remaining > 0 AND status == 'active'.
    After successful refill, refills_remaining decreases by exactly 1.
    Refill with refills_remaining=0 raises NoRefillsRemainingError.
    Refill with status != 'active' raises InvalidPrescriptionStatusError."

Why this matters (Patient Safety):
    - Contraindicated drug interactions can cause serious harm or death
    - The system MUST block dangerous prescriptions unless explicitly acknowledged
    - Refill guards prevent over-dispensing and ensure prescription validity
    - These are critical safety checks that must hold for ALL possible inputs

**Validates: Requirements 2.3, 2.4**
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InteractionBlockedError,
    InvalidPrescriptionStatusError,
    NoRefillsRemainingError,
)

# Import Dispensing model so SQLAlchemy can resolve the Prescription→Dispensing
# relationship mapper when Prescription or Dispensing objects are instantiated.
import app.modules.prescriptions.dispensing_model  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate prescription-related data
# ---------------------------------------------------------------------------

# DDI severity levels
severity_strategy = st.sampled_from([
    "Contraindicated", "Major", "Moderate", "Minor",
])

# Non-contraindicated severities (should never block)
non_contraindicated_severity = st.sampled_from([
    "Major", "Moderate", "Minor",
])

# Refill counts (valid range for prescriptions)
refills_remaining_strategy = st.integers(min_value=0, max_value=12)
positive_refills_strategy = st.integers(min_value=1, max_value=12)

# Non-active statuses (should block refills)
non_active_status_strategy = st.sampled_from([
    PrescriptionStatus.COMPLETED,
    PrescriptionStatus.DISCONTINUED,
    PrescriptionStatus.ON_HOLD,
])


# ---------------------------------------------------------------------------
# Property Tests: Contraindicated Interaction Blocks
# ---------------------------------------------------------------------------
class TestInteractionBlocks:
    """
    Property-based tests proving DDI blocking logic correctness.

    The core invariants:
    1. Contraindicated + not acknowledged → ALWAYS blocked
    2. Contraindicated + acknowledged → ALWAYS allowed
    3. Non-contraindicated → ALWAYS allowed regardless of acknowledgment
    """

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_contraindicated_unacknowledged_blocks(self, data):
        """
        Property: If DDI returns severity='Contraindicated' and
        interaction_acknowledged=False, InteractionBlockedError is raised.

        This is the critical safety gate: dangerous drug combinations
        MUST be blocked unless the prescribing Doctor explicitly acknowledges
        the risk with a documented justification.

        **Validates: Requirements 2.3**
        """
        from app.modules.prescriptions.service import PrescriptionService

        # Generate test data
        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        encounter_id = uuid.uuid4()

        # Drug data with interaction NOT acknowledged
        drug_data = {
            "drug_name": "Test Drug",
            "atc_code": "A10BA02",
            "dosage": "500mg",
            "frequency": "twice daily",
            "route": "oral",
            "refills_allowed": 3,
            "interaction_acknowledged": False,
            "interaction_justification": None,
        }

        # Mock DDI to return Contraindicated interaction
        contraindicated_interaction = [
            {"severity": "Contraindicated", "interaction_type": "ddi",
             "description": "Dangerous combination"}
        ]

        # Mock DB and code catalog
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=contraindicated_interaction,
        ), patch(
            "app.modules.prescriptions.service.PrescriptionService._get_active_medication_codes",
            new_callable=AsyncMock,
            return_value=["C08CA01"],
        ):
            service = PrescriptionService()

            # INVARIANT: Must raise InteractionBlockedError
            with pytest.raises(InteractionBlockedError):
                await service.write_prescription(
                    db=mock_db,
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    user_id=user_id,
                    encounter_id=encounter_id,
                    drug_data=drug_data,
                )

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_contraindicated_acknowledged_allows(self, data):
        """
        Property: If DDI returns severity='Contraindicated' and
        interaction_acknowledged=True, the prescription is created
        (no error raised).

        Doctors may override contraindicated interactions when clinically
        justified (e.g., no alternative exists). The system records the
        acknowledgment and justification for audit purposes.

        **Validates: Requirements 2.3**
        """
        from app.modules.prescriptions.service import PrescriptionService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        encounter_id = uuid.uuid4()

        # Drug data WITH interaction acknowledged
        drug_data = {
            "drug_name": "Test Drug",
            "atc_code": "A10BA02",
            "dosage": "500mg",
            "frequency": "twice daily",
            "route": "oral",
            "refills_allowed": 3,
            "interaction_acknowledged": True,
            "interaction_justification": "No alternative available",
        }

        contraindicated_interaction = [
            {"severity": "Contraindicated", "interaction_type": "ddi",
             "description": "Dangerous combination"}
        ]

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=contraindicated_interaction,
        ), patch(
            "app.modules.prescriptions.service.PrescriptionService._get_active_medication_codes",
            new_callable=AsyncMock,
            return_value=["C08CA01"],
        ), patch(
            "app.modules.prescriptions.service.event_bus.publish",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.prescriptions.service._audit.log",
            new_callable=AsyncMock,
        ):
            service = PrescriptionService()

            # INVARIANT: No exception raised — prescription proceeds
            result = await service.write_prescription(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                user_id=user_id,
                encounter_id=encounter_id,
                drug_data=drug_data,
            )

            # Verify a prescription object was created (added to session)
            assert mock_db.add.called, "Prescription was not added to DB session"

    @given(severity=non_contraindicated_severity, acknowledged=st.booleans())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_non_contraindicated_always_allows(
        self, severity, acknowledged
    ):
        """
        Property: If DDI returns severity of Major/Moderate/Minor,
        the prescription is created regardless of acknowledgment status.

        Only 'Contraindicated' severity triggers the blocking gate.
        Lower severity interactions are informational — they may generate
        warnings but never prevent prescription creation.

        **Validates: Requirements 2.3**
        """
        from app.modules.prescriptions.service import PrescriptionService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        encounter_id = uuid.uuid4()

        drug_data = {
            "drug_name": "Test Drug",
            "atc_code": "A10BA02",
            "dosage": "500mg",
            "frequency": "twice daily",
            "route": "oral",
            "refills_allowed": 3,
            "interaction_acknowledged": acknowledged,
            "interaction_justification": "Noted" if acknowledged else None,
        }

        # Non-contraindicated interaction
        interaction = [
            {"severity": severity, "interaction_type": "ddi",
             "description": f"{severity} interaction detected"}
        ]

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=interaction,
        ), patch(
            "app.modules.prescriptions.service.PrescriptionService._get_active_medication_codes",
            new_callable=AsyncMock,
            return_value=["C08CA01"],
        ), patch(
            "app.modules.prescriptions.service.event_bus.publish",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.prescriptions.service._audit.log",
            new_callable=AsyncMock,
        ):
            service = PrescriptionService()

            # INVARIANT: No exception — non-contraindicated never blocks
            result = await service.write_prescription(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                user_id=user_id,
                encounter_id=encounter_id,
                drug_data=drug_data,
            )

            assert mock_db.add.called, (
                f"Prescription blocked by {severity} interaction — should be allowed"
            )


# ---------------------------------------------------------------------------
# Property Tests: Prescription Refill Guard
# ---------------------------------------------------------------------------
class TestRefillGuard:
    """
    Property-based tests proving refill guard correctness.

    The core invariants:
    1. Refill succeeds iff refills_remaining > 0 AND status == "active"
    2. After successful refill, refills_remaining decreases by exactly 1
    3. refills_remaining=0 → NoRefillsRemainingError
    4. status != "active" → InvalidPrescriptionStatusError
    """

    @given(refills_remaining=positive_refills_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_refill_succeeds_when_active_with_remaining(
        self, refills_remaining
    ):
        """
        Property: Refill succeeds when status='active' AND refills_remaining > 0.
        After success, refills_remaining decreases by exactly 1.

        This is the happy path: a valid prescription with available refills
        should always allow dispensing.

        **Validates: Requirements 2.4**
        """
        from app.modules.prescriptions.service_refill import RefillService

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Create mock prescription with active status and remaining refills
        mock_prescription = MagicMock()
        mock_prescription.id = prescription_id
        mock_prescription.tenant_id = uuid.uuid4()
        mock_prescription.status = PrescriptionStatus.ACTIVE
        mock_prescription.refills_remaining = refills_remaining

        # Mock DB to return our prescription
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
                dispensed_quantity="30 tablets",
            )

        # INVARIANT: refills_remaining decreased by exactly 1
        assert mock_prescription.refills_remaining == refills_remaining - 1, (
            f"Expected refills_remaining={refills_remaining - 1}, "
            f"got {mock_prescription.refills_remaining}"
        )

        # INVARIANT: A dispensing record was created
        assert mock_db.add.called, "Dispensing record was not added to session"

    @given(status=non_active_status_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_refill_blocked_when_not_active(self, status):
        """
        Property: Refill with status != 'active' raises
        InvalidPrescriptionStatusError regardless of refills_remaining.

        Only active prescriptions can be refilled. Completed, discontinued,
        or on-hold prescriptions must not dispense medication.

        **Validates: Requirements 2.4**
        """
        from app.modules.prescriptions.service_refill import RefillService

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Create mock prescription with non-active status but remaining refills
        mock_prescription = MagicMock()
        mock_prescription.id = prescription_id
        mock_prescription.tenant_id = uuid.uuid4()
        mock_prescription.status = status
        mock_prescription.refills_remaining = 5  # Has refills but wrong status

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

        # Verify error contains correct context
        assert exc_info.value.current_status == status
        assert exc_info.value.operation == "refill"

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_refill_blocked_when_zero_remaining(self, data):
        """
        Property: Refill with refills_remaining=0 raises
        NoRefillsRemainingError even when status is 'active'.

        This prevents over-dispensing. The patient must obtain a new
        prescription from their Doctor to continue receiving medication.

        **Validates: Requirements 2.4**
        """
        from app.modules.prescriptions.service_refill import RefillService

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Create mock prescription: active but zero refills
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

        # Verify error includes the prescription_id for debugging
        assert exc_info.value.prescription_id == str(prescription_id)

    @given(
        initial_refills=st.integers(min_value=2, max_value=10),
        num_refills=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_sequential_refills_decrement_correctly(
        self, initial_refills, num_refills
    ):
        """
        Property: After N sequential refills, refills_remaining equals
        initial_refills - N (each refill decrements by exactly 1).

        This ensures the decrement logic is consistent across multiple
        refill operations on the same prescription.

        **Validates: Requirements 2.4**
        """
        from app.modules.prescriptions.service_refill import RefillService

        # Ensure we don't try more refills than available
        num_refills = min(num_refills, initial_refills)

        prescription_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Create mock prescription
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

            # Process N refills sequentially
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
            f"expected {expected} remaining, got {mock_prescription.refills_remaining}"
        )
