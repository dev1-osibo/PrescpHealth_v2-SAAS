"""
Unit tests for derived clinical features (BMI, eGFR via CKD-EPI 2021).

Synthetic data only — no PHI. These lock in the equations and their NaN-safety.
The eGFR expected values are hand-computed from the published CKD-EPI 2021
formula so a coefficient typo would be caught.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ml.training.features.derived import add_derived_features, compute_bmi, compute_egfr


def test_bmi_basic() -> None:
    """90 kg at 180 cm -> 27.78 BMI."""
    assert abs(compute_bmi(90.0, 180.0) - 27.7777) < 1e-3


def test_bmi_missing_or_bad_inputs_are_nan() -> None:
    """Missing weight/height or non-positive height yields NaN, not an error."""
    assert math.isnan(compute_bmi(None, 180.0))
    assert math.isnan(compute_bmi(90.0, 0.0))


def test_egfr_male_reference_value() -> None:
    """CKD-EPI 2021, male, creatinine 1.0 mg/dL, age 40 -> ~97.6 mL/min/1.73m^2."""
    egfr = compute_egfr(1.0, 40.0, "M")
    assert abs(egfr - 97.6) < 0.5


def test_egfr_female_lower_than_male_at_same_creatinine() -> None:
    """At identical creatinine/age, CKD-EPI gives females a LOWER eGFR.

    This is clinically correct: κ=0.7 (female) vs 0.9 (male) means a given
    creatinine reflects relatively worse function in a female (lower typical
    muscle mass), so eGFR is lower — despite the 1.012 female multiplier.
    """
    male = compute_egfr(1.0, 40.0, "M")
    female = compute_egfr(1.0, 40.0, "F")
    assert female < male


def test_egfr_missing_inputs_are_nan() -> None:
    """Missing or invalid inputs yield NaN."""
    assert math.isnan(compute_egfr(None, 40.0, "M"))
    assert math.isnan(compute_egfr(0.0, 40.0, "M"))


def test_add_derived_features_frame() -> None:
    """Frame adder computes bmi + egfr and NaN-propagates for missing rows."""
    frame = pd.DataFrame(
        {
            "weight": [90.0, np.nan],
            "height": [180.0, 170.0],
            "creatinine": [1.0, np.nan],
            "age": [40.0, 50.0],
            "gender": ["M", "F"],
        }
    )
    out = add_derived_features(frame)

    # Row 0: full inputs → real values.
    assert abs(out.loc[0, "bmi"] - 27.7777) < 1e-3
    assert abs(out.loc[0, "egfr"] - 97.6) < 0.5
    # Row 1: missing weight → bmi NaN; missing creatinine → egfr NaN.
    assert pd.isna(out.loc[1, "bmi"])
    assert pd.isna(out.loc[1, "egfr"])


def test_add_derived_features_missing_input_columns() -> None:
    """If raw input columns are absent entirely, derived columns are all-NaN."""
    frame = pd.DataFrame({"age": [40.0], "gender": ["M"]})  # no weight/height/creatinine
    out = add_derived_features(frame)
    assert "bmi" in out.columns and "egfr" in out.columns
    assert pd.isna(out.loc[0, "bmi"])
    assert pd.isna(out.loc[0, "egfr"])
