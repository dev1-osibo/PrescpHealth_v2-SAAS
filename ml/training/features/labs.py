"""
Lab-result feature aggregation from MIMIC-IV labevents.

MIMIC stores labs in two tables:
    - `d_labitems`  : itemid -> human label (e.g., "Creatinine")
    - `labevents`   : one row per lab result (subject_id, itemid, charttime, valuenum)

This module resolves the labs we care about to their itemids, then collapses each
subject's lab history to ONE (most-recent) value per lab — matching the
single-value-per-feature shape the inference pipeline sees.

TRAIN/INFERENCE CONTRACT:
    Output columns are canonical inference feature names (keys of
    ml.risk_engine.imputation.POPULATION_PRIORS). We ONLY emit labs that map to
    such a feature, so a trained model never depends on a feature the live system
    cannot supply. Labs outside the schema (electrolytes, LFTs, etc.) are ignored
    here on purpose.

APPROXIMATION FLAGGED (discipline, not silence):
    MIMIC "Glucose" is a serum glucose, NOT necessarily fasting. We map it to the
    inference feature `fasting_glucose` because that is the schema key, but this
    is a documented approximation — a fasting flag is not available in the raw
    labevents. Revisit if a fasting-specific itemid is later incorporated.
"""

from __future__ import annotations

import pandas as pd

# MIMIC d_labitems.label (lowercased) -> canonical inference feature name.
# Multiple labels can map to one feature (assay/label variants across the DB).
LAB_FEATURE_MAP: dict[str, str] = {
    "glucose": "fasting_glucose",  # serum glucose used as fasting proxy (see module docstring)
    "hemoglobin a1c": "hba1c",
    "% hemoglobin a1c": "hba1c",
    "creatinine": "creatinine",
    "cholesterol, total": "cholesterol_total",
    "cholesterol total": "cholesterol_total",
    "hdl cholesterol": "cholesterol_hdl",
    "ldl calculated": "cholesterol_ldl",
    "ldl, calculated": "cholesterol_ldl",
}

# Stable, ordered output columns (the distinct canonical features above).
LAB_FEATURE_COLUMNS: list[str] = [
    "cholesterol_hdl",
    "cholesterol_ldl",
    "cholesterol_total",
    "creatinine",
    "fasting_glucose",
    "hba1c",
]

_DLABITEMS_REQUIRED = {"itemid", "label"}
_LABEVENTS_REQUIRED = {"subject_id", "itemid", "charttime", "valuenum"}


def resolve_lab_itemids(d_labitems: pd.DataFrame) -> dict[int, str]:
    """Map MIMIC lab itemids to canonical feature names via d_labitems labels.

    Args:
        d_labitems: MIMIC-IV `d_labitems`-shaped frame with `itemid` and `label`.

    Returns:
        Dict of itemid -> canonical feature name, for labs in LAB_FEATURE_MAP.
        Labels are matched case-insensitively and whitespace-trimmed.

    Raises:
        KeyError: If required columns are missing (fail loud, not silent).
    """
    missing = _DLABITEMS_REQUIRED - set(d_labitems.columns)
    if missing:
        raise KeyError(f"d_labitems frame missing required columns: {sorted(missing)}")

    mapping: dict[int, str] = {}
    for itemid, label in zip(d_labitems["itemid"], d_labitems["label"], strict=False):
        if label is None:
            continue
        feature = LAB_FEATURE_MAP.get(str(label).strip().lower())
        if feature is not None:
            mapping[int(itemid)] = feature
    return mapping


def aggregate_labs(
    labevents: pd.DataFrame, itemid_to_feature: dict[int, str]
) -> pd.DataFrame:
    """Aggregate labevents to one (most-recent) value per subject per lab feature.

    Args:
        labevents: MIMIC-IV `labevents`-shaped frame (see module docstring).
        itemid_to_feature: Mapping from `resolve_lab_itemids`.

    Returns:
        DataFrame indexed by `subject_id` with one column per LAB_FEATURE_COLUMNS.
        Subjects appear if they have at least one recognized lab result; labs with
        no result for a subject are NaN.

    Raises:
        KeyError: If required columns are missing.
    """
    missing = _LABEVENTS_REQUIRED - set(labevents.columns)
    if missing:
        raise KeyError(f"labevents frame missing required columns: {sorted(missing)}")

    known = labevents[labevents["itemid"].isin(itemid_to_feature)].copy()
    known["feature"] = known["itemid"].map(itemid_to_feature)
    known = known.dropna(subset=["valuenum"])

    if known.empty:
        empty = pd.DataFrame(columns=LAB_FEATURE_COLUMNS)
        empty.index.name = "subject_id"
        return empty

    # Most-recent value per (subject, feature): sort by charttime, take last.
    known = known.sort_values("charttime")
    last_values = known.groupby(["subject_id", "feature"])["valuenum"].last()

    wide = last_values.unstack("feature").reindex(columns=LAB_FEATURE_COLUMNS)
    wide.index.name = "subject_id"
    return wide


def aggregate_labs_from_tables(
    labevents: pd.DataFrame, d_labitems: pd.DataFrame
) -> pd.DataFrame:
    """Convenience: resolve itemids then aggregate in one call.

    Args:
        labevents: MIMIC-IV `labevents`-shaped frame.
        d_labitems: MIMIC-IV `d_labitems`-shaped frame.

    Returns:
        Per-subject lab feature matrix (see `aggregate_labs`).
    """
    return aggregate_labs(labevents, resolve_lab_itemids(d_labitems))
