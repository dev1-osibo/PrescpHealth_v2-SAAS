"""
MIMIC-IV cohort construction — selection + label join → training frame.

Two layers, kept separate so the logic is testable without any files:
    - `build_cohort(patients, diagnoses)`  : PURE frame-in/frame-out logic
    - `load_table` / `load_and_build_cohort`: thin IO wrappers over CSV(.gz)

Cohort selection applies config.COHORT_CRITERIA (currently: min_age). ICU-hour
and missing-vitals criteria are applied downstream during feature building where
`icustays`/`chartevents` are available — they are intentionally NOT smuggled in
here to keep this step single-responsibility and independently verifiable.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ml.training.config.config import COHORT_CRITERIA, TARGET_DISEASES
from ml.training.data.disease_labels import assign_disease_labels
from ml.training.data.paths import hosp_dir

logger = logging.getLogger(__name__)


def build_cohort(
    patients: pd.DataFrame,
    diagnoses: pd.DataFrame,
    min_age: int | None = None,
) -> pd.DataFrame:
    """Build the labelled training cohort from patients + diagnoses frames.

    Args:
        patients: MIMIC-IV `patients`-shaped frame with `subject_id`, `gender`,
            and `anchor_age` columns.
        diagnoses: MIMIC-IV `diagnoses_icd`-shaped frame (see disease_labels).
        min_age: Minimum age (inclusive). Defaults to config.COHORT_CRITERIA.

    Returns:
        One row per eligible subject: `subject_id`, `age`, `gender`, and one
        boolean column per target disease. Eligible subjects with no matching
        ICD-10 diagnosis are retained as all-negative (true negatives), so the
        cohort is not silently biased toward diagnosed patients.

    Raises:
        KeyError: If required patient columns are missing (fail loud).
    """
    threshold = COHORT_CRITERIA["min_age"] if min_age is None else min_age

    required = {"subject_id", "gender", "anchor_age"}
    missing = required - set(patients.columns)
    if missing:
        raise KeyError(f"patients frame missing required columns: {sorted(missing)}")

    # --- Selection: age gate ---
    eligible = patients[patients["anchor_age"] >= threshold].copy()
    eligible = eligible.rename(columns={"anchor_age": "age"})
    cohort = eligible[["subject_id", "age", "gender"]].reset_index(drop=True)

    # --- Label join ---
    # assign_disease_labels indexes by subject_id; reset so it merges as a column.
    labels = assign_disease_labels(diagnoses).reset_index()
    cohort = cohort.merge(labels, how="left", on="subject_id")
    # Subjects with no ICD-10 diagnosis row → NaN after left join → true negatives.
    for disease in TARGET_DISEASES:
        cohort[disease] = cohort[disease].fillna(False).astype(bool)

    logger.info(
        "Cohort built",
        extra={
            "subject_count": int(len(cohort)),
            "min_age": int(threshold),
            "disease_count": len(TARGET_DISEASES),
        },
    )
    return cohort


def load_table(name: str, root: str | Path | None = None) -> pd.DataFrame:
    """Load a MIMIC-IV `hosp/` table, transparently handling .csv and .csv.gz.

    Args:
        name: Table name without extension (e.g., "patients", "diagnoses_icd").
        root: Optional MIMIC root override (see paths.resolve_mimic_root).

    Returns:
        The table as a DataFrame.

    Raises:
        FileNotFoundError: If neither a .csv nor .csv.gz file exists.
    """
    directory = hosp_dir(root)
    for filename in (f"{name}.csv.gz", f"{name}.csv"):
        candidate = directory / filename
        if candidate.exists():
            return pd.read_csv(candidate)
    raise FileNotFoundError(f"MIMIC table '{name}' not found in {directory} (.csv/.csv.gz)")


def load_and_build_cohort(root: str | Path | None = None) -> pd.DataFrame:
    """Convenience loader: read patients + diagnoses_icd and build the cohort.

    Args:
        root: Optional MIMIC root override.

    Returns:
        The labelled cohort frame (see `build_cohort`).
    """
    patients = load_table("patients", root)
    diagnoses = load_table("diagnoses_icd", root)
    return build_cohort(patients, diagnoses)
