"""
PrescpHealth ML Training Pipeline.

Owns the offline path that turns credentialed clinical datasets into trained,
validated, per-disease ensemble artifacts that the inference engines
(ml/risk_engine, ml/forecast_engine) consume via the model registry.

This package is the product-side home for ML training, consolidated here on
2026-07-16 for clean separation from the (wound-down) research/patent workspace.

Training runs on the AWS training instance (98.90.192.78) where the datasets
reside; only code, configs, and (gitignored) artifacts live in this repo.
Raw credentialed data NEVER enters version control (see .gitignore DUA block).

Planned sub-packages (to build):
    config/           — dataset definitions (migrated, clean)
    cohort/           — per-disease cohort extraction from MIMIC-IV
    features/         — feature engineering + missingness masks
    tournament/       — train candidates x diseases, validate on eICU, weight
    manifest_builder/ — emit the registry manifest consumed at runtime
"""
