"""
PrescpHealth ML Engine — XGBoost Expert Model (Layer 2).

Concrete implementation of BaseExpertModel using XGBoost gradient boosting.
This expert is disease-agnostic: it can predict ANY disease risk depending
on which trained artifact is loaded. The disease identity comes from the
artifact, not the code.

Design decisions:
    - Graceful degradation: if no model artifact is loaded, returns dummy
      predictions (0.5 probability, 0.0 confidence) so the full pipeline
      can run in development/testing without trained models.
    - Confidence estimation: uses prediction margin (distance from 0.5)
      as a proxy for confidence when no calibrated confidence model exists.
    - Batch prediction leverages XGBoost's native DMatrix vectorization.

Patent context: Part of the ensemble in Layer 2 that feeds into the
Disease Cascade Network (Layer 3) and Meta-Learner (Layer 4).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ml.risk_engine.models.base_expert import BaseExpertModel

logger = logging.getLogger(__name__)

# Graceful import — XGBoost may not be installed in all environments
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False


class XGBoostExpert(BaseExpertModel):
    """XGBoost-based expert model for disease risk prediction.

    Can predict any disease — identity determined by loaded artifact.
    Falls back to dummy predictions when no trained model is available,
    enabling the full pipeline to function during development.
    """

    def __init__(self, disease_name: str = "unknown", version: str = "0.0.0") -> None:
        """Initialize expert with disease identity and optional model loading.

        Args:
            disease_name: Disease this expert predicts (set from artifact metadata).
            version: Semantic version of the model artifact.
        """
        self._disease: str = disease_name
        self._version: str = version
        self._model: Any = None  # xgb.Booster when loaded
        self._feature_names: list[str] = []

    @property
    def disease(self) -> str:
        """Disease this expert predicts."""
        return self._disease

    @property
    def model_version(self) -> str:
        """Semantic version of the loaded model artifact."""
        return self._version

    def predict(self, features: dict[str, float]) -> tuple[float, float]:
        """Predict risk probability and confidence for a single patient.

        If no model is loaded, returns (0.5, 0.0) — neutral probability
        with zero confidence, signaling the meta-learner to rely on
        clinical standards instead.
        """
        if self._model is None or not XGBOOST_AVAILABLE:
            return (0.5, 0.0)

        # Build feature vector in expected order, defaulting missing to NaN
        values = [features.get(f, np.nan) for f in self._feature_names]
        dmatrix = xgb.DMatrix(
            np.array([values], dtype=np.float32),
            feature_names=self._feature_names,
        )
        prob: float = float(self._model.predict(dmatrix)[0])
        # Confidence proxy: distance from decision boundary (0.5)
        confidence: float = min(1.0, abs(prob - 0.5) * 2.0)
        return (np.clip(prob, 0.0, 1.0).item(), confidence)

    def predict_batch(
        self, features_list: list[dict[str, float]]
    ) -> list[tuple[float, float]]:
        """Batch prediction using XGBoost native vectorization."""
        if self._model is None or not XGBOOST_AVAILABLE:
            return [(0.5, 0.0)] * len(features_list)

        rows = [
            [f.get(name, np.nan) for name in self._feature_names]
            for f in features_list
        ]
        dmatrix = xgb.DMatrix(
            np.array(rows, dtype=np.float32),
            feature_names=self._feature_names,
        )
        probs = self._model.predict(dmatrix)
        results: list[tuple[float, float]] = []
        for p in probs:
            prob = float(np.clip(p, 0.0, 1.0))
            confidence = min(1.0, abs(prob - 0.5) * 2.0)
            results.append((prob, confidence))
        return results

    def get_feature_names(self) -> list[str]:
        """Return ordered feature names the model was trained on."""
        return list(self._feature_names)

    def load(self, artifact_path: str) -> None:
        """Load a trained XGBoost model from a .json or .ubj artifact."""
        if not XGBOOST_AVAILABLE:
            logger.warning("XGBoost not installed — cannot load model artifact")
            return
        path = Path(artifact_path)
        model_file = path / "model.json" if path.is_dir() else path
        if not model_file.exists():
            logger.warning("Model file not found at %s — using dummy predictions", model_file)
            return
        self._model = xgb.Booster()
        self._model.load_model(str(model_file))
        self._feature_names = self._model.feature_names or []
        logger.info("Loaded XGBoost model from %s", model_file)

    def save(self, artifact_path: str) -> None:
        """Save the current model to disk in JSON format."""
        if self._model is None or not XGBOOST_AVAILABLE:
            logger.warning("No model to save")
            return
        path = Path(artifact_path)
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "model.json"))
        logger.info("Saved XGBoost model to %s", path / "model.json")
