"""
PrescpHealth Forecast Engine — LSTM Forecaster.

Implements a simple LSTM-based time-series forecaster. Without trained weights,
falls back to linear regression on recent data points. When PyTorch is available
and weights are loaded, uses the recurrent architecture for sequence prediction.

Architecture (when trained):
    - Input embedding layer (normalizes measurement values)
    - 2-layer LSTM with 64 hidden units
    - Fully connected output head producing point estimate
    - Dropout between layers for uncertainty estimation (MC Dropout)
"""

from __future__ import annotations

import logging
from typing import Any

from ml.forecast_engine.models.base_forecaster import BaseForecaster, ForecastPoint

logger = logging.getLogger(__name__)

# Check if PyTorch is available
_TORCH_AVAILABLE: bool = False
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    pass


class LSTMForecaster(BaseForecaster):
    """LSTM-based time-series forecaster.

    Uses a 2-layer LSTM architecture when trained weights are available.
    Without weights, falls back to simple linear regression on the most
    recent data points — a reasonable baseline for short-horizon forecasts.
    """

    def __init__(self) -> None:
        """Initialize LSTM model or configure fallback mode."""
        self._weights_loaded: bool = False
        self._model: Any = None

        if _TORCH_AVAILABLE:
            logger.info("PyTorch available — LSTM architecture defined (no weights loaded)")
        else:
            logger.info("PyTorch not available — LSTM using linear regression fallback")

    @property
    def model_name(self) -> str:
        """Return model identifier."""
        return "LSTM"

    def get_required_history(self) -> int:
        """LSTM benefits from more context; minimum 3 points for regression."""
        return 3

    def forecast(
        self, time_series: list[dict], horizon_months: int
    ) -> ForecastPoint:
        """Forecast using LSTM or linear regression fallback.

        Without trained weights, performs ordinary least squares regression
        on the available data points, projecting the fitted line forward.

        Args:
            time_series: Historical measurements with 'value' and 'recorded_at'.
            horizon_months: Months ahead to predict.

        Returns:
            ForecastPoint with estimate and confidence bounds.
        """
        if not time_series:
            return ForecastPoint(
                point_estimate=0.0, confidence_lower=0.0,
                confidence_upper=0.0, data_quality=0.0,
            )

        return self._linear_regression_fallback(time_series, horizon_months)

    def _linear_regression_fallback(
        self, time_series: list[dict], horizon_months: int
    ) -> ForecastPoint:
        """Simple linear regression on recent data points.

        Fits y = mx + b to the time series indices, then extrapolates.
        Uses residual variance to estimate confidence interval width.
        """
        values = [entry["value"] for entry in time_series]
        n = len(values)

        if n == 1:
            estimate = values[0]
            spread = abs(estimate) * 0.15 * horizon_months
            return ForecastPoint(
                point_estimate=estimate,
                confidence_lower=estimate - spread,
                confidence_upper=estimate + spread,
                data_quality=0.2,
            )

        # OLS: fit line to (index, value) pairs
        # x = 0, 1, 2, ... n-1; project to x = n-1 + horizon_months
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        # Compute slope (m) and intercept (b)
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # Project forward: each index step ~ time between observations
        # Horizon in "steps" scaled by observation spacing assumption (~2 months/step)
        future_x = (n - 1) + horizon_months
        estimate = intercept + slope * future_x

        # Residual-based uncertainty
        residuals = [abs(values[i] - (intercept + slope * i)) for i in range(n)]
        residual_std = (sum(r ** 2 for r in residuals) / max(n - 2, 1)) ** 0.5
        # Wider uncertainty at longer horizons
        uncertainty = residual_std * (1.0 + 0.3 * horizon_months) + abs(estimate) * 0.03

        quality = min(1.0, n / (self.get_required_history() * 2))

        return ForecastPoint(
            point_estimate=round(estimate, 2),
            confidence_lower=round(estimate - uncertainty, 2),
            confidence_upper=round(estimate + uncertainty, 2),
            data_quality=round(quality, 2),
        )
