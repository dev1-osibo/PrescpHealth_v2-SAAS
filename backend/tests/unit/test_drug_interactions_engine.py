"""
Unit tests for drug_interactions/engine.py — InteractionEngine.

Tests:
- _adjust_severity_for_patient_factors (pure Python method, no DB)
- check_ddi (mocked DB — returns empty and non-empty results)
- check_dhi (mocked DB — returns empty and non-empty results)
- get_critical_interactions (mocked DB)

All drug codes, drug names, and conditions are synthetic — no real PHI.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from unittest.mock import AsyncMock


class MockDBRecord:
    """Fake DrugInteractionsDB row from a mocked DB query."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def make_mock_db(rows=None):
    """Create a mock async SQLAlchemy session that returns given rows."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows or []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


@pytest.fixture
def engine():
    """Return an InteractionEngine with a mock DB session."""
    from app.modules.drug_interactions.engine import InteractionEngine
    mock_db = make_mock_db()
    return InteractionEngine(mock_db)


# ===========================================================================
# _adjust_severity_for_patient_factors — pure Python, fully testable
# ===========================================================================
class TestAdjustSeverityForPatientFactors:
    """Tests for the pure-Python severity adjustment logic."""

    def test_no_factors_returns_base_severity(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Minor", {}, "hypertension"
        )
        assert severity == "Minor"

    def test_no_factors_note_says_no_adjustments(self, engine):
        _, notes = engine._adjust_severity_for_patient_factors(
            "Minor", {}, "hypertension"
        )
        assert "No patient factor adjustments" in notes

    def test_metformin_condition_egfr_below_30_upgrades_to_contraindicated(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {"egfr": 25}, "metformin + diabetes"
        )
        assert severity == "Contraindicated"
        assert "eGFR <30" in notes

    def test_metformin_condition_egfr_below_45_upgrades_to_major(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {"egfr": 40}, "metformin + diabetes"
        )
        assert severity == "Major"
        assert "eGFR <45" in notes

    def test_metformin_condition_egfr_above_45_no_upgrade(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {"egfr": 60}, "metformin + diabetes"
        )
        # No renal upgrade applied
        assert severity == "Moderate"

    def test_nsaid_age_above_65_upgrades_moderate_to_major(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {"age": 70}, "nsaid + hypertension"
        )
        assert severity == "Major"
        assert "GI bleed risk" in notes

    def test_nsaid_age_below_65_no_upgrade(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {"age": 55}, "nsaid + hypertension"
        )
        assert severity == "Moderate"

    def test_nsaid_minor_severity_not_changed_by_age(self, engine):
        # Only Moderate → Major upgrade for NSAIDs+age
        severity, _ = engine._adjust_severity_for_patient_factors(
            "Minor", {"age": 70}, "nsaid + hypertension"
        )
        # Minor stays Minor (upgrade only applies to Moderate)
        assert severity == "Minor"

    def test_ace_ckd_egfr_below_30_upgrades_to_major(self, engine):
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {"egfr": 25}, "ace inhibitor + ckd"
        )
        assert severity == "Major"
        assert "hyperkalemia" in notes

    def test_ace_ckd_egfr_above_30_no_upgrade(self, engine):
        severity, _ = engine._adjust_severity_for_patient_factors(
            "Moderate", {"egfr": 45}, "ace inhibitor + ckd"
        )
        assert severity == "Moderate"

    def test_multiple_notes_joined_with_semicolon(self, engine):
        # Both metformin + nsaid conditions match
        severity, notes = engine._adjust_severity_for_patient_factors(
            "Minor", {"egfr": 25, "age": 70}, "metformin + diabetes + nsaid + hypertension"
        )
        assert ";" in notes or "eGFR <30" in notes

    def test_default_age_used_when_not_provided(self, engine):
        """Default age=60 — NSAIDs should NOT trigger at 60 (threshold is 65)."""
        _, notes = engine._adjust_severity_for_patient_factors(
            "Moderate", {}, "nsaid + hypertension"
        )
        # age defaults to 60 which is <65, so no GI bleed note
        assert "GI bleed" not in notes

    def test_empty_patient_factors_returns_string_notes(self, engine):
        _, notes = engine._adjust_severity_for_patient_factors(
            "Major", {}, "generic condition"
        )
        assert isinstance(notes, str)


# ===========================================================================
# check_ddi (mocked DB)
# ===========================================================================
class TestCheckDDI:
    @pytest.mark.asyncio
    async def test_no_active_meds_returns_empty(self, engine):
        result = await engine.check_ddi("T00001", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_for_one_med(self, engine):
        result = await engine.check_ddi("T00001", ["T00002"])
        assert result == []

    @pytest.mark.asyncio
    async def test_db_match_returns_interaction_dict(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        import uuid
        row = MockDBRecord(
            id=uuid.uuid4(),
            drug_a_code="T00001", drug_a_name="TestDrugA",
            drug_b_code="T00002", drug_b_name="TestDrugB",
            severity="Major", mechanism="Test mechanism",
            adverse_outcome="Test outcome", recommended_action="Monitor",
            evidence_level="High",
        )
        mock_db = make_mock_db(rows=[row])
        eng = InteractionEngine(mock_db)
        result = await eng.check_ddi("T00001", ["T00002"])
        assert len(result) == 1
        assert result[0]["drug_a_code"] == "T00001"
        assert result[0]["severity"] == "Major"

    @pytest.mark.asyncio
    async def test_multiple_active_meds_queries_each(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        call_count = 0
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()

        async def execute_counting(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_result

        mock_db.execute = execute_counting
        eng = InteractionEngine(mock_db)
        await eng.check_ddi("T00001", ["T00002", "T00003", "T00004"])
        # Should query 3 times (one per active med)
        assert call_count == 3


# ===========================================================================
# check_dhi (mocked DB)
# ===========================================================================
class TestCheckDHI:
    @pytest.mark.asyncio
    async def test_no_conditions_returns_empty(self, engine):
        result = await engine.check_dhi("T00001", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, engine):
        result = await engine.check_dhi("T00001", ["CKD stage 4"])
        assert result == []

    @pytest.mark.asyncio
    async def test_db_match_returns_dhi_dict(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        import uuid
        row = MockDBRecord(
            id=uuid.uuid4(),
            drug_a_code="T00001", drug_a_name="TestDrugA",
            health_condition="CKD stage 4",
            severity="Major", mechanism="Test mechanism",
            adverse_outcome="Test outcome", recommended_action="Avoid",
            evidence_level="High",
        )
        mock_db = make_mock_db(rows=[row])
        eng = InteractionEngine(mock_db)
        result = await eng.check_dhi("T00001", ["CKD stage 4"])
        assert len(result) == 1
        assert result[0]["health_condition"] == "CKD stage 4"
        assert "severity" in result[0]
        assert "severity_adjusted" in result[0]

    @pytest.mark.asyncio
    async def test_patient_factors_applied_to_result(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        import uuid
        row = MockDBRecord(
            id=uuid.uuid4(),
            drug_a_code="T00001", drug_a_name="MetforminSynth",
            health_condition="metformin + diabetes",
            severity="Moderate", mechanism="Lactic acid",
            adverse_outcome="Lactic acidosis", recommended_action="Check eGFR",
            evidence_level="High",
        )
        mock_db = make_mock_db(rows=[row])
        eng = InteractionEngine(mock_db)
        result = await eng.check_dhi(
            "T00001", ["metformin + diabetes"],
            patient_factors={"egfr": 25}
        )
        assert len(result) == 1
        # eGFR <30 should upgrade severity_adjusted to Contraindicated
        assert result[0]["severity_adjusted"] == "Contraindicated"

    @pytest.mark.asyncio
    async def test_multiple_conditions_each_queried(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        call_count = 0
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()

        async def execute_counting(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_result

        mock_db.execute = execute_counting
        eng = InteractionEngine(mock_db)
        await eng.check_dhi("T00001", ["CKD", "Hepatic impairment", "Heart failure"])
        assert call_count == 3


# ===========================================================================
# get_critical_interactions (mocked DB)
# ===========================================================================
class TestGetCriticalInteractions:
    @pytest.mark.asyncio
    async def test_empty_meds_and_conditions_returns_empty(self, engine):
        result = await engine.get_critical_interactions([], [])
        assert result == []

    @pytest.mark.asyncio
    async def test_single_med_no_conditions_returns_empty(self, engine):
        result = await engine.get_critical_interactions(["T00001"], [])
        assert result == []

    @pytest.mark.asyncio
    async def test_one_ddi_pair_found(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        import uuid
        row = MockDBRecord(
            id=uuid.uuid4(),
            drug_a_code="T00001", drug_b_code="T00002",
            severity="Major",
        )
        mock_db = make_mock_db(rows=[row])
        eng = InteractionEngine(mock_db)
        result = await eng.get_critical_interactions(["T00001", "T00002"], [])
        assert len(result) == 1
        assert result[0]["type"] == "DDI"

    @pytest.mark.asyncio
    async def test_dhi_match_appended(self):
        from app.modules.drug_interactions.engine import InteractionEngine
        import uuid
        row = MockDBRecord(
            id=uuid.uuid4(),
            drug_a_code="T00001", health_condition="CKD",
            severity="Contraindicated",
        )
        mock_db = make_mock_db(rows=[row])
        eng = InteractionEngine(mock_db)
        result = await eng.get_critical_interactions(["T00001"], ["CKD"])
        assert any(r["type"] == "DHI" for r in result)

    @pytest.mark.asyncio
    async def test_three_meds_check_all_pairs(self):
        """Three meds should check C(3,2)=3 DDI pairs."""
        from app.modules.drug_interactions.engine import InteractionEngine
        call_count = 0
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()

        async def execute_counting(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_result

        mock_db.execute = execute_counting
        eng = InteractionEngine(mock_db)
        await eng.get_critical_interactions(["T00001", "T00002", "T00003"], [])
        # 3 DDI pairs checked
        assert call_count == 3
