"""
Unit tests for the Risk Model Registry and per-disease artifact loading.

These tests validate the artifact-loading CONTRACT (not model quality):
    - With no artifacts root, experts are built untrained and degrade gracefully.
    - With a real trained artifact on disk, the matching expert loads it and the
      orchestrator reports the trained version for that disease only.
    - Tenant/deployment cold-start signals (has_trained_models, disease_version)
      reflect on-disk reality.

All data is synthetic — no PHI. Models trained here are throwaway 3-round
boosters purely to exercise the load path.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xgboost as xgb

from ml.risk_engine.model_registry import (
    ARTIFACTS_ROOT_ENV,
    EXPERT_CLASSES,
    RiskModelRegistry,
    resolve_artifacts_root,
)
from ml.risk_engine.orchestrator import RiskOrchestrator

# Feature set the throwaway stroke model is trained on. Order is preserved by
# XGBoost and asserted after load to confirm the artifact was really read.
_STROKE_FEATURES: list[str] = ["age", "systolic_bp", "bmi"]


def _write_stroke_xgboost_artifact(root: Path, version: str = "1.0.0") -> None:
    """Train a tiny XGBoost model and lay it out as a registry artifact.

    Produces:
        <root>/stroke/xgboost/model.json
        <root>/stroke/metadata.json
    """
    rng = np.random.default_rng(42)
    features = rng.random((60, len(_STROKE_FEATURES)))
    # Simple separable label so the booster trains without warnings.
    labels = (features[:, 0] > 0.5).astype(int)
    dtrain = xgb.DMatrix(features, label=labels, feature_names=_STROKE_FEATURES)
    booster = xgb.train({"objective": "binary:logistic"}, dtrain, num_boost_round=3)

    artifact_dir = root / "stroke" / "xgboost"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(artifact_dir / "model.json"))

    metadata = root / "stroke" / "metadata.json"
    metadata.write_text(
        '{"version": "%s", "experts": {"xgboost": "%s"}}' % (version, version),
        encoding="utf-8",
    )


# =============================================================================
# resolve_artifacts_root
# =============================================================================


def test_resolve_prefers_explicit_over_env(monkeypatch) -> None:
    """An explicit path argument overrides the environment variable."""
    monkeypatch.setenv(ARTIFACTS_ROOT_ENV, "/from/env")
    assert resolve_artifacts_root("/explicit") == Path("/explicit")


def test_resolve_falls_back_to_env(monkeypatch) -> None:
    """When no explicit path is given, the environment variable is used."""
    monkeypatch.setenv(ARTIFACTS_ROOT_ENV, "/from/env")
    assert resolve_artifacts_root(None) == Path("/from/env")


def test_resolve_returns_none_when_unconfigured(monkeypatch) -> None:
    """No explicit path and no env var means no artifacts (degradation mode)."""
    monkeypatch.delenv(ARTIFACTS_ROOT_ENV, raising=False)
    assert resolve_artifacts_root(None) is None


# =============================================================================
# Graceful degradation (no artifacts)
# =============================================================================


def test_untrained_registry_builds_full_ensemble(monkeypatch) -> None:
    """With no root, every disease still gets the full ordered expert ensemble."""
    monkeypatch.delenv(ARTIFACTS_ROOT_ENV, raising=False)
    registry = RiskModelRegistry(None)
    experts = registry.build_experts("stroke")
    assert len(experts) == len(EXPERT_CLASSES)


def test_untrained_expert_returns_neutral_prediction(monkeypatch) -> None:
    """Untrained experts must return (0.5, 0.0) so the meta-learner falls back."""
    monkeypatch.delenv(ARTIFACTS_ROOT_ENV, raising=False)
    registry = RiskModelRegistry(None)
    xgb_expert = registry.build_experts("stroke")[0]
    assert xgb_expert.predict({"age": 60.0}) == (0.5, 0.0)
    assert xgb_expert.get_feature_names() == []


def test_untrained_disease_reports_zero_version(monkeypatch) -> None:
    """A disease with no artifacts reports version 0.0.0 and no trained models."""
    monkeypatch.delenv(ARTIFACTS_ROOT_ENV, raising=False)
    registry = RiskModelRegistry(None)
    assert registry.disease_version("stroke") == "0.0.0"
    assert registry.has_trained_models("stroke") is False


# =============================================================================
# Real artifact loading
# =============================================================================


def test_trained_artifact_is_loaded_into_matching_expert(tmp_path: Path) -> None:
    """The XGBoost expert loads a real on-disk artifact and exposes its features.

    Confirms the registry points the expert at the right directory and the
    expert's own load() actually read the booster (feature names round-trip).
    """
    _write_stroke_xgboost_artifact(tmp_path)
    registry = RiskModelRegistry(tmp_path)
    xgb_expert = registry.build_experts("stroke")[0]

    # Feature names come only from a successfully loaded booster.
    assert xgb_expert.get_feature_names() == _STROKE_FEATURES
    assert xgb_expert.model_version == "1.0.0"


def test_has_trained_models_reflects_disk_state(tmp_path: Path) -> None:
    """has_trained_models is True only for diseases with artifacts present."""
    _write_stroke_xgboost_artifact(tmp_path)
    registry = RiskModelRegistry(tmp_path)
    assert registry.has_trained_models("stroke") is True
    # No artifacts were written for cvd.
    assert registry.has_trained_models("cvd") is False


def test_orchestrator_reports_trained_version_per_disease(tmp_path: Path) -> None:
    """The orchestrator surfaces the trained version for the trained disease only."""
    _write_stroke_xgboost_artifact(tmp_path)
    orchestrator = RiskOrchestrator(artifacts_root=tmp_path)
    result = orchestrator.predict({"age": 65, "systolic_bp": 160, "bmi": 30}, [])

    assert result.model_versions["stroke"] == "1.0.0"
    # Untrained diseases still report 0.0.0 — no cross-disease leakage.
    assert result.model_versions["cvd"] == "0.0.0"
    # Pipeline still produces all six diseases with valid scores.
    assert len(result.diseases) == 6
    for disease_result in result.diseases.values():
        assert 0.0 <= disease_result.risk_score <= 1.0
