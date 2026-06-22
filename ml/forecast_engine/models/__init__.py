"""
PrescpHealth Forecast Engine — Forecasting Models Sub-Package.

Contains time-series forecasting model implementations:
    - BaseForecaster: Abstract interface all forecasters implement
    - TFTForecaster: Temporal Fusion Transformer (stub with trend fallback)
    - LSTMForecaster: LSTM network (stub with linear regression fallback)
    - ProphetForecaster: Prophet wrapper (with exponential smoothing fallback)

All models produce ForecastPoint objects with point estimates and confidence intervals.
"""

from __future__ import annotations

from ml.forecast_engine.models.base_forecaster import BaseForecaster, ForecastPoint
from ml.forecast_engine.models.tft_forecaster import TFTForecaster
from ml.forecast_engine.models.lstm_forecaster import LSTMForecaster
from ml.forecast_engine.models.prophet_forecaster import ProphetForecaster

__all__: list[str] = [
    "BaseForecaster",
    "ForecastPoint",
    "TFTForecaster",
    "LSTMForecaster",
    "ProphetForecaster",
]
