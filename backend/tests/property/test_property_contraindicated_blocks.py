"""
Property Test: Contraindicated Interaction Blocks Prescription (Property 5).

Invariant:
    If the DDI engine returns severity='Contraindicated' and
    interaction_acknowledged=False → InteractionBlockedError raised.
    If acknowledged=True with justification → prescription succeeds.
    Non-contraindicated severities (Major/Moderate/Minor) never block.

Why this matters (Patient Safety):
    Contraindicated drug combinations can cause serious adverse events
    including organ failure or death. The system MUST block these
    prescriptions unless a Doctor explicitly acknowledges the risk
    with documented clinical justification (e.g., "no alternative exists").

Tested service: app.modules.prescriptions.service.PrescriptionService
Method: write_prescription(db, tenant_id, patient_id, user_id,
    encounter_id, drug_data)

**Validates: Requirement 2.3 — Contraindicated interaction blocking**
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.prescriptions.exceptions import InteractionBlockedError

# Import models so SQLAlchemy mappers resolve correctly
import app.modules.prescriptions.dispensing_model  # noqa: F401
import app.modules.prescriptions.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate DDI-related test data
# ---------------------------------------------------------------------------

# Non-contraindicated severities that should NEVER block
non_contraindicated_severity = st.sampled_from([
    "Major", "Moderate", "Minor",
])

# Valid ATC codes (drug classification codes)
atc_code_strategy = st.from_regex(r"[A-Z]\d{2}[A-Z]{2}\d{2}", fullmatch=True)

# Clinical justification text (synthetic, no PHI)
justification_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
    min_size=10,
    max_size=100,
)


# ---------------------------------------------------------------------------
# Property Tests: Contraindicated Interaction Blocks
# ---------------------------------------------------------------------------
class TestContraindicatedBlocks:
    """
    Property-based tests proving DDI blocking logic correctness.

    Core invariants:
    1. Contraindicated + not acknowledged → ALWAYS blocked
    2. Contraindicated + acknowledged with justification → ALWAYS allowed
    3. Non-contraindicated severity → ALWAYS allowed
    """

    @given(atc_code=atc_code_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_contraindicated_no_justification_blocks(
        self, atc_code
    ):
        """
        Property: Contraindicated DDI + no acknowledgment → raises
        InteractionBlockedError for ANY drug combination.

        The system cannot allow a dangerous prescription through without
        explicit Doctor acknowledgment. This is the critical safety gate.
        """
        from app.modules.prescriptions.service import PrescriptionService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        encounter_id = uuid.uuid4()

        # Drug data WITHOUT acknowledgment
        drug_data = {
            "drug_name": "Test Drug Alpha",
            "atc_code": atc_code,
            "dosage": "100mg",
            "frequency": "once daily",
            "route": "oral",
            "refills_allowed": 2,
            "interaction_acknowledged": False,
            "interaction_justification": None,
        }

        # DDI engine returns Contraindicated
        contraindicated_result = [
            {
                "severity": "Contraindicated",
                "interaction_type": "ddi",
                "description": "Dangerous combination detected",
            }
        ]

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=contraindicated_result,
        ), patch(
            "app.modules.prescriptions.service.PrescriptionService"
            "._get_active_medication_codes",
            new_callable=AsyncMock,
            return_value=["C08CA01"],
        ):
            service = PrescriptionService()

            # INVARIANT: Must raise InteractionBlockedError
            with pytest.raises(InteractionBlockedError) as exc_info:
                await service.write_prescription(
                    db=mock_db,
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    user_id=user_id,
                    encounter_id=encounter_id,
                    drug_data=drug_data,
                )

            # Verify the error carries interaction details
            assert len(exc_info.value.interaction_details) > 0

    @given(
        atc_code=atc_code_strategy,
        justification=justification_strategy,
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_contraindicated_with_justification_succeeds(
        self, atc_code, justification
    ):
        """
        Property: Contraindicated DDI + acknowledged=True + justification
        → prescription is created successfully.

        Doctors may override contraindicated interactions when clinically
        necessary. The acknowledgment and justification are recorded for
        audit trail compliance.
        """
        from app.modules.prescriptions.service import PrescriptionService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        encounter_id = uuid.uuid4()

        # Drug data WITH acknowledgment and justification
        drug_data = {
            "drug_name": "Test Drug Beta",
            "atc_code": atc_code,
            "dosage": "250mg",
            "frequency": "twice daily",
            "route": "oral",
            "refills_allowed": 1,
            "interaction_acknowledged": True,
            "interaction_justification": justification,
        }

        contraindicated_result = [
            {
                "severity": "Contraindicated",
                "interaction_type": "ddi",
                "description": "Dangerous combination detected",
            }
        ]

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=contraindicated_result,
        ), patch(
            "app.modules.prescriptions.service.PrescriptionService"
            "._get_active_medication_codes",
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

            # INVARIANT: No exception — prescription proceeds
            result = await service.write_prescription(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                user_id=user_id,
                encounter_id=encounter_id,
                drug_data=drug_data,
            )

            # Verify prescription was added to DB session
            assert mock_db.add.called, (
                "Prescription not created despite acknowledgment"
            )

    @given(
        severity=non_contraindicated_severity,
        acknowledged=st.booleans(),
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_non_contraindicated_never_blocks(
        self, severity, acknowledged
    ):
        """
        Property: DDI with severity Major/Moderate/Minor NEVER blocks
        prescription creation, regardless of acknowledgment status.

        Only 'Contraindicated' triggers the blocking gate. Lower severity
        interactions produce informational warnings but the prescription
        proceeds without requiring explicit override.
        """
        from app.modules.prescriptions.service import PrescriptionService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        user_id = uuid.uuid4()
        encounter_id = uuid.uuid4()

        drug_data = {
            "drug_name": "Test Drug Gamma",
            "atc_code": "A10BA02",
            "dosage": "500mg",
            "frequency": "once daily",
            "route": "oral",
            "refills_allowed": 3,
            "interaction_acknowledged": acknowledged,
            "interaction_justification": "Noted" if acknowledged else None,
        }

        # Non-contraindicated interaction
        interaction_result = [
            {
                "severity": severity,
                "interaction_type": "ddi",
                "description": f"{severity} interaction noted",
            }
        ]

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=interaction_result,
        ), patch(
            "app.modules.prescriptions.service.PrescriptionService"
            "._get_active_medication_codes",
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
                f"{severity} interaction blocked prescription — should allow"
            )
