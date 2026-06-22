"""
PrescpHealth ML Engine — Base Expert Model Interface.

All disease-specific models (XGBoost for CVD, LightGBM for Stroke, etc.)
implement this interface. This enables the meta-learner (Layer 3) to treat all
experts uniformly regardless of their internal architecture.

Design rationale:
    - Uniform interface allows the meta-learner to iterate over experts generically
    - predict() returns BOTH probability AND calibrated confidence because the
      meta-learner needs confidence to weight expert opinions (Patent Claim 12)
    - get_feature_names() enables Layer 1 to know which features matter per disease
    - load/save enable hot-swapping model versions without downtime

Usage (future):
    class StrokeExpert(BaseExpertModel):
        @property
        def disease(self) -> str:
            return "stroke"
        ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseExpertModel(ABC):
    """Abstract base class for all disease-specific expert models.

    Each expert model is responsible for:
        1. Predicting risk probability for a single disease
        2. Providing a calibrated confidence score for its prediction
        3. Declaring which features it needs (for Layer 1 data assessment)
        4. Serialization/deserialization for deployment

    The meta-learner (Layer 3) orchestrates multiple experts and combines
    their outputs using learned attention weights.
    """

    @property
    @abstractmethod
    def disease(self) -> str:
        """Disease this expert predicts (e.g., 'stroke', 'cvd', 'diabetes')."""
        ...

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Semantic version of the trained model artifact (e.g., '1.2.0').

        Used for audit trail — every prediction is logged with the model
        version that produced it, enabling retrospective analysis if a
        model version is later found to have a systematic bias.
        """
        ...

    @abstractmethod
    def predict(self, features: dict[str, float]) -> tuple[float, float]:
        """Predict risk for a single patient.

        Args:
            features: Dict of feature_name -> value for this patient.
                      Missing features should be handled internally
                      (imputation or graceful degradation).

        Returns:
            Tuple of (risk_probability, calibrated_confidence):
                - risk_probability: float in [0.0, 1.0], raw predicted risk
                - calibrated_confidence: float in [0.0, 1.0], how much the
                  model trusts its own prediction (low when data is sparse
                  or patient is out-of-distribution)
        """
        ...

    @abstractmethod
    def predict_batch(
        self, features_list: list[dict[str, float]]
    ) -> list[tuple[float, float]]:
        """Batch prediction for multiple patients.

        More efficient than calling predict() in a loop because the
        underlying model (XGBoost/LightGBM) can vectorize the computation.

        Args:
            features_list: List of feature dicts, one per patient.

        Returns:
            List of (risk_probability, calibrated_confidence) tuples,
            one per patient in the same order as input.
        """
        ...

    @abstractmethod
    def get_feature_names(self) -> list[str]:
        """Return ordered list of feature names this model was trained on.

        Layer 1 (DataAssessor) uses this to compute per-disease completeness:
        it checks which of these features are available for a given patient.
        """
        ...

    @abstractmethod
    def load(self, artifact_path: str) -> None:
        """Load a trained model from disk.

        Args:
            artifact_path: Path to the serialized model artifact directory.
                          Each expert defines its own internal format.
        """
        ...

    @abstractmethod
    def save(self, artifact_path: str) -> None:
        """Save the trained model to disk.

        Args:
            artifact_path: Path where the model artifact should be written.
                          Must be deterministic — same model state produces
                          same artifact bytes (for reproducibility audits).
        """
        ...
