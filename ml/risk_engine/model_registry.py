"""
PrescpHealth ML Engine — Risk Model Registry (artifact loading contract).

This module is the single source of truth for *how trained model artifacts are
discovered and loaded* into per-disease expert instances. It decouples the
orchestrator (which knows how to run the pipeline) from the filesystem layout
of trained artifacts (which changes as the training pipeline evolves).

Artifact directory layout (per disease, per expert architecture):

    <artifacts_root>/
        <disease>/
            metadata.json          # version + per-expert versions + metrics
            xgboost/model.json
            lightgbm/model.txt
            catboost/model.cbm
            neural/model.pt        # + meta.txt (feature names)

Design rationale:
    - Each expert already knows how to load its own artifact format (see the
      *_expert.py `load()` methods). The registry only decides WHICH directory
      to point each expert at, and reads the shared metadata for versioning.
    - When `artifacts_root` is None or a disease has no artifacts, the registry
      still returns fully-constructed expert instances. Untrained experts return
      (0.5, 0.0) — neutral probability, zero confidence — so the meta-learner
      (Layer 4) falls back to clinical standards. This preserves day-1 graceful
      degradation and keeps the pipeline runnable with zero trained models.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ml.risk_engine.models.base_expert import BaseExpertModel
from ml.risk_engine.models.catboost_expert import CatBoostExpert
from ml.risk_engine.models.lightgbm_expert import LightGBMExpert
from ml.risk_engine.models.neural_expert import NeuralExpert
from ml.risk_engine.models.xgboost_expert import XGBoostExpert

logger = logging.getLogger(__name__)

# Environment variable that lets deployments (Celery workers) point at a shared
# artifact store without code changes. Unset in dev/test → graceful degradation.
ARTIFACTS_ROOT_ENV: str = "PRESCP_ML_ARTIFACTS_ROOT"

# Ordered expert architectures that make up the risk ensemble. Order matters for
# reproducibility — the meta-learner averages over experts in this order.
# Maps the on-disk subdirectory name → the expert class that loads it.
EXPERT_CLASSES: dict[str, type[BaseExpertModel]] = {
    "xgboost": XGBoostExpert,
    "lightgbm": LightGBMExpert,
    "catboost": CatBoostExpert,
    "neural": NeuralExpert,
}


def resolve_artifacts_root(explicit: str | Path | None = None) -> Path | None:
    """Resolve the artifacts root from an explicit arg or environment variable.

    Args:
        explicit: Caller-provided root. Takes precedence over the environment.

    Returns:
        A Path if a root was configured (even if it does not yet exist on disk,
        so callers can log a clear warning), or None when no root is configured
        at all (the pure graceful-degradation case).
    """
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(ARTIFACTS_ROOT_ENV)
    return Path(env_value) if env_value else None


class RiskModelRegistry:
    """Builds per-disease expert ensembles, loading trained artifacts if present.

    A single registry instance is created by the orchestrator. It is cheap to
    construct and holds no heavyweight state — the expert instances it returns
    own their loaded models.
    """

    def __init__(self, artifacts_root: str | Path | None = None) -> None:
        """Initialize the registry.

        Args:
            artifacts_root: Root directory containing per-disease artifact
                folders. If None, falls back to the PRESCP_ML_ARTIFACTS_ROOT
                environment variable; if that is also unset, no artifacts are
                loaded and all experts run in graceful-degradation mode.
        """
        self._root: Path | None = resolve_artifacts_root(artifacts_root)
        if self._root is not None and not self._root.exists():
            # Configured but missing — likely a deployment misconfiguration.
            # Warn (no PHI) and continue in degradation mode rather than crash.
            logger.warning(
                "Risk artifacts root configured but not found: %s — "
                "experts will run untrained (clinical-standard fallback)",
                self._root,
            )

    def _read_metadata(self, disease: str) -> dict:
        """Read a disease's metadata.json, returning {} if absent or unreadable.

        Metadata is advisory (versions, metrics). Its absence must never break
        loading — untrained experts simply carry version "0.0.0".
        """
        if self._root is None:
            return {}
        meta_file = self._root / disease / "metadata.json"
        if not meta_file.exists():
            return {}
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read metadata for %s: %s", disease, exc)
            return {}

    def disease_version(self, disease: str) -> str:
        """Return the trained-model version for a disease, or '0.0.0' if untrained."""
        return str(self._read_metadata(disease).get("version", "0.0.0"))

    def has_trained_models(self, disease: str) -> bool:
        """Whether at least one expert artifact exists on disk for this disease.

        Used by cold-start logic to decide whether a tenant/disease is still
        relying on population priors versus locally-trained models.
        """
        if self._root is None:
            return False
        disease_dir = self._root / disease
        for etype in EXPERT_CLASSES:
            expert_dir = disease_dir / etype
            if expert_dir.is_dir() and any(expert_dir.iterdir()):
                return True
        return False

    def build_experts(self, disease: str) -> list[BaseExpertModel]:
        """Construct the ordered expert ensemble for a single disease.

        Each expert is instantiated bound to `disease` and, if a matching
        artifact directory exists, loaded from it. Missing artifacts leave the
        expert in its untrained (0.5, 0.0) state.

        Args:
            disease: Disease identifier (e.g., 'stroke') matching the artifact
                subdirectory name.

        Returns:
            Experts in the canonical EXPERT_CLASSES order.
        """
        metadata = self._read_metadata(disease)
        per_expert_versions: dict = metadata.get("experts", {})
        fallback_version: str = str(metadata.get("version", "0.0.0"))

        experts: list[BaseExpertModel] = []
        for etype, cls in EXPERT_CLASSES.items():
            version = str(per_expert_versions.get(etype, fallback_version))
            expert = cls(disease_name=disease, version=version)
            if self._root is not None:
                expert_dir = self._root / disease / etype
                if expert_dir.is_dir():
                    # Delegate format-specific loading to the expert itself.
                    expert.load(str(expert_dir))
            experts.append(expert)
        return experts
