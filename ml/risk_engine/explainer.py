"""
PrescpHealth ML Engine — SHAP + Counterfactual Cascade Explanations (Layer 5a, Patent Claim 5).

Core patent innovation: clinicians need to understand WHY a risk score is high,
not just THAT it is high. This module provides two types of explanations:

1. SHAP Feature Contributions: which features drove the prediction up/down?
   (e.g., "systolic_bp contributed +0.15 to stroke risk")

2. Counterfactual Cascade Explanations: "what if we intervene on X? How does
   the cascade effect propagate?" (e.g., "if BP drops by 20, stroke risk drops
   by 12% AND CKD risk drops by 5% via cascade")

This is required for clinical transparency — HIPAA and clinical best practices
demand that AI-assisted decisions be explainable to the treating clinician.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Graceful import — SHAP may not be installed in lightweight deployments
try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False


class RiskExplainer:
    """SHAP-based prediction explainer with counterfactual cascade analysis.

    Provides two explanation modes:
        1. Feature attribution: per-feature SHAP values showing contribution
        2. Counterfactual cascade: "what if" analysis showing intervention effects

    When SHAP is not available, falls back to a simple feature-difference
    heuristic that approximates importance using deviation from population mean.
    """

    def __init__(self) -> None:
        """Initialize explainer with population reference values."""
        # Population means for computing deviation-based explanations
        # when SHAP is unavailable (graceful degradation)
        self._population_means: dict[str, float] = {
            "systolic_bp": 130.0,
            "diastolic_bp": 80.0,
            "cholesterol_total": 200.0,
            "cholesterol_hdl": 50.0,
            "fasting_glucose": 100.0,
            "hba1c": 5.7,
            "bmi": 26.0,
            "egfr": 90.0,
            "creatinine": 1.0,
            "age": 50.0,
            "heart_rate": 75.0,
        }

    def explain_prediction(
        self,
        model: Any,
        features: dict[str, float],
        prediction: float,
    ) -> dict[str, Any]:
        """Explain a single prediction using SHAP or fallback heuristic.

        Args:
            model: The expert model (must support predict for SHAP background).
            features: Feature dict that produced the prediction.
            prediction: The predicted risk score being explained.

        Returns:
            Dict with:
                - 'feature_contributions': dict of feature -> contribution value
                - 'top_risk_factors': list of top 5 positive contributors
                - 'top_protective_factors': list of top 3 negative contributors
                - 'method': 'shap' or 'deviation_heuristic'
        """
        if SHAP_AVAILABLE and hasattr(model, '_model') and model._model is not None:
            return self._explain_with_shap(model, features)

        # Fallback: deviation-based heuristic explanation
        return self._explain_with_deviation(features, prediction)

    def _explain_with_shap(
        self, model: Any, features: dict[str, float]
    ) -> dict[str, Any]:
        """Generate SHAP explanations using the TreeExplainer or KernelExplainer."""
        try:
            feature_names = list(features.keys())
            feature_values = np.array([[features[f] for f in feature_names]])

            # Try TreeExplainer first (fast, exact for tree models)
            explainer = shap.TreeExplainer(model._model)
            shap_values = explainer.shap_values(feature_values)

            # Handle multi-output SHAP (take positive class)
            if isinstance(shap_values, list):
                shap_values = shap_values[1]

            contributions = {
                name: float(shap_values[0][i])
                for i, name in enumerate(feature_names)
            }
        except Exception:
            # If SHAP fails (unsupported model type), fall back to heuristic
            logger.warning("SHAP explanation failed — using deviation heuristic")
            return self._explain_with_deviation(features, 0.5)

        return self._format_explanation(contributions, method="shap")

    def _explain_with_deviation(
        self, features: dict[str, float], prediction: float
    ) -> dict[str, Any]:
        """Heuristic explanation based on deviation from population means.

        Features that deviate most from the population mean are assumed
        to contribute most to the prediction. This is an approximation
        but provides useful directional insight without SHAP.
        """
        contributions: dict[str, float] = {}
        for feature, value in features.items():
            mean = self._population_means.get(feature)
            if mean is not None and mean != 0:
                # Normalized deviation: how many "units" away from population mean
                deviation = (value - mean) / mean
                # Scale by prediction magnitude to approximate contribution
                contributions[feature] = deviation * prediction * 0.3
            else:
                contributions[feature] = 0.0

        return self._format_explanation(contributions, method="deviation_heuristic")

    @staticmethod
    def _format_explanation(
        contributions: dict[str, float], method: str
    ) -> dict[str, Any]:
        """Format raw contributions into structured explanation output."""
        sorted_contribs = sorted(contributions.items(), key=lambda x: x[1], reverse=True)

        top_risk = [(name, val) for name, val in sorted_contribs if val > 0][:5]
        top_protective = [(name, val) for name, val in sorted_contribs if val < 0][:3]

        return {
            "feature_contributions": contributions,
            "top_risk_factors": [{"feature": n, "contribution": round(v, 4)} for n, v in top_risk],
            "top_protective_factors": [{"feature": n, "contribution": round(v, 4)} for n, v in top_protective],
            "method": method,
        }

    def counterfactual_cascade(
        self,
        intervention: dict[str, float],
        current_scores: dict[str, float],
        cascade_network: Any,
    ) -> dict[str, float]:
        """Compute cascade effect of a hypothetical intervention.

        "What if we reduce systolic BP by 20 mmHg? How does that cascade
        through the disease network?"

        Approach:
            1. Estimate direct effect on primary disease (proportional to intervention)
            2. Run the modified scores through the cascade network
            3. Return per-disease delta (new_score - current_score)

        Args:
            intervention: Dict of feature -> delta (e.g., {'systolic_bp': -20})
            current_scores: Current cascade-adjusted risk scores per disease.
            cascade_network: CascadeNetwork instance for re-propagation.

        Returns:
            Dict of disease -> score_delta (negative = improvement from intervention).
        """
        # Estimate direct effect of intervention on raw scores
        # Simple linear approximation: 1% change per unit of relevant feature
        modified_scores = dict(current_scores)

        # Map features to diseases they primarily affect
        feature_disease_map: dict[str, list[tuple[str, float]]] = {
            "systolic_bp": [("stroke", 0.005), ("hypertensive_crisis", 0.008), ("cvd", 0.003)],
            "diastolic_bp": [("hypertensive_crisis", 0.006), ("stroke", 0.003)],
            "cholesterol_total": [("cvd", 0.004), ("stroke", 0.002)],
            "fasting_glucose": [("diabetes", 0.005)],
            "hba1c": [("diabetes", 0.05), ("ckd", 0.02)],
            "bmi": [("diabetes", 0.008), ("cvd", 0.004)],
            "egfr": [("ckd", -0.008)],  # Higher eGFR = lower CKD risk
        }

        for feature, delta in intervention.items():
            disease_effects = feature_disease_map.get(feature, [])
            for disease, sensitivity in disease_effects:
                if disease in modified_scores:
                    change = delta * sensitivity
                    modified_scores[disease] = float(
                        np.clip(modified_scores[disease] + change, 0.0, 1.0)
                    )

        # Re-propagate through cascade network to get second-order effects
        cascaded = cascade_network.propagate(modified_scores)

        # Compute deltas
        deltas: dict[str, float] = {
            disease: round(cascaded.get(disease, 0.5) - current_scores.get(disease, 0.5), 4)
            for disease in current_scores
        }
        return deltas
