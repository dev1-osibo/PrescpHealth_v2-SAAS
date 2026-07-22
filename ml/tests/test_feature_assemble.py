"""
Unit tests for feature-matrix assembly (join + derive + filter + split).

Synthetic data only — no PHI. These validate that the four feature-engineering
steps compose into one training table with the right shape and no leakage.
"""

from __future__ import annotations

import pandas as pd

from ml.training.config.config import TARGET_DISEASES
from ml.training.features.assemble import (
    assemble_features,
    filter_by_vital_completeness,
    split_features_labels,
)


def _cohort() -> pd.DataFrame:
    """A 2-subject cohort with demographics + all six disease label columns."""
    data: dict = {"subject_id": [1, 2], "age": [65, 40], "gender": ["M", "F"]}
    for disease in TARGET_DISEASES:
        data[disease] = [False, False]
    data["ckd"] = [True, False]
    return pd.DataFrame(data)


def _vitals() -> pd.DataFrame:
    """Vitals for subject 1 only (subject 2 has none)."""
    df = pd.DataFrame(
        {"systolic_bp": [160.0], "weight": [90.0], "height": [180.0]}, index=[1]
    )
    df.index.name = "subject_id"
    return df


def _labs() -> pd.DataFrame:
    """Labs for subject 1 only."""
    df = pd.DataFrame({"creatinine": [1.0], "hba1c": [7.2]}, index=[1])
    df.index.name = "subject_id"
    return df


def test_assemble_joins_and_derives() -> None:
    """Assembled frame has demographics, vitals, labs, and derived bmi/egfr."""
    assembled = assemble_features(_cohort(), _vitals(), _labs())

    row = assembled[assembled["subject_id"] == 1].iloc[0]
    assert row["systolic_bp"] == 160.0
    assert row["creatinine"] == 1.0
    assert abs(row["bmi"] - 27.7777) < 1e-3
    # Male, creatinine 1.0, age 65 → eGFR in a plausible range.
    assert 80.0 < row["egfr"] < 100.0


def test_assemble_left_join_keeps_sparse_subject() -> None:
    """Subject 2 (no vitals/labs) is retained with NaN feature values."""
    assembled = assemble_features(_cohort(), _vitals(), _labs())
    row = assembled[assembled["subject_id"] == 2].iloc[0]
    assert pd.isna(row["systolic_bp"])
    assert pd.isna(row["bmi"])


def test_completeness_filter_drops_oversparse_subject() -> None:
    """A subject missing >max_missing_pct of vitals is dropped."""
    assembled = assemble_features(_cohort(), _vitals(), _labs())
    # Subject 2 has all vitals missing (fraction 1.0) → dropped at threshold 0.8.
    filtered = filter_by_vital_completeness(assembled, max_missing_pct=0.8)
    assert list(filtered["subject_id"]) == [1]


def test_split_features_labels_no_leakage() -> None:
    """y holds the disease columns; X excludes labels AND subject_id."""
    assembled = assemble_features(_cohort(), _vitals(), _labs())
    x, y = split_features_labels(assembled)

    assert set(y.columns) == set(TARGET_DISEASES)
    assert "subject_id" not in x.columns
    for disease in TARGET_DISEASES:
        assert disease not in x.columns
    # A real feature survives in X.
    assert "systolic_bp" in x.columns


def test_ckd_label_preserved_through_pipeline() -> None:
    """The positive CKD label on subject 1 survives assembly + split."""
    assembled = assemble_features(_cohort(), _vitals(), _labs())
    _, y = split_features_labels(assembled)
    subject1_idx = assembled.index[assembled["subject_id"] == 1][0]
    assert bool(y.loc[subject1_idx, "ckd"]) is True
