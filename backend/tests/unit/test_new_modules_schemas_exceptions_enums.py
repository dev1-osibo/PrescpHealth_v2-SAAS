"""
Unit tests for schemas, exceptions, and enums across new modules.

Coverage targets:
  - risk_engine/exceptions.py      (production)
  - risk_engine/enums.py           (production)
  - drug_interactions/exceptions.py (production)
"""

import pytest


# ===========================================================================
# risk_engine/exceptions.py  (production)
# ===========================================================================
from app.modules.risk_engine.exceptions import (
    RiskEngineError,
    InsufficientDataError,
    MLEngineError,
    ModelVersionNotFoundError,
    DataSufficiencyCheckError,
    ComputationTimeoutError,
)


class TestRiskEngineError:
    def test_stores_code(self):
        err = RiskEngineError(code="test_code", message="Test message")
        assert err.code == "test_code"

    def test_stores_message(self):
        err = RiskEngineError(code="test_code", message="Test message")
        assert err.message == "Test message"

    def test_default_empty_context(self):
        err = RiskEngineError(code="c", message="m")
        assert err.context == {}

    def test_stores_context(self):
        ctx = {"patient_id": "synth-001"}
        err = RiskEngineError(code="c", message="m", context=ctx)
        assert err.context == ctx

    def test_inherits_from_exception(self):
        assert isinstance(RiskEngineError(code="c", message="m"), Exception)

    def test_str_is_message(self):
        err = RiskEngineError(code="c", message="my error")
        assert str(err) == "my error"


class TestInsufficientDataError:
    def test_code(self):
        err = InsufficientDataError("synth-001", "no measurements")
        assert err.code == "insufficient_data"

    def test_context_patient_id(self):
        err = InsufficientDataError("synth-001", "stale data")
        assert err.context["patient_id"] == "synth-001"

    def test_context_reason(self):
        err = InsufficientDataError("synth-001", "stale data")
        assert err.context["reason"] == "stale data"

    def test_inherits_from_risk_engine_error(self):
        assert isinstance(InsufficientDataError("s", "r"), RiskEngineError)


class TestMLEngineError:
    def test_code(self):
        assert MLEngineError("v1.0.0", "OOM").code == "ml_engine_error"

    def test_context_model_version(self):
        assert MLEngineError("v1.2.3", "timeout").context["model_version"] == "v1.2.3"

    def test_context_error_detail(self):
        assert MLEngineError("v1.2.3", "inference failed").context["error_detail"] == "inference failed"


class TestModelVersionNotFoundError:
    def test_code(self):
        assert ModelVersionNotFoundError("stroke", "9.9.9").code == "model_version_not_found"

    def test_context_disease(self):
        assert ModelVersionNotFoundError("cvd", "1.0.0").context["disease"] == "cvd"

    def test_context_version(self):
        assert ModelVersionNotFoundError("cvd", "1.0.0").context["version"] == "1.0.0"

    def test_message_includes_disease_and_version(self):
        err = ModelVersionNotFoundError("diabetes", "2.0.0")
        assert "diabetes" in err.message
        assert "2.0.0" in err.message


class TestDataSufficiencyCheckError:
    def test_code(self):
        assert DataSufficiencyCheckError("synth-001", "DB error").code == "data_sufficiency_check_error"

    def test_context(self):
        err = DataSufficiencyCheckError("synth-001", "DB error")
        assert err.context["patient_id"] == "synth-001"
        assert err.context["reason"] == "DB error"


class TestComputationTimeoutError:
    def test_code(self):
        assert ComputationTimeoutError("comp-001", 35.2).code == "computation_timeout"

    def test_context(self):
        err = ComputationTimeoutError("comp-001", 35.2)
        assert err.context["computation_id"] == "comp-001"
        assert err.context["elapsed_seconds"] == 35.2

    def test_message_has_seconds(self):
        assert "35.2" in ComputationTimeoutError("c", 35.2).message


# ===========================================================================
# risk_engine/enums.py  (production)
# ===========================================================================
from app.modules.risk_engine.enums import Disease, RiskStratum


class TestDiseaseEnum:
    def test_stroke(self): assert Disease.STROKE.value == "stroke"
    def test_cvd(self): assert Disease.CARDIOVASCULAR_DISEASE.value == "cvd"
    def test_diabetes(self): assert Disease.TYPE_2_DIABETES.value == "diabetes"
    def test_ckd(self): assert Disease.CHRONIC_KIDNEY_DISEASE.value == "ckd"
    def test_hypertensive_crisis(self): assert Disease.HYPERTENSIVE_CRISIS.value == "hypertensive_crisis"
    def test_copd(self): assert Disease.COPD.value == "copd"
    def test_all_diseases_six_entries(self): assert len(Disease.all_diseases()) == 6
    def test_all_diseases_returns_strings(self): assert all(isinstance(d, str) for d in Disease.all_diseases())
    def test_all_diseases_contains_stroke(self): assert "stroke" in Disease.all_diseases()


class TestRiskStratumEnum:
    def test_low_at_0(self): assert RiskStratum.from_score(0) == RiskStratum.LOW
    def test_low_at_24(self): assert RiskStratum.from_score(24.9) == RiskStratum.LOW
    def test_moderate_at_25(self): assert RiskStratum.from_score(25) == RiskStratum.MODERATE
    def test_moderate_at_49(self): assert RiskStratum.from_score(49.9) == RiskStratum.MODERATE
    def test_high_at_50(self): assert RiskStratum.from_score(50) == RiskStratum.HIGH
    def test_high_at_74(self): assert RiskStratum.from_score(74.9) == RiskStratum.HIGH
    def test_critical_at_75(self): assert RiskStratum.from_score(75) == RiskStratum.CRITICAL
    def test_critical_at_100(self): assert RiskStratum.from_score(100) == RiskStratum.CRITICAL
    def test_raises_below_0(self):
        with pytest.raises(ValueError): RiskStratum.from_score(-1)
    def test_raises_above_100(self):
        with pytest.raises(ValueError): RiskStratum.from_score(101)
    def test_low_value(self): assert RiskStratum.LOW.value == "Low"
    def test_moderate_value(self): assert RiskStratum.MODERATE.value == "Moderate"
    def test_high_value(self): assert RiskStratum.HIGH.value == "High"
    def test_critical_value(self): assert RiskStratum.CRITICAL.value == "Critical"


# ===========================================================================
# drug_interactions/exceptions.py  (production)
# ===========================================================================
from app.modules.drug_interactions.exceptions import (
    DrugInteractionError,
    InteractionCheckFailedError,
    MedicationNotFoundError,
    InteractionNotFoundError,
    InvalidOverrideJustificationError,
    DrugCodeNotFoundError,
)


class TestDrugInteractionProductionExceptions:
    def test_base_stores_message(self):
        assert DrugInteractionError("test msg").message == "test msg"

    def test_base_default_code(self):
        assert DrugInteractionError("msg").error_code == "DRUG_INTERACTION_ERROR"

    def test_base_custom_code(self):
        assert DrugInteractionError("msg", "CUSTOM").error_code == "CUSTOM"

    def test_base_inherits_exception(self):
        assert isinstance(DrugInteractionError("msg"), Exception)

    def test_interaction_check_failed_code(self):
        assert InteractionCheckFailedError("f").error_code == "INTERACTION_CHECK_FAILED"

    def test_medication_not_found_code(self):
        assert MedicationNotFoundError("med-001").error_code == "MEDICATION_NOT_FOUND"

    def test_medication_not_found_message(self):
        assert "med-001" in MedicationNotFoundError("med-001").message

    def test_interaction_not_found_code(self):
        assert InteractionNotFoundError("int-001").error_code == "INTERACTION_NOT_FOUND"

    def test_interaction_not_found_message(self):
        assert "int-001" in InteractionNotFoundError("int-001").message

    def test_invalid_override_default_code(self):
        assert InvalidOverrideJustificationError().error_code == "INVALID_OVERRIDE_JUSTIFICATION"

    def test_invalid_override_custom_msg(self):
        assert InvalidOverrideJustificationError("custom").message == "custom"

    def test_drug_code_not_found_code(self):
        assert DrugCodeNotFoundError("T00001").error_code == "DRUG_CODE_NOT_FOUND"

    def test_drug_code_not_found_message(self):
        assert "T00001" in DrugCodeNotFoundError("T00001").message

    def test_all_inherit_from_base(self):
        excepts = [
            InteractionCheckFailedError("m"), MedicationNotFoundError("m"),
            InteractionNotFoundError("i"), InvalidOverrideJustificationError(),
            DrugCodeNotFoundError("c"),
        ]
        for exc in excepts:
            assert isinstance(exc, DrugInteractionError)
