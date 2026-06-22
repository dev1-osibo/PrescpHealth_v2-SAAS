"""
PrescpHealth ML Engine — CatBoost Expert Model (Layer 2).

Concrete implementation of BaseExpertModel using Yandex's CatBoost.
CatBoost is particularly strong with categorical features (e.g., smoking_status,
medication_type, ethnicity) which are common in clinical data but poorly handled
by XGBoost/LightGBM without manual encoding.

Design decisions:
    - CatBoost natively handles categorical features — no one-hot encoding needed.
    - Same graceful degradation: (0.5, 0.0) when no model loaded.
    - Uses CatBoost's built-in prediction probability mode.

Patent context: Third expert in the Layer 2 ensemble. Diversity of model
architectures (XGBoost + LightGBM + CatBoost + Neural) improves ensemble
robustness via decorrelation of prediction errors.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ml.risk_engine.models.base_expert import BaseExpertModel

logger = logging.getLogger(__name__)

# Graceful import — CatBoost may not be installed in all environments
try:
    from catboost import CatBoostClassifier
    CATBOOST_AVAILABLE = True
except ImportError:
    CATBOOST_AVAILABLE = False


class CatBoostExpert(BaseExpertModel):
    """CatBoost-based expert model for disease risk prediction.

    Strongest when categorical features (smoking status, medication type,
    comorbidity codes) carry significant predictive signal. CatBoost's
    ordered target encoding avoids the target leakage that naive encoding
    introduces during cross-validation.
    """

    def __init__(self, disease_name: str = "unknown", version: str = "0.0.0") -> None:
        """Initialize expert with disease identity.

        Args:
            disease_name: Disease this expert predicts.
            version: Semantic version of the model artifact.
        """
        self._disease: str = disease_name
        self._version: str = version
        self._model: Any = None  # CatBoostClassifier when loaded
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

        Returns (0.5, 0.0) when no model is loaded — neutral prediction
        with zero confidence for safe pipeline operation without artifacts.
        """
        if self._model is None or not CATBOOST_AVAILABLE:
            return (0.5, 0.0)

        values = [features.get(f, np.nan) for f in self._feature_names]
        input_array = np.array([values], dtype=np.float64)
        # CatBoost predict_proba returns [[prob_class_0, prob_class_1]]
        proba = self._model.predict_proba(input_array)
        prob: float = float(proba[0][1])  # Probability of positive class (at-risk)
        confidence: float = min(1.0, abs(prob - 0.5) * 2.0)
        return (float(np.clip(prob, 0.0, 1.0)), confidence)

    def predict_batch(
        self, features_list: list[dict[str, float]]
    ) -> list[tuple[float, float]]:
        """Batch prediction using CatBoost's vectorized predict_proba."""
        if self._model is None or not CATBOOST_AVAILABLE:
            return [(0.5, 0.0)] * len(features_list)

        rows = [
            [f.get(name, np.nan) for name in self._feature_names]
            for f in features_list
        ]
        input_array = np.array(rows, dtype=np.float64)
        probas = self._model.predict_proba(input_array)
        results: list[tuple[float, float]] = []
        for proba_row in probas:
            prob = float(np.clip(proba_row[1], 0.0, 1.0))
            confidence = min(1.0, abs(prob - 0.5) * 2.0)
            results.append((prob, confidence))
        return results

    def get_feature_names(self) -> list[str]:
        """Return ordered feature names the model was trained on."""
        return list(self._feature_names)

    def load(self, artifact_path: str) -> None:
        """Load a trained CatBoost model from its native binary format."""
        if not CATBOOST_AVAILABLE:
            logger.warning("CatBoost not installed — cannot load model artifact")
            return
        path = Path(artifact_path)
        model_file = path / "model.cbm" if path.is_dir() else path
        if not model_file.exists():
            logger.warning("Model file not found at %s — using dummy predictions", model_file)
            return
        self._model = CatBoostClassifier()
        self._model.load_model(str(model_file))
        self._feature_names = self._model.feature_names_ or []
        logger.info("Loaded CatBoost model from %s", model_file)

    def save(self, artifact_path: str) -> None:
        """Save the current model to disk in CatBoost binary format."""
        if self._model is None or not CATBOOST_AVAILABLE:
            logger.warning("No model to save")
            return
        path = Path(artifact_path)
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "model.cbm"))
        logger.info("Saved CatBoost model to %s", path / "model.cbm")
