"""
PrescpHealth ML Engine — Layer 1: Data Assessment Module.

Implements per-patient data quality scoring as described in the patent:
- Completeness: weighted sum of available features / total weights
- Freshness: exponential decay based on measurement age, with disease-specific decay rates (λ_d)
- Sufficiency: completeness × mean_freshness compared against per-disease learned thresholds

The key innovation (Patent Claim 8) is that decay rates λ_d vary per disease:
- Blood pressure freshness decays rapidly for stroke (λ_stroke = high)
- But slowly for CKD (λ_CKD = low)
- These rates are learned during training from patient outcome data

This module is the gatekeeper: it determines HOW MUCH to trust the ML prediction
vs. falling back to clinical standards (Layer 4 uses this score).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


# =============================================================================
# Constants — Clinical defaults, to be overridden by learned values post-training
# =============================================================================

# Feature importance weights per disease. Higher weight = more critical for that
# disease's prediction accuracy. Weights are normalized internally so they don't
# need to sum to 1.0 — they represent RELATIVE importance.
DISEASE_FEATURE_WEIGHTS: dict[str, dict[str, float]] = {
    "stroke": {
        "systolic_bp": 0.25, "diastolic_bp": 0.15, "heart_rate": 0.10,
        "age": 0.15, "bmi": 0.05, "smoking_status": 0.10,
        "cholesterol_total": 0.10, "atrial_fibrillation": 0.10,
    },
    "cvd": {
        "systolic_bp": 0.15, "diastolic_bp": 0.10, "cholesterol_total": 0.20,
        "cholesterol_hdl": 0.15, "age": 0.10, "bmi": 0.10,
        "smoking_status": 0.10, "diabetes_status": 0.10,
    },
    "diabetes": {
        "fasting_glucose": 0.25, "hba1c": 0.25, "bmi": 0.15,
        "age": 0.10, "family_history_diabetes": 0.10, "waist_circumference": 0.10,
        "physical_activity": 0.05,
    },
    "ckd": {
        "egfr": 0.30, "creatinine": 0.20, "albumin_creatinine_ratio": 0.15,
        "systolic_bp": 0.10, "age": 0.10, "diabetes_status": 0.10,
        "proteinuria": 0.05,
    },
    "hypertensive_crisis": {
        "systolic_bp": 0.35, "diastolic_bp": 0.25, "heart_rate": 0.15,
        "age": 0.10, "kidney_function": 0.10, "medication_adherence": 0.05,
    },
    "copd": {
        "fev1": 0.25, "fev1_fvc_ratio": 0.20, "smoking_pack_years": 0.20,
        "age": 0.10, "bmi": 0.10, "dyspnea_score": 0.10,
        "exacerbation_history": 0.05,
    },
}

# Decay rates (λ_d) per disease — controls how fast measurement freshness drops.
# Units: 1/days. Higher λ = faster decay = disease needs more recent data.
# Example: λ=0.05 means 50% freshness at ~14 days; λ=0.01 means 50% at ~69 days.
# These are clinical defaults; training refines them from outcome data.
DISEASE_DECAY_RATES: dict[str, float] = {
    "stroke": 0.05,              # BP changes rapidly; needs fresh readings
    "cvd": 0.02,                 # Cardiovascular risk evolves more slowly
    "diabetes": 0.015,           # HbA1c reflects ~3 months; slower decay
    "ckd": 0.01,                 # Kidney disease progresses slowly
    "hypertensive_crisis": 0.07, # Acute — needs very recent BP data
    "copd": 0.012,               # Lung function changes slowly over months
}

# Minimum sufficiency score for the ML prediction to be trusted.
# Below this threshold, Layer 4 blends the ML output with clinical standards
# (fallback to population-level risk tables like Framingham/QRISK3).
DISEASE_SUFFICIENCY_THRESHOLDS: dict[str, float] = {
    "stroke": 0.55,
    "cvd": 0.50,
    "diabetes": 0.50,
    "ckd": 0.45,                 # CKD tolerable with less data (slow progression)
    "hypertensive_crisis": 0.60, # Acute events need high confidence
    "copd": 0.45,
}

# All diseases the engine supports
SUPPORTED_DISEASES: list[str] = list(DISEASE_FEATURE_WEIGHTS.keys())


class DataAssessor:
    """Layer 1: Per-patient data quality scoring.

    Determines whether we have ENOUGH RECENT data to trust the ML prediction
    for each disease. If not, Layer 4 will blend ML output with clinical
    standards (risk tables) proportionally to the sufficiency deficit.

    This is NOT a binary gate — it produces a continuous score that modulates
    confidence. A patient with 80% sufficiency still gets an ML prediction,
    but with lower confidence weight vs. clinical standards.
    """

    def compute_completeness(
        self, patient_features: dict[str, Any], disease: str
    ) -> float:
        """Compute feature completeness score for a specific disease.

        Completeness = sum(weights of available features) / sum(all weights).
        A patient with all features present scores 1.0; one with none scores 0.0.

        Args:
            patient_features: Dict of feature_name -> value. A feature is
                             considered "present" if its key exists and value
                             is not None.
            disease: Which disease to assess completeness for.

        Returns:
            Float in [0.0, 1.0] representing weighted feature completeness.
        """
        weights = DISEASE_FEATURE_WEIGHTS.get(disease, {})
        if not weights:
            return 0.0

        total_weight: float = sum(weights.values())
        available_weight: float = 0.0

        for feature, weight in weights.items():
            # Feature counts as present if key exists and value is not None
            if feature in patient_features and patient_features[feature] is not None:
                available_weight += weight

        return available_weight / total_weight if total_weight > 0 else 0.0

    def compute_freshness(
        self, measurements: list[dict[str, Any]], disease: str
    ) -> float:
        """Compute temporal freshness score using exponential decay.

        Formula per measurement: freshness(m) = exp(-λ_d × days_since_measurement)
        Overall freshness = mean of per-measurement freshness scores.

        The decay rate λ_d varies by disease (Patent Claim 8):
        - Stroke needs very fresh BP readings (high λ → fast decay)
        - CKD tolerates older data (low λ → slow decay)

        Args:
            measurements: List of dicts with keys:
                - 'type': measurement type (str)
                - 'recorded_at': ISO datetime string or datetime object
            disease: Disease to compute freshness for (determines decay rate).

        Returns:
            Float in [0.0, 1.0]. Returns 1.0 if no measurements (no penalty
            for missing — that's handled by completeness).
        """
        if not measurements:
            # No measurements means freshness isn't the bottleneck — completeness is.
            # Return neutral 1.0 so sufficiency is driven by completeness alone.
            return 1.0

        decay_rate: float = DISEASE_DECAY_RATES.get(disease, 0.02)
        now = datetime.now(tz=timezone.utc)
        freshness_scores: list[float] = []

        for measurement in measurements:
            recorded_at = measurement.get("recorded_at")
            if recorded_at is None:
                continue

            # Parse ISO string if needed
            if isinstance(recorded_at, str):
                # Handle both timezone-aware and naive datetime strings
                recorded_at = datetime.fromisoformat(recorded_at)

            # Make timezone-aware if naive (assume UTC)
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)

            days_elapsed: float = (now - recorded_at).total_seconds() / 86400.0
            # Clamp to non-negative (future dates treated as perfectly fresh)
            days_elapsed = max(0.0, days_elapsed)

            # Core freshness formula: exponential decay
            score = math.exp(-decay_rate * days_elapsed)
            freshness_scores.append(score)

        if not freshness_scores:
            return 1.0

        # Mean freshness across all measurements
        return sum(freshness_scores) / len(freshness_scores)

    def compute_sufficiency(
        self, completeness: float, freshness: float, disease: str
    ) -> tuple[float, bool]:
        """Combine completeness and freshness into a sufficiency decision.

        Sufficiency = completeness × freshness (both must be adequate).
        This multiplicative combination means:
        - High completeness + stale data = low sufficiency (don't trust old data)
        - Fresh data + many missing features = low sufficiency (not enough signal)

        Args:
            completeness: Output of compute_completeness() in [0.0, 1.0].
            freshness: Output of compute_freshness() in [0.0, 1.0].
            disease: Disease to check threshold for.

        Returns:
            Tuple of (sufficiency_score, is_sufficient):
                - sufficiency_score: float in [0.0, 1.0]
                - is_sufficient: True if score >= disease threshold
        """
        sufficiency_score: float = completeness * freshness
        threshold: float = DISEASE_SUFFICIENCY_THRESHOLDS.get(disease, 0.50)
        is_sufficient: bool = sufficiency_score >= threshold

        return sufficiency_score, is_sufficient

    def assess_patient(
        self,
        patient_features: dict[str, Any],
        measurements: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Full Layer 1 assessment across all diseases for one patient.

        This is the main entry point. It computes completeness, freshness,
        and sufficiency for each of the 6 supported diseases and returns
        a comprehensive assessment dict.

        Args:
            patient_features: All known features for this patient.
            measurements: All recent measurements with timestamps.

        Returns:
            Dict mapping disease -> assessment details:
            {
                "stroke": {
                    "completeness": 0.75,
                    "freshness": 0.82,
                    "sufficiency_score": 0.615,
                    "is_sufficient": True,
                },
                ...
            }
        """
        assessment: dict[str, dict[str, Any]] = {}

        for disease in SUPPORTED_DISEASES:
            completeness = self.compute_completeness(patient_features, disease)
            freshness = self.compute_freshness(measurements, disease)
            sufficiency_score, is_sufficient = self.compute_sufficiency(
                completeness, freshness, disease
            )

            assessment[disease] = {
                "completeness": round(completeness, 4),
                "freshness": round(freshness, 4),
                "sufficiency_score": round(sufficiency_score, 4),
                "is_sufficient": is_sufficient,
            }

        return assessment
