"""
PrescpHealth ML Engine — LightGBM Expert Model (Layer 2).

Concrete implementation of BaseExpertModel using Microsoft's LightGBM.
LightGBM excels on sparse clinical data (common in underserved settings where
many lab tests haven't been ordered) due to its native handling of missing values
and histogram-based binning.

Design decisions:
    - Same graceful degradation pattern as XGBoostExpert: returns (0.5, 0.0)
      when no model is loaded, letting the pipeline run without trained models.
    - LightGBM's built-in handling of NaN features means less imputation
      pressure on Layer 1 for this expert specifically.
    - Batch prediction uses numpy array input directly (LightGBM accepts it).

Patent context: Part of the multi-model ensemble in Layer 2. The Meta-Learner
(Layer 4) learns which expert to trust more per-patient based on data density.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ml.risk_engine.models.base_expert import BaseExpertModel

logger = logging.getLogger(__name__)

# Graceful import — LightGBM may not be installed in all environments
try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False


class LightGBMExpert(BaseExpertModel):
    """LightGBM-based expert model for disease risk prediction.

    Particularly strong when patient data is sparse — LightGBM handles
    missing features natively without requiring explicit imputation,
    making it valuable for patients in underserved settings with
    incomplete lab panels.
    """

    def __init__(self, disease_name: str = "unknown", version: str = "0.0.0") -> None:
        """Initialize expert with disease identity.

        Args:
            disease_name: Disease this expert predicts.
            version: Semantic version of the model artifact.
        """
        self._disease: str = disease_name
        self._version: str = version
        self._model: Any = None  # lgb.Booster when loaded
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

        Returns (0.5, 0.0) when no model loaded — neutral prediction with
        zero confidence tells meta-learner to ignore this expert's opinion.
        """
        if self._model is None or not LIGHTGBM_AVAILABLE:
            return (0.5, 0.0)

        values = [features.get(f, np.nan) for f in self._feature_names]
        input_array = np.array([values], dtype=np.float64)
        prob: float = float(self._model.predict(input_array)[0])
        # Confidence proxy: how far from the decision boundary
        confidence: float = min(1.0, abs(prob - 0.5) * 2.0)
        return (float(np.clip(prob, 0.0, 1.0)), confidence)

    def predict_batch(
        self, features_list: list[dict[str, float]]
    ) -> list[tuple[float, float]]:
        """Batch prediction using LightGBM's native array interface."""
        if self._model is None or not LIGHTGBM_AVAILABLE:
            return [(0.5, 0.0)] * len(features_list)

        rows = [
            [f.get(name, np.nan) for name in self._feature_names]
            for f in features_list
        ]
        input_array = np.array(rows, dtype=np.float64)
        probs = self._model.predict(input_array)
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
        """Load a trained LightGBM model from a text-format artifact."""
        if not LIGHTGBM_AVAILABLE:
            logger.warning("LightGBM not installed — cannot load model artifact")
            return
        path = Path(artifact_path)
        model_file = path / "model.txt" if path.is_dir() else path
        if not model_file.exists():
            logger.warning("Model file not found at %s — using dummy predictions", model_file)
            return
        self._model = lgb.Booster(model_file=str(model_file))
        self._feature_names = self._model.feature_name()
        logger.info("Loaded LightGBM model from %s", model_file)

    def save(self, artifact_path: str) -> None:
        """Save the current model to disk in LightGBM text format."""
        if self._model is None or not LIGHTGBM_AVAILABLE:
            logger.warning("No model to save")
            return
        path = Path(artifact_path)
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "model.txt"))
        logger.info("Saved LightGBM model to %s", path / "model.txt")
