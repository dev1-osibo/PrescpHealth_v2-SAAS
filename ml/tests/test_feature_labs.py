"""
Unit tests for lab-result feature aggregation from MIMIC-IV labevents.

Synthetic, MIMIC-shaped data only — no PHI. These lock in:
    1. d_labitems label -> canonical feature resolution (case-insensitive).
    2. Most-recent value wins per subject/lab.
    3. Only inference-schema labs are emitted; others are ignored.
    4. Multiple itemids mapping to the same feature are unified.
"""

from __future__ import annotations

import pandas as pd

from ml.training.features.labs import (
    LAB_FEATURE_COLUMNS,
    aggregate_labs,
    aggregate_labs_from_tables,
    resolve_lab_itemids,
)


def _d_labitems(rows: list[tuple[int, str]]) -> pd.DataFrame:
    """Build a d_labitems-shaped frame from (itemid, label)."""
    return pd.DataFrame(rows, columns=["itemid", "label"])


def _labevents(rows: list[tuple[int, int, str, float]]) -> pd.DataFrame:
    """Build a labevents-shaped frame from (subject_id, itemid, charttime, valuenum)."""
    return pd.DataFrame(
        rows, columns=["subject_id", "itemid", "charttime", "valuenum"]
    )


def test_resolve_maps_known_labels_case_insensitively() -> None:
    """Known lab labels resolve to canonical features regardless of case/spacing."""
    items = _d_labitems([(50912, "Creatinine"), (50931, " GLUCOSE "), (99999, "Widget")])
    mapping = resolve_lab_itemids(items)
    assert mapping[50912] == "creatinine"
    assert mapping[50931] == "fasting_glucose"
    # Unknown lab is not mapped.
    assert 99999 not in mapping


def test_most_recent_lab_value_wins() -> None:
    """For repeated results, the latest charttime value is the feature value."""
    items = _d_labitems([(50912, "Creatinine")])
    events = _labevents(
        [
            (1, 50912, "2150-01-01 08:00", 1.2),
            (1, 50912, "2150-01-03 08:00", 2.4),  # later -> should win
            (1, 50912, "2150-01-02 08:00", 1.8),
        ]
    )
    result = aggregate_labs_from_tables(events, items)
    assert result.at[1, "creatinine"] == 2.4


def test_unknown_itemids_ignored_and_schema_stable() -> None:
    """Labs outside the inference schema contribute nothing; columns stay stable."""
    items = _d_labitems([(50912, "Creatinine"), (50971, "Potassium")])
    events = _labevents(
        [
            (2, 50912, "2150-02-01 09:00", 0.9),
            (2, 50971, "2150-02-01 09:00", 4.1),  # potassium not in schema
        ]
    )
    result = aggregate_labs_from_tables(events, items)
    assert result.at[2, "creatinine"] == 0.9
    assert list(result.columns) == LAB_FEATURE_COLUMNS
    assert "potassium" not in result.columns


def test_multiple_itemids_map_to_same_feature() -> None:
    """Two A1c label variants both feed the single hba1c feature."""
    items = _d_labitems([(50852, "Hemoglobin A1c"), (50854, "% Hemoglobin A1c")])
    mapping = resolve_lab_itemids(items)
    assert mapping[50852] == "hba1c" and mapping[50854] == "hba1c"
    # Latest across either itemid wins.
    events = _labevents(
        [
            (3, 50852, "2150-03-01 09:00", 6.1),
            (3, 50854, "2150-03-05 09:00", 7.2),  # later -> wins
        ]
    )
    result = aggregate_labs(events, mapping)
    assert result.at[3, "hba1c"] == 7.2


def test_missing_lab_is_nan() -> None:
    """A subject missing a lab still yields the full stable column set (NaN)."""
    items = _d_labitems([(50912, "Creatinine")])
    events = _labevents([(4, 50912, "2150-04-01 09:00", 1.0)])
    result = aggregate_labs_from_tables(events, items)
    assert pd.isna(result.at[4, "hba1c"])
    assert list(result.columns) == LAB_FEATURE_COLUMNS


def test_empty_labevents_returns_empty_schema() -> None:
    """No recognized labs -> empty frame with the stable lab column schema."""
    items = _d_labitems([(50912, "Creatinine")])
    result = aggregate_labs_from_tables(_labevents([]), items)
    assert list(result.columns) == LAB_FEATURE_COLUMNS
    assert len(result) == 0
