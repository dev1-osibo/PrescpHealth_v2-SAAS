"""
PrescpHealth ML Engine — Forecast Engine Package.

Predicts future health trajectories and simulates interventions (Patent Claim 5).
This module extends the risk engine by projecting risk scores forward in time
and answering counterfactual questions: "What happens if the patient loses weight?"

Architecture:
    - Forecasting Models: TFT, LSTM, Prophet (ensemble)
    - Survival Analysis: Cox PH, DeepSurv
    - Ensemble Combiner: Weighted combination of forecaster outputs
    - Intervention Simulator: Counterfactual "what-if" analysis
    - Orchestrator: Ties all components into a single pipeline

Public API:
    ForecastOrchestrator — Main pipeline entry point
    ForecastResult — Structured output with per-target, per-horizon predictions
"""

from __future__ import annotations

from ml.forecast_engine.orchestrator import ForecastOrchestrator, ForecastResult

__all__: list[str] = [
    "ForecastOrchestrator",
    "ForecastResult",
]
