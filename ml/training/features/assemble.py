"""
Feature-matrix assembly — join cohort + vitals + labs + derived into one frame.

This is the final feature-engineering step: it produces the per-subject training
table where each row is a patient, columns are the inference-schema features
(vitals, labs, derived bmi/egfr) plus demographics, and the six disease columns
are the labels (y).

It also applies the `max_missing_vitals_pct` cohort criterion (subjects missing
too large a fraction of core vitals are excluded — they cannot be scored
reliably). The `min_icu_hours` criterion is NOT applied here: it needs the
`icustays` table and belongs in a separate ICU-stay filter step, kept out to
preserve this module's single responsibility.
"""

from __future__ import annotations

import pandas as pd

from ml.training.config.config import COHORT_CRITERIA, TARGET_DISEASES
from ml.training.features.derived import add_derived_features
from ml.training.features.vitals import VITAL_FEATURE_COLUMNS


def assemble_features(
    cohort: pd.DataFrame,
    vitals: pd.DataFrame,
    labs: pd.DataFrame,
) -> pd.DataFrame:
    """Join cohort demographics/labels with vitals + labs and add derived features.

    Args:
        cohort: Output of mimic_cohort.build_cohort — `subject_id`, `age`,
            `gender`, and one boolean column per target disease.
        vitals: Output of features.vitals.aggregate_vitals — indexed by subject_id.
        labs: Output of features.labs.aggregate_labs — indexed by subject_id.

    Returns:
        One row per cohort subject: demographics + vital features + lab features +
        derived (`bmi`, `egfr`) + the disease label columns. Subjects with no
        vital/lab rows keep NaN feature values (left join — the cohort is the
        spine, so undiagnosed/sparse patients are not dropped here).

    Raises:
        KeyError: If the cohort is missing `subject_id` (fail loud).
    """
    if "subject_id" not in cohort.columns:
        raise KeyError("cohort frame missing required column: subject_id")

    assembled = cohort.merge(vitals, how="left", left_on="subject_id", right_index=True)
    assembled = assembled.merge(labs, how="left", left_on="subject_id", right_index=True)

    # Derived features depend on joined vitals (weight/height) + labs (creatinine)
    # + demographics (age/gender), so they must be computed AFTER the joins.
    assembled = add_derived_features(assembled)
    return assembled


def filter_by_vital_completeness(
    assembled: pd.DataFrame, max_missing_pct: float | None = None
) -> pd.DataFrame:
    """Drop subjects missing more than `max_missing_pct` of the core vitals.

    Implements the `max_missing_vitals_pct` cohort criterion: a patient with
    almost no vitals cannot be scored reliably and would otherwise be carried
    entirely by imputation.

    Args:
        assembled: Frame from `assemble_features`.
        max_missing_pct: Max allowed fraction of missing core vitals (0-1).
            Defaults to config.COHORT_CRITERIA["max_missing_vitals_pct"].

    Returns:
        The frame with over-sparse subjects removed. Rows are not modified.
    """
    threshold = (
        COHORT_CRITERIA["max_missing_vitals_pct"]
        if max_missing_pct is None
        else max_missing_pct
    )

    # Fraction of the core vital columns that are missing, per subject.
    present_vitals = [c for c in VITAL_FEATURE_COLUMNS if c in assembled.columns]
    if not present_vitals:
        return assembled  # nothing to assess against; don't silently drop everyone

    missing_fraction = assembled[present_vitals].isna().mean(axis=1)
    keep = missing_fraction <= threshold
    return assembled[keep].reset_index(drop=True)


def split_features_labels(
    assembled: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split an assembled frame into feature matrix X and label matrix y.

    Args:
        assembled: Frame from `assemble_features` (post any filtering).

    Returns:
        (X, y) where y holds the six disease label columns and X holds everything
        else except `subject_id` (kept out of X so it can't leak as a feature).
    """
    label_cols = [c for c in TARGET_DISEASES if c in assembled.columns]
    y = assembled[label_cols].copy()
    x = assembled.drop(columns=label_cols + ["subject_id"], errors="ignore").copy()
    return x, y
