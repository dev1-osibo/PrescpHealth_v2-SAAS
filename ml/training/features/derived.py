"""
Derived clinical features — values computed from raw vitals/labs + demographics.

Two inference-schema features are not measured directly and must be derived:
    - `bmi`  : from weight (kg) + height (cm)
    - `egfr` : from serum creatinine + age + sex, via the CKD-EPI 2021 equation

CKD-EPI 2021 is the current race-free standard (the 2009 equation's race
coefficient was removed by NKF/ASN in 2021). Getting eGFR from creatinine here
(rather than expecting the lab to report it) matches how the live system will
also derive it, keeping train/inference consistent.

All functions degrade to NaN when inputs are missing, so a subject lacking the
raw inputs simply gets a NaN derived feature (handled downstream by imputation),
never a crash or a silently wrong number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# CKD-EPI 2021 coefficients, indexed by sex.
_CKD_EPI = {
    "female": {"kappa": 0.7, "alpha": -0.241, "sex_mult": 1.012},
    "male": {"kappa": 0.9, "alpha": -0.302, "sex_mult": 1.0},
}


def compute_bmi(weight_kg: float, height_cm: float) -> float:
    """Body Mass Index = weight(kg) / height(m)^2.

    Args:
        weight_kg: Weight in kilograms.
        height_cm: Height in centimetres.

    Returns:
        BMI, or NaN if either input is missing or height is non-positive.
    """
    if weight_kg is None or height_cm is None:
        return float("nan")
    if not np.isfinite(weight_kg) or not np.isfinite(height_cm) or height_cm <= 0:
        return float("nan")
    height_m = height_cm / 100.0
    return float(weight_kg / (height_m * height_m))


def compute_egfr(creatinine: float, age: float, sex: str) -> float:
    """Estimated GFR via CKD-EPI 2021 (race-free).

    Args:
        creatinine: Serum creatinine in mg/dL.
        age: Age in years.
        sex: 'M'/'F' (case-insensitive); anything starting with 'f' is female.

    Returns:
        eGFR in mL/min/1.73m^2, or NaN if any input is missing/invalid.
    """
    if creatinine is None or age is None or sex is None:
        return float("nan")
    if not np.isfinite(creatinine) or not np.isfinite(age) or creatinine <= 0:
        return float("nan")

    is_female = str(sex).strip().lower().startswith("f")
    coef = _CKD_EPI["female"] if is_female else _CKD_EPI["male"]
    ratio = creatinine / coef["kappa"]
    egfr = (
        142.0
        * min(ratio, 1.0) ** coef["alpha"]
        * max(ratio, 1.0) ** -1.200
        * 0.9938**age
        * coef["sex_mult"]
    )
    return float(egfr)


def add_derived_features(features: pd.DataFrame) -> pd.DataFrame:
    """Add `bmi` and `egfr` columns to an assembled per-subject feature frame.

    Vectorized (NaN-propagating) so it scales to the full cohort. Requires the
    raw inputs to already be present as columns; missing input columns yield
    all-NaN derived columns rather than an error, so the step is order-tolerant.

    Args:
        features: Per-subject frame that may contain `weight`, `height`,
            `creatinine`, `age`, and `gender` columns.

    Returns:
        The same frame with `bmi` and `egfr` columns added/overwritten.
    """
    out = features.copy()

    # --- BMI ---
    if {"weight", "height"}.issubset(out.columns):
        height_m = out["height"] / 100.0
        # Guard against divide-by-zero/negative heights → NaN.
        safe_height = height_m.where(height_m > 0)
        out["bmi"] = out["weight"] / (safe_height * safe_height)
    else:
        out["bmi"] = np.nan

    # --- eGFR (CKD-EPI 2021, vectorized) ---
    if {"creatinine", "age", "gender"}.issubset(out.columns):
        scr = out["creatinine"].where(out["creatinine"] > 0)
        age = out["age"]
        is_female = out["gender"].astype("string").str.lower().str.startswith("f")
        kappa = np.where(is_female, 0.7, 0.9)
        alpha = np.where(is_female, -0.241, -0.302)
        sex_mult = np.where(is_female, 1.012, 1.0)
        ratio = scr / kappa
        out["egfr"] = (
            142.0
            * np.minimum(ratio, 1.0) ** alpha
            * np.maximum(ratio, 1.0) ** -1.200
            * 0.9938**age
            * sex_mult
        )
    else:
        out["egfr"] = np.nan

    return out
