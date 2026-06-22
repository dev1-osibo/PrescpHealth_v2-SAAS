"""
PrescpHealth Forecast Engine — Main Forecast Pipeline Orchestrator.

Top-level entry point that ties all forecast components together:
    - Time-series forecasters (TFT, LSTM, Prophet)
    - Ensemble combiner (weighted average + union CIs)
    - Survival analysis (Cox PH, DeepSurv)
    - Intervention simulator (counterfactual what-if analysis)

Pipeline for each target metric:
    measurements -> filter by target -> run 3 forecasters -> ensemble combine
    -> run survival models -> merge into ForecastResult at 3/6/12 month horizons

Usage:
    orchestrator = ForecastOrchestrator()
    result = orchestrator.predict(patient_features, measurements, targets)
    simulation = orchestrator.simulate_intervention(features, 'weight_loss', params)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ml.forecast_engine.ensemble import ForecastEnsemble
from ml.forecast_engine.models.base_forecaster import ForecastPoint
from ml.forecast_engine.models.lstm_forecaster import LSTMForecaster
from ml.forecast_engine.models.prophet_forecaster import ProphetForecaster
from ml.forecast_engine.models.tft_forecaster import TFTForecaster
from ml.forecast_engine.simulation import InterventionSimulator, SimulationResult
from ml.forecast_engine.survival.cox_ph import CoxPHModel
from ml.forecast_engine.survival.deepsurv import DeepSurvModel

logger = logging.getLogger(__name__)

# Standard horizons for all forecasts (months)
FORECAST_HORIZONS: list[int] = [3, 6, 12]


@dataclass
class ForecastResult:
    """Complete output of the forecast pipeline.

    Contains per-target, per-horizon predictions with confidence intervals
    and survival probabilities. Structured for easy consumption by the
    frontend risk dashboard and alert system.

    Attributes:
        forecasts: Nested dict — target -> horizon_months -> point_estimate.
        confidence_intervals: target -> horizon_months -> (lower, upper).
        survival_probabilities: target -> horizon_months -> survival_prob.
        data_quality: target -> quality score in [0, 1].
        computation_time_ms: How long the full pipeline took.
    """

    forecasts: dict[str, dict[int, float]] = field(default_factory=dict)
    confidence_intervals: dict[str, dict[int, tuple[float, float]]] = field(
        default_factory=dict
    )
    survival_probabilities: dict[str, dict[int, float]] = field(default_factory=dict)
    data_quality: dict[str, float] = field(default_factory=dict)
    computation_time_ms: float = 0.0

    def __repr__(self) -> str:
        """Human-readable forecast summary."""
        lines = [f"ForecastResult (computed in {self.computation_time_ms:.0f}ms):"]
        for target, horizons in self.forecasts.items():
            lines.append(f"  {target}:")
            for h, val in sorted(horizons.items()):
                ci = self.confidence_intervals.get(target, {}).get(h, (0, 0))
                surv = self.survival_probabilities.get(target, {}).get(h, 0)
                lines.append(
                    f"    {h}m: {val:.1f} "
                    f"[CI: {ci[0]:.1f} - {ci[1]:.1f}] "
                    f"(survival: {surv:.2f})"
                )
            quality = self.data_quality.get(target, 0.0)
            lines.append(f"    data_quality: {quality:.2f}")
        return "\n".join(lines)


class ForecastOrchestrator:
    """Main forecast pipeline — ties forecasters, ensemble, and survival together.

    For each requested target metric:
        1. Filters measurements to that target's time series
        2. Runs TFT + LSTM + Prophet forecasters at each horizon
        3. Combines via weighted ensemble
        4. Runs Cox PH + DeepSurv survival analysis
        5. Packages into ForecastResult

    Also provides intervention simulation via simulate_intervention().
    """

    def __init__(self) -> None:
        """Initialize all pipeline components."""
        # Forecasting models
        self._tft = TFTForecaster()
        self._lstm = LSTMForecaster()
        self._prophet = ProphetForecaster()

        # Ensemble combiner (equal weights until validation data available)
        self._ensemble = ForecastEnsemble()

        # Survival models
        self._cox_ph = CoxPHModel()
        self._deepsurv = DeepSurvModel()

        # Intervention simulator
        self._simulator = InterventionSimulator()

    def predict(
        self,
        patient_features: dict[str, Any],
        measurements: list[dict],
        targets: list[str],
    ) -> ForecastResult:
        """Run the full forecast pipeline for specified targets.

        Args:
            patient_features: Current patient feature dict.
            measurements: All historical measurements (will be filtered per target).
            targets: List of target metrics to forecast (e.g., ['systolic_bp']).

        Returns:
            ForecastResult with predictions at 3/6/12 month horizons per target.
        """
        start = time.perf_counter()
        result = ForecastResult()

        for target in targets:
            # Filter measurements to this target's time series
            target_series = [
                m for m in measurements if m.get("type") == target
            ]

            # Initialize per-target storage
            result.forecasts[target] = {}
            result.confidence_intervals[target] = {}
            result.survival_probabilities[target] = {}

            for horizon in FORECAST_HORIZONS:
                # Run all three forecasters
                tft_forecast = self._tft.forecast(target_series, horizon)
                lstm_forecast = self._lstm.forecast(target_series, horizon)
                prophet_forecast = self._prophet.forecast(target_series, horizon)

                # Ensemble combine the three predictions
                combined = self._ensemble.combine(
                    [tft_forecast, lstm_forecast, prophet_forecast]
                )

                # Store forecast values
                result.forecasts[target][horizon] = combined.point_estimate
                result.confidence_intervals[target][horizon] = (
                    combined.confidence_lower,
                    combined.confidence_upper,
                )

                # Survival analysis at this horizon
                survival_prob = self._compute_survival(patient_features, horizon)
                result.survival_probabilities[target][horizon] = round(
                    survival_prob, 4
                )

            # Data quality from ensemble (use last horizon's quality as representative)
            result.data_quality[target] = combined.data_quality

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        result.computation_time_ms = round(elapsed_ms, 2)

        logger.info(
            "Forecast completed",
            extra={"targets": targets, "duration_ms": result.computation_time_ms},
        )
        return result

    def simulate_intervention(
        self,
        patient_features: dict[str, Any],
        measurements: list[dict],
        intervention_type: str,
        parameters: dict[str, Any],
    ) -> SimulationResult:
        """Simulate a health intervention and compare to baseline trajectory.

        Args:
            patient_features: Current patient features.
            measurements: Historical measurements.
            intervention_type: Type of intervention to simulate.
            parameters: Intervention-specific parameters.

        Returns:
            SimulationResult with baseline vs. simulated deltas.
        """
        return self._simulator.simulate(
            patient_features=patient_features,
            measurements=measurements,
            intervention_type=intervention_type,
            parameters=parameters,
            forecast_engine=self,
        )

    def _compute_survival(
        self, features: dict[str, Any], horizon: int
    ) -> float:
        """Compute average survival probability from Cox PH and DeepSurv.

        Both models are run and their predictions averaged for robustness.
        """
        cox_survival = self._cox_ph.predict_survival(features, horizon)
        deep_survival = self._deepsurv.predict_survival(features, horizon)
        # Average of both survival models
        return (cox_survival + deep_survival) / 2.0
