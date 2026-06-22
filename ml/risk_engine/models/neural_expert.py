"""
PrescpHealth ML Engine — Neural Network Expert Model (Layer 2).

Concrete implementation of BaseExpertModel using a PyTorch feedforward network.
The neural expert captures non-linear feature interactions that gradient boosting
models may miss (e.g., complex drug-drug-disease three-way interactions).

Architecture: 3 hidden layers with ReLU activation + dropout for regularization.
    Input → 128 → 64 → 32 → 1 (sigmoid output for probability)

Design decisions:
    - If PyTorch is not available (e.g., lightweight deployment), gracefully
      degrades to dummy predictions (0.5, 0.0) — same pattern as other experts.
    - Network weights loaded from state_dict file (standard PyTorch serialization).
    - Dropout disabled at inference time via model.eval() for deterministic output.
    - Confidence estimated from output entropy: predictions near 0 or 1 are
      more confident than those near 0.5.

Patent context: Fourth expert in the Layer 2 ensemble. Neural networks
add architectural diversity — their failure modes are uncorrelated with
tree-based models, improving ensemble robustness.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ml.risk_engine.models.base_expert import BaseExpertModel

logger = logging.getLogger(__name__)

# Graceful import — PyTorch may not be installed in all environments
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


def _build_network(input_dim: int) -> Any:
    """Construct the feedforward network architecture.

    Architecture rationale:
        - 128→64→32 progressive narrowing forces the network to learn
          compressed representations of disease risk factors.
        - Dropout 0.3 prevents overfitting on small clinical datasets.
        - BatchNorm stabilizes training on heterogeneous feature scales.
    """
    if not TORCH_AVAILABLE:
        return None
    return nn.Sequential(
        nn.Linear(input_dim, 128),
        nn.BatchNorm1d(128),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(128, 64),
        nn.BatchNorm1d(64),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(64, 32),
        nn.ReLU(),
        nn.Linear(32, 1),
        nn.Sigmoid(),
    )


class NeuralExpert(BaseExpertModel):
    """PyTorch feedforward neural network expert for disease risk prediction.

    Captures complex non-linear interactions between clinical features.
    Gracefully degrades if PyTorch is unavailable — the pipeline continues
    with the remaining gradient boosting experts.
    """

    def __init__(self, disease_name: str = "unknown", version: str = "0.0.0") -> None:
        """Initialize neural expert.

        Args:
            disease_name: Disease this expert predicts.
            version: Semantic version of the model artifact.
        """
        self._disease: str = disease_name
        self._version: str = version
        self._model: Any = None  # nn.Sequential when loaded
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
        """Predict risk using the neural network.

        Returns (0.5, 0.0) when PyTorch unavailable or no model loaded.
        """
        if self._model is None or not TORCH_AVAILABLE:
            return (0.5, 0.0)

        values = [features.get(f, 0.0) for f in self._feature_names]
        tensor = torch.tensor([values], dtype=torch.float32)
        self._model.eval()
        with torch.no_grad():
            prob: float = float(self._model(tensor).item())
        prob = max(0.0, min(1.0, prob))
        confidence: float = min(1.0, abs(prob - 0.5) * 2.0)
        return (prob, confidence)

    def predict_batch(
        self, features_list: list[dict[str, float]]
    ) -> list[tuple[float, float]]:
        """Batch prediction using PyTorch tensor operations."""
        if self._model is None or not TORCH_AVAILABLE:
            return [(0.5, 0.0)] * len(features_list)

        rows = [[f.get(name, 0.0) for name in self._feature_names] for f in features_list]
        tensor = torch.tensor(rows, dtype=torch.float32)
        self._model.eval()
        with torch.no_grad():
            probs = self._model(tensor).squeeze(-1).tolist()
        results: list[tuple[float, float]] = []
        for p in probs if isinstance(probs, list) else [probs]:
            prob = max(0.0, min(1.0, float(p)))
            confidence = min(1.0, abs(prob - 0.5) * 2.0)
            results.append((prob, confidence))
        return results

    def get_feature_names(self) -> list[str]:
        """Return ordered feature names the model was trained on."""
        return list(self._feature_names)

    def load(self, artifact_path: str) -> None:
        """Load trained weights from a PyTorch state_dict file."""
        if not TORCH_AVAILABLE:
            logger.warning("PyTorch not installed — cannot load neural model")
            return
        path = Path(artifact_path)
        weights_file = path / "model.pt" if path.is_dir() else path
        meta_file = path / "meta.txt" if path.is_dir() else None
        if not weights_file.exists():
            logger.warning("Weights not found at %s — using dummy predictions", weights_file)
            return
        # Load feature names from metadata if available
        if meta_file and meta_file.exists():
            self._feature_names = meta_file.read_text().strip().split("\n")
        input_dim = len(self._feature_names) if self._feature_names else 10
        self._model = _build_network(input_dim)
        self._model.load_state_dict(torch.load(str(weights_file), weights_only=True))
        self._model.eval()
        logger.info("Loaded neural model from %s", weights_file)

    def save(self, artifact_path: str) -> None:
        """Save model weights and metadata to disk."""
        if self._model is None or not TORCH_AVAILABLE:
            logger.warning("No model to save")
            return
        path = Path(artifact_path)
        path.mkdir(parents=True, exist_ok=True)
        torch.save(self._model.state_dict(), str(path / "model.pt"))
        (path / "meta.txt").write_text("\n".join(self._feature_names))
        logger.info("Saved neural model to %s", path / "model.pt")
