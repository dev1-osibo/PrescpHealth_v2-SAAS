"""
Vital-sign feature aggregation from MIMIC-IV chartevents.

Collapses a subject's time-series of vital measurements into ONE value per
vital, matching the single-value-per-feature shape the inference pipeline sees
(a live patient presents a current measurement, not a series). We take the most
recent (last by charttime) value per vital — the clinical analogue of "current".

Output column names are the VITAL_ITEMIDS keys (systolic_bp, diastolic_bp,
heart_rate, ...), which are exactly the inference-side feature names. This keeps
the train/inference feature contract aligned.

UNIT-SAFETY (why this module is not a trivial groupby):
    MIMIC-IV records temperature under TWO itemids — Fahrenheit (223761) and
    Celsius (223762) — both of which map to the single "temperature" feature.
    Averaging or mixing them without conversion would silently corrupt the
    feature. We convert Fahrenheit rows to Celsius BEFORE aggregation so the
    "temperature" column is unambiguously Celsius. This explicit handling is
    the statistical-discipline rule in action, not incidental.
"""

from __future__ import annotations

import pandas as pd

from ml.training.config.config import VITAL_ITEMIDS

# Invert VITAL_ITEMIDS (name -> [itemids]) into itemid -> name for fast mapping.
ITEMID_TO_VITAL: dict[int, str] = {
    itemid: name for name, itemids in VITAL_ITEMIDS.items() for itemid in itemids
}

# MIMIC-IV "Temperature Fahrenheit" itemid — its valuenum must be converted to
# Celsius so it can share the "temperature" feature with the Celsius itemid.
TEMPERATURE_FAHRENHEIT_ITEMID: int = 223761

# Ordered vital feature columns the aggregator always emits (missing => NaN),
# so the output schema is stable regardless of which vitals a subject has.
VITAL_FEATURE_COLUMNS: list[str] = list(VITAL_ITEMIDS.keys())

_REQUIRED_COLUMNS = {"subject_id", "itemid", "charttime", "valuenum"}


def _normalize_units(chartevents: pd.DataFrame) -> pd.DataFrame:
    """Convert Fahrenheit temperature rows to Celsius in a place-safe copy.

    Args:
        chartevents: Frame filtered to known vital itemids.

    Returns:
        A copy where valuenum for the Fahrenheit temperature itemid has been
        converted to Celsius; all other rows are untouched.
    """
    df = chartevents.copy()
    fahrenheit = df["itemid"] == TEMPERATURE_FAHRENHEIT_ITEMID
    # (F - 32) * 5/9 -> Celsius. Only touches Fahrenheit temperature rows.
    df.loc[fahrenheit, "valuenum"] = (df.loc[fahrenheit, "valuenum"] - 32.0) * 5.0 / 9.0
    return df


def aggregate_vitals(chartevents: pd.DataFrame) -> pd.DataFrame:
    """Aggregate chartevents vitals to one (most-recent) value per subject.

    Args:
        chartevents: MIMIC-IV `chartevents`-shaped frame with at least
            `subject_id`, `itemid`, `charttime`, and `valuenum` columns.

    Returns:
        DataFrame indexed by `subject_id` with one column per vital
        (VITAL_FEATURE_COLUMNS). Subjects appear if they have at least one
        recognized vital reading; vitals with no reading for a subject are NaN.

    Raises:
        KeyError: If required columns are missing (fail loud, not silent).
    """
    missing = _REQUIRED_COLUMNS - set(chartevents.columns)
    if missing:
        raise KeyError(f"chartevents frame missing required columns: {sorted(missing)}")

    # Keep only rows for vitals we care about, then convert units.
    known = chartevents[chartevents["itemid"].isin(ITEMID_TO_VITAL)].copy()
    known = _normalize_units(known)
    known["vital"] = known["itemid"].map(ITEMID_TO_VITAL)

    # Drop rows without a numeric value — they carry no aggregatable signal.
    known = known.dropna(subset=["valuenum"])

    if known.empty:
        # No usable vitals at all — return an empty, correctly-typed frame.
        empty = pd.DataFrame(columns=VITAL_FEATURE_COLUMNS)
        empty.index.name = "subject_id"
        return empty

    # Most-recent value per (subject, vital): sort by charttime, take the last.
    known = known.sort_values("charttime")
    last_values = known.groupby(["subject_id", "vital"])["valuenum"].last()

    # Long -> wide: one column per vital, one row per subject.
    wide = last_values.unstack("vital")

    # Guarantee a stable, complete column set (absent vitals become NaN columns).
    wide = wide.reindex(columns=VITAL_FEATURE_COLUMNS)
    wide.index.name = "subject_id"
    return wide
