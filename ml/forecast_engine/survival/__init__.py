"""
PrescpHealth Forecast Engine — Survival Analysis Sub-Package.

Implements survival/time-to-event models for predicting when adverse
health events may occur (not just IF they will occur, but WHEN).

Contains:
    - CoxPHModel: Cox Proportional Hazards (classical survival analysis)
    - DeepSurvModel: Neural network extension of Cox PH (PyTorch-based)

Both models share a common interface: predict_survival() and get_hazard_ratio().
"""

from __future__ import annotations

from ml.forecast_engine.survival.cox_ph import CoxPHModel
from ml.forecast_engine.survival.deepsurv import DeepSurvModel

__all__: list[str] = [
    "CoxPHModel",
    "DeepSurvModel",
]
