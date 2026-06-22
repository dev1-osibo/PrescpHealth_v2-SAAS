"""
PrescpHealth Forecast Engine — Base Forecaster Interface.

Abstract base class that all forecasting models (TFT, LSTM, Prophet) implement.
Produces ForecastPoint dataclass instances with point estimates and confidence
intervals, ensuring a uniform output contract for the ensemble combiner.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastPoint:
    """A single forecast prediction with uncertainty bounds.

    Attributes:
        point_estimate: Best-guess predicted value at the forecast horizon.
        confidence_lower: Lower bound of the prediction interval (e.g., 5th percentile).
        confidence_upper: Upper bound of the prediction interval (e.g., 95th percentile).
        data_quality: Score in [0, 1] indicating how much data supported this forecast.
            1.0 = ample history, 0.0 = minimal data (extrapolation is unreliable).
    """

    point_estimate: float
    confidence_lower: float
    confidence_upper: float
    data_quality: float


class BaseForecaster(ABC):
    """Abstract interface for all time-series forecasting models.

    Each forecaster takes a series of historical measurements and produces
    a ForecastPoint at a specified horizon (months into the future).
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier (e.g., 'TFT', 'LSTM', 'Prophet')."""
        ...

    @abstractmethod
    def forecast(
        self, time_series: list[dict], horizon_months: int
    ) -> ForecastPoint:
        """Produce a forecast at the given horizon.

        Args:
            time_series: List of dicts with keys 'value' (float) and
                'recorded_at' (ISO date string). Ordered chronologically.
            horizon_months: How many months ahead to forecast.

        Returns:
            ForecastPoint with prediction and confidence bounds.
        """
        ...

    @abstractmethod
    def get_required_history(self) -> int:
        """Minimum number of data points needed for a meaningful forecast."""
        ...
