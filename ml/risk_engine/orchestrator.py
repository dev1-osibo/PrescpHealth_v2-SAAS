"""
PrescpHealth ML Engine — Risk Prediction Orchestrator (Main Pipeline).

This is the top-level entry point that ties all 5 layers together:
    Layer 1: DataAssessor → data quality scoring
    Layer 2: Expert Models → per-disease ML predictions
    Layer 3: CascadeNetwork → disease-disease interaction propagation
    Layer 4: AdaptiveMetaLearner → ML/clinical-standard blending
    Layer 5a: RiskExplainer → SHAP + counterfactual explanations
    Layer 5b: ClinicalSilenceEngine → alert/inform/silence decisions

The orchestrator follows a strict pipeline:
    patient_features + measurements
        → assess data quality (Layer 1)
        → impute missing values (Layer 1.5)
        → predict per-disease risk (Layer 2)
        → propagate cascades (Layer 3)
        → blend with clinical standards (Layer 4)
        → explain predictions (Layer 5a)
        → determine alert disposition (Layer 5b)
        → return structured RiskPredictionResult
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ml.risk_engine.cascade_network import CascadeNetwork, DISEASE_NODES
from ml.risk_engine.clinical_silence import ClinicalSilenceEngine
from ml.risk_engine.data_assessment import DataAssessor
from ml.risk_engine.explainer import RiskExplainer
from ml.risk_engine.imputation import BayesianImputer
from ml.risk_engine.meta_learner import AdaptiveMetaLearner
from ml.risk_engine.models.xgboost_expert import XGBoostExpert
from ml.risk_engine.models.lightgbm_expert import LightGBMExpert
from ml.risk_engine.models.catboost_expert import CatBoostExpert
from ml.risk_engine.models.neural_expert import NeuralExpert

logger = logging.getLogger(__name__)


# Risk strata thresholds — maps score ranges to clinical severity labels
RISK_STRATA: list[tuple[float, str]] = [
    (0.75, "CRITICAL"),
    (0.50, "HIGH"),
    (0.25, "MODERATE"),
    (0.0, "LOW"),
]


@dataclass
class DiseaseResult:
    """Structured result for a single disease prediction."""

    disease: str
    risk_score: float
    stratum: str
    confidence: float
    alert_disposition: str
    explanation: dict[str, Any] = field(default_factory=dict)
    data_sufficiency: float = 0.0
    beta_weight: float = 0.0


@dataclass
class RiskPredictionResult:
    """Complete output of the risk prediction pipeline."""

    diseases: dict[str, DiseaseResult] = field(default_factory=dict)
    computation_time_ms: float = 0.0
    model_versions: dict[str, str] = field(default_factory=dict)
    pipeline_status: str = "success"

    def __repr__(self) -> str:
        """Human-readable summary for debugging."""
        lines = [f"RiskPredictionResult (computed in {self.computation_time_ms:.0f}ms):"]
        for disease, result in self.diseases.items():
            lines.append(
                f"  {disease}: {result.risk_score:.2f} ({result.stratum}) "
                f"[{result.alert_disposition}] conf={result.confidence:.2f}"
            )
        return "\n".join(lines)


def _score_to_stratum(score: float) -> str:
    """Map a risk score to its clinical stratum label."""
    for threshold, label in RISK_STRATA:
        if score >= threshold:
            return label
    return "LOW"


class RiskOrchestrator:
    """Main pipeline orchestrator — ties Layer 1→2→3→4→5 together.

    Instantiates all layer components and runs the full prediction pipeline
    for a single patient. Designed to be called by Celery workers or
    directly for synchronous computation.
    """

    def __init__(self) -> None:
        """Initialize all pipeline components.

        Expert models start without trained artifacts — they return dummy
        predictions (0.5, 0.0) until artifacts are loaded. This is intentional:
        the meta-learner (Layer 4) will detect zero confidence and fall back
        to clinical standards automatically.
        """
        # Layer 1: Data Assessment
        self._assessor = DataAssessor()

        # Layer 1.5: Imputation
        self._imputer = BayesianImputer()

        # Layer 2: Expert Models (one per architecture, disease-agnostic)
        self._experts = [
            XGBoostExpert(disease_name="ensemble", version="0.0.0"),
            LightGBMExpert(disease_name="ensemble", version="0.0.0"),
            CatBoostExpert(disease_name="ensemble", version="0.0.0"),
            NeuralExpert(disease_name="ensemble", version="0.0.0"),
        ]

        # Layer 3: Disease Cascade Network
        self._cascade = CascadeNetwork()

        # Layer 4: Adaptive Meta-Learner
        self._meta_learner = AdaptiveMetaLearner()

        # Layer 5a: Explainer
        self._explainer = RiskExplainer()

        # Layer 5b: Clinical Silence
        self._silence = ClinicalSilenceEngine()

    def predict(
        self,
        patient_features: dict[str, Any],
        measurements: list[dict[str, Any]],
        medications: list[str] | None = None,
    ) -> RiskPredictionResult:
        """Run the full 5-layer prediction pipeline for one patient.

        Args:
            patient_features: All known features for this patient.
            measurements: Recent measurements with 'type', 'value', 'recorded_at'.
            medications: Optional list of medication classes (for iatrogenic cascades).

        Returns:
            RiskPredictionResult with per-disease scores, strata, explanations,
            and alert dispositions.
        """
        start = time.perf_counter()

        # --- Layer 1: Data Assessment ---
        assessment = self._assessor.assess_patient(patient_features, measurements)

        # --- Layer 2: Expert Predictions (per disease) ---
        raw_scores: dict[str, float] = {}
        expert_preds: dict[str, tuple[float, float]] = {}
        confidences: dict[str, float] = {}

        for disease in DISEASE_NODES:
            # Impute missing features for this disease
            imputed, mask = self._imputer.impute(patient_features, disease)
            # Merge mask into features (missingness-as-feature)
            combined = {**imputed, **{k: float(v) for k, v in mask.items()}}

            # Collect predictions from all experts
            disease_probs: list[float] = []
            disease_confs: list[float] = []
            for expert in self._experts:
                prob, conf = expert.predict(combined)
                disease_probs.append(prob)
                disease_confs.append(conf)

            # Ensemble: mean probability, mean confidence
            raw_scores[disease] = float(sum(disease_probs) / len(disease_probs))
            mean_conf = float(sum(disease_confs) / len(disease_confs))
            confidences[disease] = mean_conf
            expert_preds[disease] = (raw_scores[disease], mean_conf)

        # --- Layer 3: Disease Cascade Network ---
        cascaded_scores = self._cascade.propagate(raw_scores, medications)

        # --- Layer 4: Adaptive Meta-Learner ---
        weights = self._meta_learner.compute_weights(assessment, expert_preds)
        clinical_scores: dict[str, float] = {
            disease: self._meta_learner.compute_clinical_standard(disease, patient_features)
            for disease in DISEASE_NODES
        }
        final_scores = self._meta_learner.blend_predictions(cascaded_scores, clinical_scores, weights)

        # --- Layer 5: Explanations + Clinical Silence ---
        result = RiskPredictionResult()
        for disease in DISEASE_NODES:
            score = final_scores.get(disease, 0.5)
            conf = confidences.get(disease, 0.0)

            # Ensemble agreement: fraction of experts that agree on direction
            expert_high = sum(1 for e in self._experts if e.predict(patient_features)[0] > 0.5)
            agreement = expert_high / len(self._experts)

            # Clinical silence decision
            disposition = self._silence.should_alert(disease, score, conf, agreement)

            # Explanation (use first expert as representative for SHAP)
            explanation = self._explainer.explain_prediction(
                self._experts[0], patient_features, score
            )

            result.diseases[disease] = DiseaseResult(
                disease=disease,
                risk_score=round(score, 4),
                stratum=_score_to_stratum(score),
                confidence=round(conf, 4),
                alert_disposition=disposition,
                explanation=explanation,
                data_sufficiency=assessment.get(disease, {}).get("sufficiency_score", 0.0),
                beta_weight=round(weights.get(disease, 0.5), 4),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        result.computation_time_ms = round(elapsed_ms, 2)
        result.model_versions = {e.disease: e.model_version for e in self._experts}
        result.pipeline_status = "success"

        logger.info(
            "Risk prediction completed",
            extra={"duration_ms": result.computation_time_ms, "disease_count": len(DISEASE_NODES)},
        )
        return result
