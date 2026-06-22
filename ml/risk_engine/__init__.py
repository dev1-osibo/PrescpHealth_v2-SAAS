"""
PrescpHealth ML Engine — Risk Engine Package.

This package implements the patent's 5-layer adaptive risk prediction system:
    Layer 1: Data Assessment (quality gating)
    Layer 1.5: Bayesian Imputation + Missingness Encoding (Patent Claim 6)
    Layer 2: Expert Models (XGBoost, LightGBM, CatBoost, Neural)
    Layer 3: Disease Cascade Network (Patent Claim 1)
    Layer 4: Adaptive Meta-Learner (Patent Claim 2)
    Layer 5a: SHAP + Counterfactual Explanations (Patent Claim 5)
    Layer 5b: Clinical Silence Engine (Patent Claim 7)

Supporting modules:
    Population Transfer (Patent Claim 3)
    Trajectory Retrieval (Patent Claim 4)

Public API:
    RiskOrchestrator — Main pipeline entry point (ties all layers together)
    DataAssessor — Layer 1 data quality scoring
    BaseExpertModel — Abstract interface for all disease expert models
"""

from __future__ import annotations

from ml.risk_engine.data_assessment import DataAssessor
from ml.risk_engine.models.base_expert import BaseExpertModel
from ml.risk_engine.orchestrator import RiskOrchestrator, RiskPredictionResult

__all__: list[str] = [
    "DataAssessor",
    "BaseExpertModel",
    "RiskOrchestrator",
    "RiskPredictionResult",
]
