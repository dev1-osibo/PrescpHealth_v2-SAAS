"""
PrescpHealth ML Engine — Bayesian Imputation + Missingness Encoding (Patent Claim 6).

Key patent innovation: the ABSENCE of a test is itself clinical information.
If a doctor did NOT order an eGFR test, that's a signal — either the doctor
doesn't suspect kidney issues, or the patient couldn't afford it, or the lab
isn't available. All three scenarios carry predictive value.

This module:
    1. Imputes missing values using Bayesian population-level priors
    2. Creates a binary missingness mask that becomes ADDITIONAL FEATURES
       for the expert models (e.g., 'egfr_missing' = 1 when eGFR not ordered)

The missingness mask doubles as an "information-about-absence" channel that
the model learns to interpret during training. This is superior to simple
mean imputation because it preserves the clinical semantics of missing data.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Population-level priors for imputation: (mean, std_dev) per feature.
# These represent what we'd expect from the general population when a
# measurement is unavailable. Learned values override these after training.
# Source: WHO population health statistics, clinical reference ranges.
POPULATION_PRIORS: dict[str, tuple[float, float]] = {
    "systolic_bp": (130.0, 20.0),
    "diastolic_bp": (80.0, 12.0),
    "heart_rate": (75.0, 12.0),
    "cholesterol_total": (200.0, 40.0),
    "cholesterol_hdl": (50.0, 15.0),
    "cholesterol_ldl": (130.0, 35.0),
    "fasting_glucose": (100.0, 25.0),
    "hba1c": (5.7, 1.0),
    "bmi": (26.0, 5.0),
    "egfr": (90.0, 20.0),
    "creatinine": (1.0, 0.3),
    "albumin_creatinine_ratio": (15.0, 10.0),
    "fev1": (80.0, 15.0),
    "fev1_fvc_ratio": (0.75, 0.10),
    "waist_circumference": (90.0, 15.0),
    "age": (50.0, 15.0),
}

# Disease-specific prior adjustments: certain diseases shift the expected
# population mean for imputation. E.g., if computing diabetes risk, a missing
# fasting_glucose is imputed slightly higher (selection bias — doctors order
# the test when they suspect elevated glucose).
DISEASE_PRIOR_SHIFTS: dict[str, dict[str, float]] = {
    "diabetes": {"fasting_glucose": 10.0, "hba1c": 0.3, "bmi": 2.0},
    "ckd": {"egfr": -10.0, "creatinine": 0.2},
    "stroke": {"systolic_bp": 10.0},
    "cvd": {"cholesterol_total": 15.0, "systolic_bp": 5.0},
    "hypertensive_crisis": {"systolic_bp": 15.0, "diastolic_bp": 8.0},
    "copd": {"fev1": -10.0, "fev1_fvc_ratio": -0.05},
}


class BayesianImputer:
    """Bayesian imputation with missingness encoding (Patent Claim 6).

    Imputes missing patient features using population-level priors while
    simultaneously generating a missingness mask that serves as additional
    model input. The mask captures the clinical information embedded in
    which tests were or were NOT ordered.

    Priors can be updated with learned values after model training completes
    on real population data, via update_priors().
    """

    def __init__(self) -> None:
        """Initialize with default population priors."""
        # Mutable copy — can be updated with learned priors post-training
        self._priors: dict[str, tuple[float, float]] = dict(POPULATION_PRIORS)
        self._disease_shifts: dict[str, dict[str, float]] = dict(DISEASE_PRIOR_SHIFTS)

    def update_priors(self, learned_priors: dict[str, tuple[float, float]]) -> None:
        """Override default priors with values learned from real population data.

        Args:
            learned_priors: Dict of feature_name -> (mean, std_dev) learned
                           from the deployment population.
        """
        self._priors.update(learned_priors)
        logger.info("Updated %d population priors from learned values", len(learned_priors))

    def impute(
        self, patient_features: dict[str, Any], disease: str
    ) -> tuple[dict[str, float], dict[str, int]]:
        """Impute missing features and generate missingness mask.

        For each feature expected by the disease model:
            - If present and not None: keep original value, mask = 0
            - If missing or None: impute from prior (with disease shift), mask = 1

        The missingness mask entries (e.g., 'systolic_bp_missing': 1) become
        ADDITIONAL input features for the expert models. The model learns
        during training what missingness means clinically.

        Args:
            patient_features: Raw patient data (may have None or missing keys).
            disease: Target disease (affects prior shift direction).

        Returns:
            Tuple of (imputed_features, missingness_mask):
                - imputed_features: dict with all features filled
                - missingness_mask: dict of {feature_name}_missing -> 0 or 1
        """
        imputed: dict[str, float] = {}
        mask: dict[str, int] = {}
        shifts = self._disease_shifts.get(disease, {})

        for feature, (mean, std) in self._priors.items():
            value = patient_features.get(feature)

            if value is not None:
                # Feature is present — use actual value, mark as not missing
                imputed[feature] = float(value)
                mask[f"{feature}_missing"] = 0
            else:
                # Feature is missing — impute from Bayesian prior with disease shift
                shift = shifts.get(feature, 0.0)
                imputed_value = mean + shift
                # Add small noise proportional to uncertainty (std)
                # This prevents the model from learning that imputed values
                # are always exactly at the prior mean (which would be leakage)
                noise = np.random.normal(0.0, std * 0.1)
                imputed[feature] = imputed_value + noise
                mask[f"{feature}_missing"] = 1

        # Also pass through any features the patient has that aren't in our priors
        # (e.g., custom features added by the clinic)
        for feature, value in patient_features.items():
            if feature not in self._priors and value is not None:
                imputed[feature] = float(value)
                mask[f"{feature}_missing"] = 0

        return imputed, mask

    def get_expected_features(self) -> list[str]:
        """Return list of features this imputer knows about.

        Useful for Layer 1 data assessment to know which features
        are expected by the imputation pipeline.
        """
        return list(self._priors.keys())
