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

from pathlib import Path

from ml.risk_engine.cascade_network import CascadeNetwork, DISEASE_NODES
from ml.risk_engine.clinical_silence import ClinicalSilenceEngine
from ml.risk_engine.data_assessment import DataAssessor
from ml.risk_engine.explainer import RiskExplainer
from ml.risk_engine.imputation import BayesianImputer
from ml.risk_engine.meta_learner import AdaptiveMetaLearner
from ml.risk_engine.model_registry import RiskModelRegistry

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

    def __init__(self, artifacts_root: str | Path | None = None) -> None:
        """Initialize all pipeline components.

        Args:
            artifacts_root: Optional root directory of trained model artifacts.
                When provided (or set via PRESCP_ML_ARTIFACTS_ROOT), each disease
                gets its OWN ensemble of experts loaded from
                ``<root>/<disease>/<expert>/``. When None and no env var is set,
                experts are constructed untrained and return (0.5, 0.0) — the
                meta-learner (Layer 4) then falls back to clinical standards.
                This is intentional graceful degradation for day-1 deployments.

        Design note: experts are now instantiated PER DISEASE (not a single
        shared ensemble reused across diseases). This is required for real
        per-disease models — the stroke ensemble and the diabetes ensemble load
        different artifacts and expose different feature sets.
        """
        # Layer 1: Data Assessment
        self._assessor = DataAssessor()

        # Layer 1.5: Imputation
        self._imputer = BayesianImputer()

        # Layer 2: Per-disease expert ensembles, loaded via the registry.
        # Each disease owns an independent list of experts so trained artifacts
        # (and feature sets) never leak across diseases.
        self._registry = RiskModelRegistry(artifacts_root)
        self._experts_by_disease = {
            disease: self._registry.build_experts(disease) for disease in DISEASE_NODES
        }

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
        # Retain each disease's per-expert probabilities so Layer 5 can compute
        # ensemble agreement WITHOUT re-predicting (and on the same imputed
        # features the ensemble score was derived from — consistency matters).
        expert_probs_by_disease: dict[str, list[float]] = {}

        for disease in DISEASE_NODES:
            # Impute missing features for this disease
            imputed, mask = self._imputer.impute(patient_features, disease)
            # Merge mask into features (missingness-as-feature)
            combined = {**imputed, **{k: float(v) for k, v in mask.items()}}

            # Collect predictions from THIS disease's own expert ensemble
            disease_probs: list[float] = []
            disease_confs: list[float] = []
            for expert in self._experts_by_disease[disease]:
                prob, conf = expert.predict(combined)
                disease_probs.append(prob)
                disease_confs.append(conf)

            expert_probs_by_disease[disease] = disease_probs

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

            # Ensemble agreement: fraction of THIS disease's experts predicting
            # elevated risk. Reuses the Layer-2 probabilities (computed on the
            # imputed feature set) instead of re-predicting on raw features.
            disease_experts = self._experts_by_disease[disease]
            disease_probs = expert_probs_by_disease[disease]
            expert_high = sum(1 for p in disease_probs if p > 0.5)
            agreement = expert_high / len(disease_probs) if disease_probs else 0.0

            # Clinical silence decision
            disposition = self._silence.should_alert(disease, score, conf, agreement)

            # Explanation (use this disease's first expert as SHAP representative)
            explanation = self._explainer.explain_prediction(
                disease_experts[0], patient_features, score
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
        # Per-disease trained-model version for the audit trail (0.0.0 = untrained).
        result.model_versions = {
            disease: self._registry.disease_version(disease) for disease in DISEASE_NODES
        }
        result.pipeline_status = "success"

        logger.info(
            "Risk prediction completed",
            extra={"duration_ms": result.computation_time_ms, "disease_count": len(DISEASE_NODES)},
        )
        return result
