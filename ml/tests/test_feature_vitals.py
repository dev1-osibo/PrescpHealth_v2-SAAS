"""
Unit tests for vital-sign feature aggregation from MIMIC-IV chartevents.

Synthetic, MIMIC-shaped data only — no PHI. These lock in two correctness
properties that a naive groupby would get wrong:
    1. Most-recent (by charttime) value wins per subject/vital.
    2. Fahrenheit temperature is converted to Celsius before aggregation, so the
       "temperature" feature never mixes units.
"""

from __future__ import annotations

import pandas as pd

from ml.training.features.vitals import (
    TEMPERATURE_FAHRENHEIT_ITEMID,
    VITAL_FEATURE_COLUMNS,
    aggregate_vitals,
)

# Standard MIMIC-IV vital itemids used across these tests.
_HEART_RATE = 220045
_SYSTOLIC_BP = 220050
_TEMP_CELSIUS = 223762


def _chartevents(rows: list[tuple[int, int, str, float]]) -> pd.DataFrame:
    """Build a chartevents-shaped frame from (subject_id, itemid, charttime, valuenum)."""
    return pd.DataFrame(
        rows, columns=["subject_id", "itemid", "charttime", "valuenum"]
    )


def test_most_recent_value_wins() -> None:
    """For repeated readings, the latest charttime value is the feature value."""
    events = _chartevents(
        [
            (1, _HEART_RATE, "2150-01-01 08:00", 70.0),
            (1, _HEART_RATE, "2150-01-01 12:00", 95.0),  # later -> should win
            (1, _HEART_RATE, "2150-01-01 10:00", 80.0),
        ]
    )
    result = aggregate_vitals(events)
    assert result.at[1, "heart_rate"] == 95.0


def test_fahrenheit_temperature_converted_to_celsius() -> None:
    """A 98.6F reading must be aggregated as 37.0C, not left in Fahrenheit."""
    events = _chartevents(
        [(2, TEMPERATURE_FAHRENHEIT_ITEMID, "2150-02-01 09:00", 98.6)]
    )
    result = aggregate_vitals(events)
    assert abs(result.at[2, "temperature"] - 37.0) < 1e-6


def test_celsius_temperature_left_unchanged() -> None:
    """A native Celsius reading passes through without conversion."""
    events = _chartevents([(3, _TEMP_CELSIUS, "2150-02-01 09:00", 37.5)])
    result = aggregate_vitals(events)
    assert result.at[3, "temperature"] == 37.5


def test_unknown_itemids_are_ignored() -> None:
    """Itemids not in VITAL_ITEMIDS contribute no columns/values."""
    events = _chartevents(
        [
            (4, 999999, "2150-03-01 09:00", 123.0),  # unknown itemid
            (4, _SYSTOLIC_BP, "2150-03-01 09:00", 140.0),
        ]
    )
    result = aggregate_vitals(events)
    assert result.at[4, "systolic_bp"] == 140.0
    # The unknown reading did not create a spurious column.
    assert set(result.columns) == set(VITAL_FEATURE_COLUMNS)


def test_missing_vital_is_nan_not_dropped_column() -> None:
    """A subject missing a vital still yields the full stable column set (NaN)."""
    events = _chartevents([(5, _HEART_RATE, "2150-04-01 09:00", 60.0)])
    result = aggregate_vitals(events)
    assert list(result.columns) == VITAL_FEATURE_COLUMNS
    assert pd.isna(result.at[5, "systolic_bp"])


def test_empty_chartevents_returns_empty_schema() -> None:
    """No usable vitals -> empty frame with the stable vital column schema."""
    events = _chartevents([])
    result = aggregate_vitals(events)
    assert list(result.columns) == VITAL_FEATURE_COLUMNS
    assert len(result) == 0
