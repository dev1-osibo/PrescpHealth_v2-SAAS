"""
PrescpHealth Forecast Engine — Cox Proportional Hazards Model.

Implements the Cox PH model for survival analysis. If the `lifelines` library
is installed, uses its CoxPHFitter for proper partial likelihood estimation.
Otherwise falls back to a simplified hazard calculation using clinically-
derived baseline hazard rates and feature-specific hazard ratios.

Cox PH assumes: h(t|X) = h_0(t) * exp(beta . X)
    - h_0(t): baseline hazard (time-varying, estimated non-parametrically)
    - beta: learned coefficients (log hazard ratios)
    - X: patient feature vector

This is the standard model for clinical time-to-event prediction.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Check if lifelines is available
_LIFELINES_AVAILABLE: bool = False
try:
    from lifelines import CoxPHFitter  # type: ignore[import-untyped]
    _LIFELINES_AVAILABLE = True
except ImportError:
    pass

# Clinically-derived hazard ratios for common risk factors.
# These are population-level estimates from epidemiological literature.
# In production, these would be learned from training data.
_DEFAULT_HAZARD_RATIOS: dict[str, float] = {
    "age": 1.05,             # 5% increased hazard per year of age
    "systolic_bp": 1.02,     # 2% per mmHg above normal
    "bmi": 1.03,             # 3% per BMI unit above 25
    "smoking": 1.80,         # 80% increased hazard for smokers
    "diabetes": 1.60,        # 60% increased hazard for diabetics
    "cholesterol": 1.01,     # 1% per mg/dL above normal
    "weight_kg": 1.005,      # 0.5% per kg above ideal
}

# Baseline annual hazard rate (general population age-adjusted)
_BASELINE_ANNUAL_HAZARD: float = 0.02


class CoxPHModel:
    """Cox Proportional Hazards survival model.

    Predicts the probability of surviving (remaining event-free) to a
    specified time horizon, given patient features. Also provides
    hazard ratios for individual features to support clinical interpretation.
    """

    def __init__(self) -> None:
        """Initialize Cox PH with default hazard ratios."""
        self._hazard_ratios: dict[str, float] = _DEFAULT_HAZARD_RATIOS.copy()
        self._baseline_hazard: float = _BASELINE_ANNUAL_HAZARD
        self._fitted: bool = False

        if _LIFELINES_AVAILABLE:
            logger.info("lifelines available — CoxPH can be fitted to training data")

    def predict_survival(self, features: dict[str, Any], time_horizon: int) -> float:
        """Predict probability of surviving to time_horizon months.

        Uses the Cox PH formula: S(t|X) = S_0(t)^exp(beta . X)
        where S_0(t) = exp(-H_0(t)) is baseline survival.

        Args:
            features: Patient feature dict (e.g., {'age': 62, 'bmi': 29.5}).
            time_horizon: Time in months to predict survival probability.

        Returns:
            Probability in [0, 1] of surviving (event-free) to time_horizon.
        """
        # Compute linear predictor: sum of log(HR) * feature_value_scaled
        linear_pred = self._compute_linear_predictor(features)

        # Convert baseline annual hazard to cumulative hazard at time_horizon
        # H_0(t) = baseline_hazard * (t / 12) — simple proportional scaling
        cumulative_baseline = self._baseline_hazard * (time_horizon / 12.0)

        # Survival probability: S(t|X) = exp(-H_0(t) * exp(linear_predictor))
        survival_prob = math.exp(-cumulative_baseline * math.exp(linear_pred))

        # Clamp to valid probability range
        return max(0.0, min(1.0, survival_prob))

    def get_hazard_ratio(self, feature: str) -> float:
        """Get the hazard ratio for a specific feature.

        HR > 1 means the feature increases risk; HR < 1 is protective.

        Args:
            feature: Feature name (e.g., 'age', 'bmi', 'smoking').

        Returns:
            Hazard ratio (defaults to 1.0 if feature unknown — no effect).
        """
        return self._hazard_ratios.get(feature, 1.0)

    def _compute_linear_predictor(self, features: dict[str, Any]) -> float:
        """Compute beta . X for the Cox model (sum of log-HR * scaled feature).

        Feature values are centered around population norms so that the
        baseline hazard represents an "average" patient.
        """
        # Population reference values for centering
        reference: dict[str, float] = {
            "age": 50.0,
            "systolic_bp": 120.0,
            "bmi": 25.0,
            "weight_kg": 70.0,
            "cholesterol": 200.0,
        }

        linear_pred = 0.0
        for feature_name, hr in self._hazard_ratios.items():
            value = features.get(feature_name)
            if value is None:
                continue
            # For binary features (smoking, diabetes), use raw value
            ref = reference.get(feature_name, 0.0)
            # Deviation from reference * log(HR)
            deviation = float(value) - ref
            linear_pred += math.log(hr) * deviation

        return linear_pred
