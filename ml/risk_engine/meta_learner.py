"""
PrescpHealth ML Engine — Adaptive Meta-Learner (Layer 4, Patent Claim 2).

Core patent innovation: when data is sparse, don't abandon the patient —
BLEND the ML prediction with established clinical risk calculators
(Framingham, QRISK3, KDIGO) proportionally to data sufficiency.

Formula: final_score = β × ML_score + (1 - β) × clinical_standard_score
    where β = f(sufficiency_score) — β is HIGH when data is rich (trust ML),
    and LOW when data is sparse (fall back to population-level clinical tables).

This ensures the system works from day 1 with zero local training data:
    - New deployment with no trained models? β ≈ 0, output ≈ clinical standard
    - Trained model, full patient data? β ≈ 1, output ≈ ML prediction
    - Partial data? Smooth blend between the two

The clinical standards are NOT competing with ML — they're the safety net
that guarantees clinically-reasonable output even in worst-case data scenarios.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Clinical standard calculators (simplified implementations).
# These return population-level risk estimates using only basic demographics
# and readily available measurements. They work even with minimal data.
# In production, these would call validated implementations (QRISK3 API, etc.)
CLINICAL_STANDARD_FEATURES: dict[str, list[str]] = {
    "stroke": ["age", "systolic_bp", "smoking_status", "atrial_fibrillation"],
    "cvd": ["age", "cholesterol_total", "systolic_bp", "smoking_status"],
    "diabetes": ["age", "bmi", "fasting_glucose", "family_history_diabetes"],
    "ckd": ["age", "egfr", "diabetes_status", "systolic_bp"],
    "hypertensive_crisis": ["systolic_bp", "diastolic_bp", "age"],
    "copd": ["age", "smoking_pack_years", "fev1"],
}

# β computation parameters: maps sufficiency to blending weight.
# β = sigmoid(steepness × (sufficiency - midpoint))
# At midpoint sufficiency, β = 0.5 (equal blend)
# Above midpoint, β → 1.0 (trust ML more)
# Below midpoint, β → 0.0 (trust clinical standard more)
BETA_STEEPNESS: float = 8.0   # How sharply β transitions (higher = sharper)
BETA_MIDPOINT: float = 0.55   # Sufficiency level where β = 0.5


class AdaptiveMetaLearner:
    """Adaptive Meta-Learner blending ML predictions with clinical standards.

    The key insight: clinical risk calculators (Framingham, QRISK3) are
    imperfect but ALWAYS available (they need only age, sex, BP, smoking).
    Our ML models are better but need more data to be trustworthy.

    This layer adaptively blends the two based on data sufficiency,
    ensuring the system ALWAYS produces clinically-reasonable output
    regardless of data availability.
    """

    def __init__(self) -> None:
        """Initialize meta-learner with default parameters."""
        self._steepness: float = BETA_STEEPNESS
        self._midpoint: float = BETA_MIDPOINT

    def compute_weights(
        self,
        patient_assessment: dict[str, dict[str, Any]],
        expert_predictions: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        """Compute per-disease blending weight β between ML and clinical standard.

        β is determined by:
            1. Data sufficiency (from Layer 1 assessment)
            2. Model confidence (from Layer 2 expert predictions)

        A low-confidence ML prediction on sparse data gets β ≈ 0 (ignore ML).
        A high-confidence prediction on complete data gets β ≈ 1 (trust ML).

        Args:
            patient_assessment: Layer 1 output (per-disease sufficiency scores).
            expert_predictions: Layer 2 output (per-disease (prob, confidence)).

        Returns:
            Dict of disease -> β weight in [0.0, 1.0].
        """
        weights: dict[str, float] = {}

        for disease, assessment in patient_assessment.items():
            sufficiency: float = assessment.get("sufficiency_score", 0.0)
            # Get model confidence (second element of prediction tuple)
            _, model_confidence = expert_predictions.get(disease, (0.5, 0.0))

            # Combine sufficiency and model confidence into effective signal
            # Both must be high for β to be high — multiplicative combination
            effective_signal: float = sufficiency * (0.7 + 0.3 * model_confidence)

            # Sigmoid mapping: effective_signal → β
            beta: float = 1.0 / (
                1.0 + np.exp(-self._steepness * (effective_signal - self._midpoint))
            )
            weights[disease] = float(np.clip(beta, 0.0, 1.0))

        return weights

    def compute_clinical_standard(
        self, disease: str, patient_features: dict[str, Any]
    ) -> float:
        """Compute clinical standard risk score using simplified calculators.

        These are approximations of Framingham/QRISK3/KDIGO that work with
        minimal data. In production, these would call validated external APIs.

        Args:
            disease: Target disease.
            patient_features: Available patient features.

        Returns:
            Clinical standard risk score in [0.0, 1.0].
        """
        age = patient_features.get("age", 50.0)
        # Age-based baseline risk (increases non-linearly with age)
        age_factor: float = min(1.0, max(0.0, (age - 30.0) / 60.0))

        if disease == "stroke":
            sbp = patient_features.get("systolic_bp", 130.0)
            bp_factor = min(1.0, max(0.0, (sbp - 100.0) / 100.0))
            af = float(patient_features.get("atrial_fibrillation", 0))
            return float(np.clip(0.3 * age_factor + 0.4 * bp_factor + 0.3 * af, 0.0, 1.0))

        elif disease == "cvd":
            chol = patient_features.get("cholesterol_total", 200.0)
            chol_factor = min(1.0, max(0.0, (chol - 150.0) / 150.0))
            sbp = patient_features.get("systolic_bp", 130.0)
            bp_factor = min(1.0, max(0.0, (sbp - 100.0) / 100.0))
            return float(np.clip(0.3 * age_factor + 0.35 * chol_factor + 0.35 * bp_factor, 0.0, 1.0))

        elif disease == "diabetes":
            bmi = patient_features.get("bmi", 26.0)
            bmi_factor = min(1.0, max(0.0, (bmi - 20.0) / 25.0))
            glucose = patient_features.get("fasting_glucose", 100.0)
            gluc_factor = min(1.0, max(0.0, (glucose - 70.0) / 130.0))
            return float(np.clip(0.2 * age_factor + 0.4 * bmi_factor + 0.4 * gluc_factor, 0.0, 1.0))

        elif disease == "ckd":
            egfr = patient_features.get("egfr", 90.0)
            # Lower eGFR = higher CKD risk (inverse relationship)
            egfr_factor = min(1.0, max(0.0, (120.0 - egfr) / 90.0))
            return float(np.clip(0.3 * age_factor + 0.7 * egfr_factor, 0.0, 1.0))

        elif disease == "hypertensive_crisis":
            sbp = patient_features.get("systolic_bp", 130.0)
            dbp = patient_features.get("diastolic_bp", 80.0)
            sbp_factor = min(1.0, max(0.0, (sbp - 120.0) / 80.0))
            dbp_factor = min(1.0, max(0.0, (dbp - 80.0) / 50.0))
            return float(np.clip(0.6 * sbp_factor + 0.3 * dbp_factor + 0.1 * age_factor, 0.0, 1.0))

        elif disease == "copd":
            pack_years = patient_features.get("smoking_pack_years", 0.0)
            smoke_factor = min(1.0, max(0.0, pack_years / 40.0))
            return float(np.clip(0.3 * age_factor + 0.7 * smoke_factor, 0.0, 1.0))

        # Unknown disease — return moderate baseline risk
        return 0.3

    def blend_predictions(
        self,
        ml_scores: dict[str, float],
        clinical_scores: dict[str, float],
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Blend ML predictions with clinical standards using computed weights.

        Formula: final = β × ML + (1 - β) × clinical_standard

        Args:
            ml_scores: ML model predictions per disease (from cascade network).
            clinical_scores: Clinical standard scores per disease.
            weights: Per-disease β weights from compute_weights().

        Returns:
            Final blended risk scores per disease, all in [0.0, 1.0].
        """
        blended: dict[str, float] = {}
        for disease in ml_scores:
            beta = weights.get(disease, 0.5)
            ml = ml_scores.get(disease, 0.5)
            clinical = clinical_scores.get(disease, 0.3)
            final = beta * ml + (1.0 - beta) * clinical
            blended[disease] = float(np.clip(final, 0.0, 1.0))
        return blended
