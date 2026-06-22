"""
PrescpHealth Forecast Engine — Forecast Ensemble Combiner.

Combines predictions from multiple forecasting models (TFT, LSTM, Prophet)
into a single consensus forecast using weighted averaging. Weights can be
learned from validation performance or default to equal weighting.

The ensemble approach provides:
    - Reduced variance (averaging smooths individual model noise)
    - Robustness (no single model failure ruins the prediction)
    - Wider confidence intervals (union of individual CIs captures true uncertainty)
"""

from __future__ import annotations

import logging
from typing import Any

from ml.forecast_engine.models.base_forecaster import ForecastPoint

logger = logging.getLogger(__name__)


class ForecastEnsemble:
    """Weighted ensemble combiner for multiple forecaster outputs.

    Takes a list of ForecastPoint predictions from different models and
    produces a single combined ForecastPoint. Confidence intervals are
    widened to the union of individual model CIs (conservative approach
    that better captures epistemic uncertainty).
    """

    def __init__(self, default_weights: list[float] | None = None) -> None:
        """Initialize ensemble with optional learned weights.

        Args:
            default_weights: Pre-learned weights for each model.
                If None, uses equal weighting (1/n for n models).
                Weights are normalized to sum to 1.0.
        """
        self._default_weights: list[float] | None = default_weights
        self._validation_scores: dict[str, float] = {}

    def combine(
        self, forecasts: list[ForecastPoint], weights: list[float] | None = None
    ) -> ForecastPoint:
        """Combine multiple forecasts into a single ensemble prediction.

        Point estimate: weighted average of individual estimates.
        Confidence bounds: union (min lower, max upper) of individual CIs.
        Data quality: weighted average of individual qualities.

        Args:
            forecasts: List of ForecastPoint from different models.
            weights: Optional weights for this specific combination.
                If None, uses default_weights or equal weighting.

        Returns:
            Combined ForecastPoint with consensus estimate and wide CIs.
        """
        if not forecasts:
            return ForecastPoint(
                point_estimate=0.0, confidence_lower=0.0,
                confidence_upper=0.0, data_quality=0.0,
            )

        if len(forecasts) == 1:
            return forecasts[0]

        # Resolve weights: explicit > default > equal
        effective_weights = self._resolve_weights(len(forecasts), weights)

        # Weighted average point estimate
        point_estimate = sum(
            f.point_estimate * w for f, w in zip(forecasts, effective_weights)
        )

        # Union of confidence intervals (conservative — captures all model uncertainty)
        # This is wider than a weighted average of CIs, which is intentional:
        # if ANY model thinks the value could be extreme, we want to flag that
        confidence_lower = min(f.confidence_lower for f in forecasts)
        confidence_upper = max(f.confidence_upper for f in forecasts)

        # Weighted average data quality
        data_quality = sum(
            f.data_quality * w for f, w in zip(forecasts, effective_weights)
        )

        return ForecastPoint(
            point_estimate=round(point_estimate, 2),
            confidence_lower=round(confidence_lower, 2),
            confidence_upper=round(confidence_upper, 2),
            data_quality=round(data_quality, 2),
        )

    def _resolve_weights(
        self, n_models: int, explicit_weights: list[float] | None
    ) -> list[float]:
        """Determine effective weights, normalizing to sum to 1.0.

        Priority: explicit argument > stored default > equal weighting.
        """
        if explicit_weights and len(explicit_weights) == n_models:
            raw = explicit_weights
        elif self._default_weights and len(self._default_weights) == n_models:
            raw = self._default_weights
        else:
            # Equal weighting fallback
            return [1.0 / n_models] * n_models

        # Normalize to sum to 1.0
        total = sum(raw)
        if total <= 0:
            return [1.0 / n_models] * n_models
        return [w / total for w in raw]

    def update_weights_from_validation(
        self, model_names: list[str], mae_scores: list[float]
    ) -> list[float]:
        """Learn weights from validation MAE (lower MAE = higher weight).

        Assigns weight proportional to 1/MAE so better-performing models
        get more influence in the ensemble.

        Args:
            model_names: Names of models corresponding to forecasts list order.
            mae_scores: Mean Absolute Error from validation set per model.

        Returns:
            Updated normalized weights (also stored as default).
        """
        # Inverse MAE weighting: better models (lower MAE) get higher weight
        inverse_mae = [1.0 / max(mae, 0.001) for mae in mae_scores]
        total = sum(inverse_mae)
        new_weights = [w / total for w in inverse_mae]

        self._default_weights = new_weights
        for name, weight in zip(model_names, new_weights):
            self._validation_scores[name] = weight
            logger.info("Ensemble weight for %s: %.3f", name, weight)

        return new_weights
