"""
ML Engine Checkpoint Verification Tests (Task 22).

Validates end-to-end pipeline behavior without trained models.
All tests use synthetic patient data — no PHI.

Requirements verified:
    1. Risk engine produces scores for all 6 diseases
    2. All scores are in [0.0, 1.0] range
    3. Forecast engine produces predictions at 3, 6, 12 month horizons
    4. Forecast confidence intervals: lower < point_estimate < upper
    5. Intervention simulation produces directionally correct results
    6. Clinical silence returns SILENT when confidence=0
    7. Cascade network propagates scores (output != input when edges exist)
    8. Meta-learner falls back to clinical standards when data insufficient
    9. Data assessment correctly identifies insufficient data
"""

from __future__ import annotations

import pytest

from ml.risk_engine.cascade_network import CascadeNetwork, DISEASE_NODES
from ml.risk_engine.clinical_silence import ClinicalSilenceEngine
from ml.risk_engine.data_assessment import DataAssessor
from ml.risk_engine.meta_learner import AdaptiveMetaLearner
from ml.risk_engine.orchestrator import RiskOrchestrator
from ml.forecast_engine.orchestrator import ForecastOrchestrator


# =============================================================================
# Synthetic Test Data — no PHI, clearly artificial
# =============================================================================

FULL_PATIENT_FEATURES: dict = {
    "systolic_bp": 160,
    "diastolic_bp": 95,
    "age": 65,
    "bmi": 30,
    "cholesterol_total": 240,
    "smoking_status": 1,
    "heart_rate": 88,
    "atrial_fibrillation": 0,
    "cholesterol_hdl": 38,
    "diabetes_status": 1,
    "fasting_glucose": 130,
    "hba1c": 7.2,
    "family_history_diabetes": 1,
    "waist_circumference": 105,
    "physical_activity": 2,
    "egfr": 55,
    "creatinine": 1.8,
    "albumin_creatinine_ratio": 45,
    "proteinuria": 1,
    "kidney_function": 0.6,
    "medication_adherence": 0.7,
    "fev1": 2.1,
    "fev1_fvc_ratio": 0.65,
    "smoking_pack_years": 20,
    "dyspnea_score": 3,
    "exacerbation_history": 2,
    "weight_kg": 95,
}

SPARSE_PATIENT_FEATURES: dict = {
    "systolic_bp": 140,
}

MEASUREMENTS: list[dict] = [
    {"type": "systolic_bp", "value": 155, "recorded_at": "2026-06-01"},
    {"type": "systolic_bp", "value": 158, "recorded_at": "2026-05-15"},
    {"type": "systolic_bp", "value": 162, "recorded_at": "2026-05-01"},
    {"type": "systolic_bp", "value": 150, "recorded_at": "2026-04-15"},
    {"type": "diastolic_bp", "value": 92, "recorded_at": "2026-06-01"},
    {"type": "heart_rate", "value": 88, "recorded_at": "2026-06-01"},
]


# =============================================================================
# Requirement 1: Risk engine produces scores for all 6 diseases
# =============================================================================


class TestRiskEngineAllDiseases:
    """Verify the risk orchestrator produces scores for every supported disease."""

    def test_risk_engine_returns_all_six_diseases(self) -> None:
        """Risk engine must produce a DiseaseResult for each of the 6 diseases:
        stroke, cvd, diabetes, ckd, hypertensive_crisis, copd."""
        orchestrator = RiskOrchestrator()
        result = orchestrator.predict(FULL_PATIENT_FEATURES, MEASUREMENTS)

        expected_diseases = {"stroke", "cvd", "diabetes", "ckd", "hypertensive_crisis", "copd"}
        actual_diseases = set(result.diseases.keys())

        assert actual_diseases == expected_diseases, (
            f"Expected all 6 diseases, got: {actual_diseases}"
        )

    def test_risk_engine_sparse_patient_still_returns_all_diseases(self) -> None:
        """Even with minimal patient data, the pipeline must return scores
        for all 6 diseases (graceful degradation, not failure)."""
        orchestrator = RiskOrchestrator()
        result = orchestrator.predict(SPARSE_PATIENT_FEATURES, [])

        assert len(result.diseases) == 6, (
            f"Expected 6 diseases even with sparse data, got {len(result.diseases)}"
        )


# =============================================================================
# Requirement 2: All scores in [0.0, 1.0] range
# =============================================================================


class TestRiskScoreRange:
    """Verify all risk scores are valid probabilities in [0.0, 1.0]."""

    def test_full_patient_scores_in_valid_range(self) -> None:
        """All risk scores for a fully-featured patient must be in [0.0, 1.0].
        This validates the sigmoid/clipping in cascade network and meta-learner."""
        orchestrator = RiskOrchestrator()
        result = orchestrator.predict(FULL_PATIENT_FEATURES, MEASUREMENTS)

        for disease, disease_result in result.diseases.items():
            assert 0.0 <= disease_result.risk_score <= 1.0, (
                f"{disease} score {disease_result.risk_score} out of [0,1] range"
            )

    def test_sparse_patient_scores_in_valid_range(self) -> None:
        """Scores must remain in [0.0, 1.0] even with minimal input data.
        Edge case: imputation + cascade on near-empty features."""
        orchestrator = RiskOrchestrator()
        result = orchestrator.predict(SPARSE_PATIENT_FEATURES, [])

        for disease, disease_result in result.diseases.items():
            assert 0.0 <= disease_result.risk_score <= 1.0, (
                f"{disease} score {disease_result.risk_score} out of [0,1] range (sparse)"
            )


# =============================================================================
# Requirement 3: Forecast engine produces predictions at 3, 6, 12 month horizons
# =============================================================================


class TestForecastHorizons:
    """Verify forecast engine returns predictions at all standard horizons."""

    def test_forecast_produces_all_three_horizons(self) -> None:
        """Forecast must return point estimates at 3, 6, and 12 months
        for each requested target metric."""
        engine = ForecastOrchestrator()
        result = engine.predict(
            patient_features=FULL_PATIENT_FEATURES,
            measurements=MEASUREMENTS,
            targets=["systolic_bp"],
        )

        assert "systolic_bp" in result.forecasts, "Target metric missing from forecasts"
        horizons = set(result.forecasts["systolic_bp"].keys())
        assert horizons == {3, 6, 12}, (
            f"Expected horizons {{3, 6, 12}}, got {horizons}"
        )

    def test_forecast_empty_measurements_still_returns_horizons(self) -> None:
        """Even with no historical measurements, the forecast engine
        should return predictions at all horizons (graceful degradation)."""
        engine = ForecastOrchestrator()
        result = engine.predict(
            patient_features=SPARSE_PATIENT_FEATURES,
            measurements=[],
            targets=["systolic_bp"],
        )

        horizons = set(result.forecasts.get("systolic_bp", {}).keys())
        assert horizons == {3, 6, 12}, (
            f"Expected all 3 horizons even with no data, got {horizons}"
        )


# =============================================================================
# Requirement 4: Forecast confidence intervals — lower < point < upper
# =============================================================================


class TestForecastConfidenceIntervals:
    """Verify confidence intervals are properly ordered."""

    def test_confidence_interval_ordering(self) -> None:
        """For each horizon, confidence_lower <= point_estimate <= confidence_upper.
        This ensures the uncertainty bounds are logically consistent."""
        engine = ForecastOrchestrator()
        result = engine.predict(
            patient_features=FULL_PATIENT_FEATURES,
            measurements=MEASUREMENTS,
            targets=["systolic_bp"],
        )

        for horizon in [3, 6, 12]:
            point = result.forecasts["systolic_bp"][horizon]
            lower, upper = result.confidence_intervals["systolic_bp"][horizon]

            assert lower <= point <= upper, (
                f"Horizon {horizon}m: CI ordering violated — "
                f"lower={lower}, point={point}, upper={upper}"
            )

    def test_confidence_intervals_exist_for_all_horizons(self) -> None:
        """Every horizon must have associated confidence intervals."""
        engine = ForecastOrchestrator()
        result = engine.predict(
            patient_features=FULL_PATIENT_FEATURES,
            measurements=MEASUREMENTS,
            targets=["systolic_bp"],
        )

        for horizon in [3, 6, 12]:
            assert horizon in result.confidence_intervals.get("systolic_bp", {}), (
                f"Missing CI for horizon {horizon}m"
            )


# =============================================================================
# Requirement 5: Intervention simulation — directionally correct
# =============================================================================


class TestInterventionSimulation:
    """Verify that health interventions produce directionally correct changes."""

    def test_weight_loss_lowers_blood_pressure(self) -> None:
        """Weight loss intervention should produce LOWER systolic BP forecasts
        compared to baseline — this is well-established clinical evidence."""
        engine = ForecastOrchestrator()
        result = engine.simulate_intervention(
            patient_features=FULL_PATIENT_FEATURES,
            measurements=MEASUREMENTS,
            intervention_type="weight_loss",
            parameters={"target_weight_kg": 85},
        )

        assert len(result.deltas) > 0, "Simulation produced no deltas"

        # Weight loss should reduce BP (negative absolute_delta)
        for delta in result.deltas:
            assert delta.absolute_delta <= 0, (
                f"Weight loss at {delta.horizon_months}m should lower BP, "
                f"got delta={delta.absolute_delta}"
            )

    def test_smoking_cessation_lowers_blood_pressure(self) -> None:
        """Smoking cessation should produce lower BP forecasts.
        Clinical evidence: quitting reduces systolic BP by 5-10 mmHg."""
        engine = ForecastOrchestrator()
        result = engine.simulate_intervention(
            patient_features=FULL_PATIENT_FEATURES,
            measurements=MEASUREMENTS,
            intervention_type="smoking_cessation",
            parameters={},
        )

        assert len(result.deltas) > 0, "Simulation produced no deltas"

        for delta in result.deltas:
            assert delta.absolute_delta <= 0, (
                f"Smoking cessation at {delta.horizon_months}m should lower BP, "
                f"got delta={delta.absolute_delta}"
            )


# =============================================================================
# Requirement 6: Clinical silence returns SILENT when confidence=0
# =============================================================================


class TestClinicalSilence:
    """Verify clinical silence suppresses alerts when confidence is zero."""

    def test_zero_confidence_returns_silent(self) -> None:
        """When model confidence is 0.0 (no trained models), the system must
        return SILENT regardless of risk score — preventing false alarms."""
        silence = ClinicalSilenceEngine()

        for disease in DISEASE_NODES:
            disposition = silence.should_alert(
                disease=disease,
                risk_score=0.9,         # High risk BUT...
                confidence=0.0,         # Zero confidence = untrained model
                ensemble_agreement=0.0,
            )
            assert disposition == "SILENT", (
                f"{disease}: Expected SILENT with 0 confidence, got {disposition}"
            )

    def test_high_everything_returns_alert(self) -> None:
        """When risk, confidence, and agreement are all high, the system
        should escalate to ALERT — confirming the silence engine works
        bidirectionally."""
        silence = ClinicalSilenceEngine()

        for disease in DISEASE_NODES:
            disposition = silence.should_alert(
                disease=disease,
                risk_score=0.95,
                confidence=0.90,
                ensemble_agreement=0.85,
            )
            assert disposition == "ALERT", (
                f"{disease}: Expected ALERT with all-high signals, got {disposition}"
            )


# =============================================================================
# Requirement 7: Cascade network propagates scores (output != input)
# =============================================================================


class TestCascadeNetworkPropagation:
    """Verify the cascade network modifies scores via disease-disease edges."""

    def test_cascade_propagation_changes_scores(self) -> None:
        """When edges exist between diseases, propagation must change at least
        some scores — proving the GNN message passing is active."""
        cascade = CascadeNetwork()

        # Input: non-uniform scores that should trigger cascade effects
        input_scores = {
            "stroke": 0.3,
            "cvd": 0.4,
            "diabetes": 0.8,      # High diabetes should cascade into CKD, CVD
            "ckd": 0.2,
            "hypertensive_crisis": 0.9,  # High HTN should cascade into stroke, CVD
            "copd": 0.3,
        }

        output_scores = cascade.propagate(input_scores)

        # Output must differ from input for at least some diseases
        # (cascade edges exist: diabetes→ckd, htn→stroke, etc.)
        changes = sum(
            1 for d in DISEASE_NODES
            if abs(output_scores[d] - input_scores[d]) > 0.001
        )
        assert changes >= 2, (
            f"Expected cascade to change at least 2 scores, only changed {changes}. "
            f"Input: {input_scores}, Output: {output_scores}"
        )

    def test_cascade_output_remains_in_valid_range(self) -> None:
        """Cascade propagation must keep all outputs in [0.0, 1.0] even
        with extreme input scores — sigmoid activation must clamp."""
        cascade = CascadeNetwork()

        # Extreme inputs: all at 1.0 (worst case for overflow)
        extreme_scores = {d: 1.0 for d in DISEASE_NODES}
        output = cascade.propagate(extreme_scores)

        for disease, score in output.items():
            assert 0.0 <= score <= 1.0, (
                f"Cascade output for {disease} = {score} out of [0,1] range"
            )


# =============================================================================
# Requirement 8: Meta-learner falls back to clinical standards
# =============================================================================


class TestMetaLearnerFallback:
    """Verify meta-learner blends toward clinical standards when data is sparse."""

    def test_zero_sufficiency_produces_low_beta(self) -> None:
        """When data sufficiency is 0 and model confidence is 0, the blending
        weight β should be very low (close to 0), meaning the final output
        is dominated by the clinical standard — not the untrained ML model."""
        meta = AdaptiveMetaLearner()

        # Simulate zero-sufficiency assessment (no useful data)
        assessment = {
            disease: {"sufficiency_score": 0.0, "is_sufficient": False}
            for disease in DISEASE_NODES
        }
        # Zero-confidence expert predictions (untrained models)
        expert_preds = {disease: (0.5, 0.0) for disease in DISEASE_NODES}

        weights = meta.compute_weights(assessment, expert_preds)

        for disease, beta in weights.items():
            assert beta < 0.2, (
                f"{disease}: β={beta:.3f} too high for zero sufficiency — "
                "should fall back to clinical standards"
            )

    def test_full_sufficiency_produces_high_beta(self) -> None:
        """When sufficiency is high and confidence is high, β should be high,
        meaning the ML prediction dominates over clinical standards."""
        meta = AdaptiveMetaLearner()

        assessment = {
            disease: {"sufficiency_score": 0.95, "is_sufficient": True}
            for disease in DISEASE_NODES
        }
        expert_preds = {disease: (0.7, 0.9) for disease in DISEASE_NODES}

        weights = meta.compute_weights(assessment, expert_preds)

        for disease, beta in weights.items():
            assert beta > 0.7, (
                f"{disease}: β={beta:.3f} too low for high sufficiency — "
                "ML should dominate when data is rich"
            )


# =============================================================================
# Requirement 9: Data assessment correctly identifies insufficient data
# =============================================================================


class TestDataAssessmentInsufficiency:
    """Verify data assessment flags sparse patients as insufficient."""

    def test_sparse_patient_marked_insufficient(self) -> None:
        """A patient with only systolic_bp should be marked as data-insufficient
        for most diseases — they're missing critical features."""
        assessor = DataAssessor()
        assessment = assessor.assess_patient(SPARSE_PATIENT_FEATURES, [])

        # With only 1 feature out of many required, most diseases should fail
        insufficient_count = sum(
            1 for disease_data in assessment.values()
            if not disease_data["is_sufficient"]
        )
        assert insufficient_count >= 4, (
            f"Expected at least 4 diseases insufficient with sparse data, "
            f"got {insufficient_count}"
        )

    def test_full_patient_has_higher_completeness(self) -> None:
        """A patient with comprehensive features should have significantly
        higher completeness scores than a sparse patient."""
        assessor = DataAssessor()

        full_assessment = assessor.assess_patient(FULL_PATIENT_FEATURES, MEASUREMENTS)
        sparse_assessment = assessor.assess_patient(SPARSE_PATIENT_FEATURES, [])

        for disease in DISEASE_NODES:
            full_completeness = full_assessment[disease]["completeness"]
            sparse_completeness = sparse_assessment[disease]["completeness"]
            assert full_completeness > sparse_completeness, (
                f"{disease}: Full patient completeness ({full_completeness:.3f}) "
                f"should exceed sparse ({sparse_completeness:.3f})"
            )

    def test_completeness_in_valid_range(self) -> None:
        """Completeness scores must always be in [0.0, 1.0]."""
        assessor = DataAssessor()
        assessment = assessor.assess_patient(FULL_PATIENT_FEATURES, MEASUREMENTS)

        for disease, data in assessment.items():
            assert 0.0 <= data["completeness"] <= 1.0, (
                f"{disease} completeness {data['completeness']} out of range"
            )
            assert 0.0 <= data["freshness"] <= 1.0, (
                f"{disease} freshness {data['freshness']} out of range"
            )
            assert 0.0 <= data["sufficiency_score"] <= 1.0, (
                f"{disease} sufficiency {data['sufficiency_score']} out of range"
            )
