"""
Unit tests for service classes using async mocks.

Targets:
- drug_interactions/service.py (production, 18% covered → significant coverage gain)
- risk_engine/service.py (production, 32% covered → significant coverage gain)

All external dependencies (DB, audit, engine, celery, events) are mocked.
No real database access. Synthetic data only — no PHI.
"""

import uuid
import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ===========================================================================
# DrugInteractionService tests
# ===========================================================================
class TestDrugInteractionServiceAddMedication:
    """Tests for DrugInteractionService.add_medication"""

    def _make_service(self, ddi_results=None, dhi_results=None):
        """Build a DrugInteractionService with all mocked dependencies."""
        from app.modules.drug_interactions.service import DrugInteractionService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_audit = AsyncMock()
        mock_audit.log_action = AsyncMock()

        mock_engine = AsyncMock()
        mock_engine.check_ddi = AsyncMock(return_value=ddi_results or [])
        mock_engine.check_dhi = AsyncMock(return_value=dhi_results or [])

        # Mock _get_active_medications to return empty list
        svc = DrugInteractionService(mock_db, mock_audit, mock_engine)
        # Patch private helpers to isolate
        svc._get_active_medications = AsyncMock(return_value=[])
        svc._get_patient_conditions = AsyncMock(return_value=[])
        svc._get_patient_factors = AsyncMock(return_value={"age": 65, "egfr": 60})

        return svc, mock_db, mock_audit, mock_engine

    @pytest.mark.asyncio
    async def test_add_medication_returns_dict(self):
        svc, _, _, _ = self._make_service()
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth",
            drug_code="T00001",
            dosage="10mg",
            frequency="once daily",
            route="oral",
            start_date=date(2026, 1, 1),
            prescribed_by=uuid.uuid4(),
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_add_medication_no_interactions_status_safe(self):
        svc, _, _, _ = self._make_service(ddi_results=[], dhi_results=[])
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert result["safety_status"] == "Safe"
        assert result["ddi_count"] == 0
        assert result["dhi_count"] == 0

    @pytest.mark.asyncio
    async def test_add_medication_minor_interaction_status_caution(self):
        ddi = [{
            "interaction_id": str(uuid.uuid4()),
            "drug_a_code": "T00001", "drug_a_name": "TestDrugA",
            "drug_b_code": "T00002", "drug_b_name": "TestDrugB",
            "severity": "Minor", "mechanism": "Test",
            "adverse_outcome": "Test", "recommended_action": "Monitor",
            "evidence_level": "Low",
        }]
        svc, _, _, _ = self._make_service(ddi_results=ddi)
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert result["safety_status"] == "Caution"
        assert result["ddi_count"] == 1

    @pytest.mark.asyncio
    async def test_add_medication_major_ddi_status_action_required(self):
        ddi = [{
            "interaction_id": str(uuid.uuid4()),
            "drug_a_code": "T00001", "drug_a_name": "TestDrugA",
            "drug_b_code": "T00002", "drug_b_name": "TestDrugB",
            "severity": "Major", "mechanism": "Test",
            "adverse_outcome": "Serious", "recommended_action": "Stop",
            "evidence_level": "High",
        }]
        svc, _, _, _ = self._make_service(ddi_results=ddi)
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert result["safety_status"] == "Action Required"
        assert len(result["critical_interactions"]) == 1

    @pytest.mark.asyncio
    async def test_add_medication_contraindicated_action_required(self):
        ddi = [{
            "interaction_id": str(uuid.uuid4()),
            "drug_a_code": "T00001", "drug_a_name": "TestDrugA",
            "drug_b_code": "T00002", "drug_b_name": "TestDrugB",
            "severity": "Contraindicated", "mechanism": "Test",
            "adverse_outcome": "Death risk", "recommended_action": "Avoid",
            "evidence_level": "High",
        }]
        svc, _, _, _ = self._make_service(ddi_results=ddi)
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert result["safety_status"] == "Action Required"

    @pytest.mark.asyncio
    async def test_add_medication_dhi_action_required(self):
        dhi = [{
            "interaction_id": str(uuid.uuid4()),
            "drug_code": "T00001", "drug_name": "TestDrug",
            "health_condition": "Renal failure",
            "severity": "Major", "severity_adjusted": "Major",
            "mechanism": "Nephrotoxicity",
            "adverse_outcome": "Renal failure", "recommended_action": "Avoid",
            "evidence_level": "High", "patient_factor_notes": "eGFR <30",
        }]
        svc, _, _, _ = self._make_service(dhi_results=dhi)
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert result["safety_status"] == "Action Required"
        assert result["dhi_count"] == 1

    @pytest.mark.asyncio
    async def test_add_medication_db_add_called(self):
        svc, mock_db, _, _ = self._make_service()
        await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert mock_db.add.called

    @pytest.mark.asyncio
    async def test_add_medication_audit_called(self):
        svc, _, mock_audit, _ = self._make_service()
        await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert mock_audit.log_action.called

    @pytest.mark.asyncio
    async def test_add_medication_result_has_medication_id(self):
        svc, _, _, _ = self._make_service()
        result = await svc.add_medication(
            patient_id=uuid.uuid4(),
            drug_name="TestDrugSynth", drug_code="T00001",
            dosage="10mg", frequency="once daily", route="oral",
            start_date=date(2026, 1, 1), prescribed_by=uuid.uuid4(),
        )
        assert "medication_id" in result


class TestDrugInteractionServiceGetSafetySummary:
    """Tests for DrugInteractionService.get_safety_summary"""

    def _make_service_with_interactions(self, interactions):
        from app.modules.drug_interactions.service import DrugInteractionService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = interactions
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_audit = AsyncMock()
        mock_engine = AsyncMock()
        svc = DrugInteractionService(mock_db, mock_audit, mock_engine)
        return svc

    @pytest.mark.asyncio
    async def test_no_interactions_safe_status(self):
        svc = self._make_service_with_interactions([])
        result = await svc.get_safety_summary(uuid.uuid4())
        assert result["overall_status"] == "Safe"

    @pytest.mark.asyncio
    async def test_critical_count_zero_with_no_interactions(self):
        svc = self._make_service_with_interactions([])
        result = await svc.get_safety_summary(uuid.uuid4())
        assert result["critical_issue_count"] == 0

    @pytest.mark.asyncio
    async def test_contraindicated_gives_action_required(self):
        mock_interaction = MagicMock()
        mock_interaction.severity = "Contraindicated"
        mock_interaction.interaction_type = "DDI"
        mock_interaction.recommended_action = "Stop immediately"
        mock_interaction.id = uuid.uuid4()
        mock_interaction.is_overridden = False
        svc = self._make_service_with_interactions([mock_interaction])
        result = await svc.get_safety_summary(uuid.uuid4())
        assert result["overall_status"] == "Action Required"
        assert result["critical_issue_count"] == 1

    @pytest.mark.asyncio
    async def test_moderate_gives_caution_status(self):
        mock_interaction = MagicMock()
        mock_interaction.severity = "Moderate"
        mock_interaction.interaction_type = "DDI"
        mock_interaction.recommended_action = "Monitor"
        mock_interaction.id = uuid.uuid4()
        svc = self._make_service_with_interactions([mock_interaction])
        result = await svc.get_safety_summary(uuid.uuid4())
        assert result["overall_status"] == "Caution"
        assert result["moderate_issue_count"] == 1

    @pytest.mark.asyncio
    async def test_recommendations_list_populated(self):
        mock_interaction = MagicMock()
        mock_interaction.severity = "Major"
        mock_interaction.interaction_type = "DDI"
        mock_interaction.recommended_action = "Substitute"
        mock_interaction.id = uuid.uuid4()
        svc = self._make_service_with_interactions([mock_interaction])
        result = await svc.get_safety_summary(uuid.uuid4())
        assert len(result["recommendations"]) > 0


class TestDrugInteractionServiceOverrideInteraction:
    """Tests for DrugInteractionService.override_interaction"""

    def _make_service(self, interaction_mock=None):
        from app.modules.drug_interactions.service import DrugInteractionService

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=interaction_mock)
        mock_db.commit = AsyncMock()

        mock_audit = AsyncMock()
        mock_audit.log_action = AsyncMock()

        mock_engine = AsyncMock()
        svc = DrugInteractionService(mock_db, mock_audit, mock_engine)
        return svc

    @pytest.mark.asyncio
    async def test_short_justification_raises_value_error(self):
        svc = self._make_service()
        with pytest.raises(ValueError, match="at least 20 characters"):
            await svc.override_interaction(
                uuid.uuid4(), uuid.uuid4(), "Too short"
            )

    @pytest.mark.asyncio
    async def test_interaction_not_found_raises(self):
        svc = self._make_service(interaction_mock=None)
        with pytest.raises(ValueError, match="not found"):
            await svc.override_interaction(
                uuid.uuid4(), uuid.uuid4(),
                "This is a sufficient justification for override."
            )

    @pytest.mark.asyncio
    async def test_valid_override_returns_success(self):
        mock_interaction = MagicMock()
        mock_interaction.patient_id = uuid.uuid4()
        mock_interaction.interaction_type = "DDI"
        svc = self._make_service(interaction_mock=mock_interaction)
        result = await svc.override_interaction(
            uuid.uuid4(), uuid.uuid4(),
            "No alternative available; patient closely monitored."
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_override_sets_is_overridden_flag(self):
        mock_interaction = MagicMock()
        mock_interaction.patient_id = uuid.uuid4()
        mock_interaction.interaction_type = "DDI"
        svc = self._make_service(interaction_mock=mock_interaction)
        await svc.override_interaction(
            uuid.uuid4(), uuid.uuid4(),
            "No alternative available; patient closely monitored."
        )
        assert mock_interaction.is_overridden is True

    @pytest.mark.asyncio
    async def test_override_records_justification(self):
        mock_interaction = MagicMock()
        mock_interaction.patient_id = uuid.uuid4()
        mock_interaction.interaction_type = "DDI"
        svc = self._make_service(interaction_mock=mock_interaction)
        justification = "Patient has no alternative drug options available for treatment."
        await svc.override_interaction(uuid.uuid4(), uuid.uuid4(), justification)
        assert mock_interaction.override_justification == justification


class TestDrugInteractionServicePrivateHelpers:
    """Tests for private helper methods."""

    @pytest.mark.asyncio
    async def test_get_patient_conditions_returns_empty_list(self):
        from app.modules.drug_interactions.service import DrugInteractionService
        svc = DrugInteractionService(AsyncMock(), AsyncMock(), AsyncMock())
        conditions = await svc._get_patient_conditions(uuid.uuid4())
        assert conditions == []

    @pytest.mark.asyncio
    async def test_get_patient_factors_returns_defaults(self):
        from app.modules.drug_interactions.service import DrugInteractionService
        svc = DrugInteractionService(AsyncMock(), AsyncMock(), AsyncMock())
        factors = await svc._get_patient_factors(uuid.uuid4())
        assert "age" in factors
        assert "egfr" in factors

    @pytest.mark.asyncio
    async def test_get_active_medications_calls_db_execute(self):
        from app.modules.drug_interactions.service import DrugInteractionService
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc = DrugInteractionService(mock_db, AsyncMock(), AsyncMock())
        result = await svc._get_active_medications(uuid.uuid4())
        assert result == []
        assert mock_db.execute.called


# ===========================================================================
# RiskService tests
# ===========================================================================
class TestRiskServiceGetLatestScores:
    """Tests for RiskService.get_latest_scores"""

    def _make_risk_service(self, scalar_returns=None):
        """Build a RiskService with mocked DB that returns given scalars."""
        from app.modules.risk_engine.service import RiskService

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(side_effect=scalar_returns or (lambda stmt: None))

        svc = RiskService(
            db_session=mock_db,
            measurement_service=AsyncMock(),
            audit_service=AsyncMock(),
            request_id="test-request-001",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        )
        return svc, mock_db

    @pytest.mark.asyncio
    async def test_get_latest_scores_all_none_when_no_data(self):
        # mock db.scalar always returns None (no scores)
        from app.modules.risk_engine.service import RiskService

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)

        svc = RiskService(
            db_session=mock_db,
            measurement_service=AsyncMock(),
            audit_service=AsyncMock(),
            request_id="test-request-001",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        )
        result = await svc.get_latest_scores(uuid.uuid4())
        assert isinstance(result, dict)
        # All 6 diseases should be present
        assert len(result) == 6
        # All should be None (no data)
        assert all(v is None for v in result.values())

    @pytest.mark.asyncio
    async def test_get_latest_scores_returns_six_disease_keys(self):
        from app.modules.risk_engine.service import RiskService
        from app.modules.risk_engine.enums import Disease

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)

        svc = RiskService(
            db_session=mock_db,
            measurement_service=AsyncMock(),
            audit_service=AsyncMock(),
            request_id="req-001",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        )
        result = await svc.get_latest_scores(uuid.uuid4())
        expected_diseases = Disease.all_diseases()
        for disease in expected_diseases:
            assert disease in result

    @pytest.mark.asyncio
    async def test_get_latest_scores_with_data_returns_score_dict(self):
        from app.modules.risk_engine.service import RiskService

        mock_score = MagicMock()
        mock_score.score = Decimal("42.00")
        mock_score.stratum = "Moderate"
        mock_score.confidence_lower = Decimal("38.00")
        mock_score.confidence_upper = Decimal("46.00")
        mock_score.computed_at = datetime(2026, 5, 31, tzinfo=timezone.utc)
        mock_score.id = uuid.uuid4()

        # First call: return the score; subsequent calls (for SHAP): return None
        call_count = [0]
        async def side_effect(stmt):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_score  # First disease: stroke has a score
            return None  # Remaining diseases + SHAP queries

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(side_effect=side_effect)

        svc = RiskService(
            db_session=mock_db,
            measurement_service=AsyncMock(),
            audit_service=AsyncMock(),
            request_id="req-001",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        )
        result = await svc.get_latest_scores(uuid.uuid4())
        # First disease (stroke) should have data
        stroke_data = result.get("stroke")
        assert stroke_data is not None
        assert stroke_data["score"] == 42.0
        assert stroke_data["stratum"] == "Moderate"


class TestRiskServiceGetScoreHistory:
    """Tests for RiskService.get_score_history"""

    def _make_service(self, rows=None):
        from app.modules.risk_engine.service import RiskService

        mock_scalars_result = MagicMock()
        mock_scalars_result.all.return_value = rows or []

        mock_db = AsyncMock()
        mock_db.scalars = AsyncMock(return_value=mock_scalars_result)

        return RiskService(
            db_session=mock_db,
            measurement_service=AsyncMock(),
            audit_service=AsyncMock(),
            request_id="req-001",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        )

    @pytest.mark.asyncio
    async def test_invalid_disease_raises_value_error(self):
        svc = self._make_service()
        with pytest.raises(ValueError, match="Unknown disease"):
            await svc.get_score_history(uuid.uuid4(), "not_a_disease")

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list(self):
        svc = self._make_service(rows=[])
        result = await svc.get_score_history(uuid.uuid4(), "stroke")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self):
        mock_row = MagicMock()
        mock_row.score = Decimal("55.0")
        mock_row.stratum = "High"
        mock_row.confidence_lower = Decimal("50.0")
        mock_row.confidence_upper = Decimal("60.0")
        mock_row.computed_at = datetime(2026, 5, 31, tzinfo=timezone.utc)
        svc = self._make_service(rows=[mock_row])
        result = await svc.get_score_history(uuid.uuid4(), "stroke")
        assert len(result) == 1
        assert result[0]["score"] == 55.0
        assert result[0]["stratum"] == "High"

    @pytest.mark.asyncio
    async def test_limit_capped_at_500(self):
        svc = self._make_service()
        # Calling with limit=1000 should not raise — it caps at 500
        result = await svc.get_score_history(uuid.uuid4(), "cvd", limit=1000)
        assert result == []

    @pytest.mark.asyncio
    async def test_all_valid_diseases_accepted(self):
        from app.modules.risk_engine.enums import Disease
        svc = self._make_service()
        for disease in Disease.all_diseases():
            result = await svc.get_score_history(uuid.uuid4(), disease)
            assert isinstance(result, list)


class TestRiskServiceTriggerComputation:
    """Tests for RiskService.trigger_computation"""

    @pytest.mark.asyncio
    async def test_trigger_computation_returns_task_id(self):
        from app.modules.risk_engine.service import RiskService

        mock_audit = AsyncMock()
        mock_audit.log_audit = AsyncMock()

        mock_task_result = MagicMock()
        mock_task_result.id = "task-synth-001"

        with patch("app.modules.risk_engine.service.compute_risk_scores_task") as mock_task:
            mock_task.delay.return_value = mock_task_result

            svc = RiskService(
                db_session=AsyncMock(),
                measurement_service=AsyncMock(),
                audit_service=mock_audit,
                request_id="req-001",
                tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
            )
            task_id = await svc.trigger_computation(uuid.uuid4())
            assert task_id == "task-synth-001"

    @pytest.mark.asyncio
    async def test_trigger_computation_calls_audit(self):
        from app.modules.risk_engine.service import RiskService

        mock_audit = AsyncMock()
        mock_audit.log_audit = AsyncMock()

        mock_task_result = MagicMock()
        mock_task_result.id = "task-synth-002"

        with patch("app.modules.risk_engine.service.compute_risk_scores_task") as mock_task:
            mock_task.delay.return_value = mock_task_result

            svc = RiskService(
                db_session=AsyncMock(),
                measurement_service=AsyncMock(),
                audit_service=mock_audit,
                request_id="req-001",
                tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
            )
            await svc.trigger_computation(uuid.uuid4())
            assert mock_audit.log_audit.called
