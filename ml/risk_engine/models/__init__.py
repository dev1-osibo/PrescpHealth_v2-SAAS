"""
PrescpHealth ML Engine — Expert Models Package.

Contains disease-specific expert model implementations:
    - BaseExpertModel: Abstract interface all experts implement
    - XGBoostExpert: XGBoost gradient boosting expert
    - LightGBMExpert: LightGBM gradient boosting expert
    - CatBoostExpert: CatBoost gradient boosting expert
    - NeuralExpert: PyTorch feedforward neural network expert
"""

from __future__ import annotations

from ml.risk_engine.models.base_expert import BaseExpertModel
from ml.risk_engine.models.xgboost_expert import XGBoostExpert
from ml.risk_engine.models.lightgbm_expert import LightGBMExpert
from ml.risk_engine.models.catboost_expert import CatBoostExpert
from ml.risk_engine.models.neural_expert import NeuralExpert

__all__: list[str] = [
    "BaseExpertModel",
    "XGBoostExpert",
    "LightGBMExpert",
    "CatBoostExpert",
    "NeuralExpert",
]
