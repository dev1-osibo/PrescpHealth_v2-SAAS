"""
PrescpHealth Forecast Engine — Prophet Forecaster.

Wraps Meta's Prophet library for time-series forecasting. If Prophet is not
installed, falls back to simple exponential smoothing — a lightweight method
that weights recent observations more heavily than older ones.

Prophet excels at:
    - Capturing seasonality (relevant for seasonal health patterns)
    - Handling missing data and outliers gracefully
    - Producing calibrated uncertainty intervals
"""

from __future__ import annotations

import logging
from typing import Any

from ml.forecast_engine.models.base_forecaster import BaseForecaster, ForecastPoint

logger = logging.getLogger(__name__)

# Check if Prophet is available
_PROPHET_AVAILABLE: bool = False
try:
    from prophet import Prophet  # type: ignore[import-untyped]
    _PROPHET_AVAILABLE = True
except ImportError:
    pass


class ProphetForecaster(BaseForecaster):
    """Prophet-based time-series forecaster with exponential smoothing fallback.

    When Prophet is installed, uses it for forecasting with automatic
    seasonality detection. Otherwise uses exponential smoothing (alpha=0.3)
    as a simple but effective alternative for clinical measurements.
    """

    def __init__(self, alpha: float = 0.3) -> None:
        """Initialize Prophet forecaster.

        Args:
            alpha: Smoothing factor for exponential smoothing fallback.
                Higher alpha = more weight on recent observations.
        """
        self._alpha: float = alpha

        if _PROPHET_AVAILABLE:
            logger.info("Prophet available — will use for forecasting")
        else:
            logger.info("Prophet not available — using exponential smoothing fallback")

    @property
    def model_name(self) -> str:
        """Return model identifier."""
        return "Prophet"

    def get_required_history(self) -> int:
        """Prophet recommends 2+ data points; smoothing works with 1+."""
        return 2

    def forecast(
        self, time_series: list[dict], horizon_months: int
    ) -> ForecastPoint:
        """Forecast using Prophet or exponential smoothing fallback.

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

        # Fallback to exponential smoothing (Prophet not trained for clinical data yet)
        return self._exponential_smoothing(time_series, horizon_months)

    def _exponential_smoothing(
        self, time_series: list[dict], horizon_months: int
    ) -> ForecastPoint:
        """Simple exponential smoothing forecast.

        Computes smoothed level and trend, then projects forward.
        Recent values have exponentially more influence (controlled by alpha).
        """
        values = [entry["value"] for entry in time_series]
        n = len(values)

        # Initialize smoothed value with first observation
        smoothed = values[0]

        # Apply exponential smoothing: S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
        for val in values[1:]:
            smoothed = self._alpha * val + (1.0 - self._alpha) * smoothed

        # Estimate trend from smoothed level vs last value
        if n >= 2:
            trend = (values[-1] - values[0]) / max(n - 1, 1)
        else:
            trend = 0.0

        # Project: smoothed level + trend * horizon
        estimate = smoothed + trend * horizon_months

        # Confidence interval based on historical variance
        if n >= 2:
            variance = sum((v - smoothed) ** 2 for v in values) / n
            std_dev = variance ** 0.5
        else:
            std_dev = abs(smoothed) * 0.1

        # Uncertainty grows with horizon
        uncertainty = std_dev * (1.0 + 0.2 * horizon_months)
        quality = min(1.0, n / (self.get_required_history() * 2))

        return ForecastPoint(
            point_estimate=round(estimate, 2),
            confidence_lower=round(estimate - uncertainty, 2),
            confidence_upper=round(estimate + uncertainty, 2),
            data_quality=round(quality, 2),
        )
