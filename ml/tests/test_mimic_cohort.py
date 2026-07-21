"""
Unit tests for MIMIC-IV cohort extraction (labelling + selection).

All data is synthetic and MIMIC-IV-shaped — no PHI, no dependency on the AWS
data box. These tests lock in the correctness of the label logic and cohort
gates BEFORE the pipeline is ever run against the 364k-patient dataset, per the
statistical-discipline rule.
"""

from __future__ import annotations

import pandas as pd

from ml.training.config.config import TARGET_DISEASES
from ml.training.data.disease_labels import (
    assign_disease_labels,
    icd9_diagnosis_count,
    label_icd_code,
)
from ml.training.data.mimic_cohort import build_cohort


def _diagnoses(rows: list[tuple[int, str, int]]) -> pd.DataFrame:
    """Build a diagnoses_icd-shaped frame from (subject_id, icd_code, version)."""
    return pd.DataFrame(rows, columns=["subject_id", "icd_code", "icd_version"])


# =============================================================================
# label_icd_code — single-code prefix matching
# =============================================================================


def test_stroke_code_maps_to_stroke() -> None:
    """I63x (cerebral infarction) must map to the stroke disease label."""
    assert label_icd_code("I639") == {"stroke"}


def test_diabetes_code_maps_to_diabetes() -> None:
    """E11x (type 2 diabetes) must map to the diabetes label."""
    assert label_icd_code("E119") == {"diabetes"}


def test_unrelated_code_maps_to_nothing() -> None:
    """A code outside all target prefixes must map to an empty set."""
    assert label_icd_code("Z000") == set()


def test_label_is_case_insensitive_and_trimmed() -> None:
    """Lowercase/whitespace codes still match (defensive against dirty input)."""
    assert label_icd_code(" i639 ") == {"stroke"}


# =============================================================================
# assign_disease_labels — per-subject matrix
# =============================================================================


def test_icd9_rows_are_excluded_from_labelling() -> None:
    """ICD-9 rows must not be labelled (config prefixes are ICD-10 only)."""
    diagnoses = _diagnoses([(1, "43491", 9), (1, "I639", 10)])
    labels = assign_disease_labels(diagnoses)
    # Subject 1 is stroke-positive from the ICD-10 row, not the ICD-9 one.
    assert bool(labels.at[1, "stroke"]) is True


def test_icd9_count_is_reported() -> None:
    """The excluded ICD-9 fraction is measurable, not silently dropped."""
    diagnoses = _diagnoses([(1, "43491", 9), (2, "I639", 10), (3, "25000", 9)])
    assert icd9_diagnosis_count(diagnoses) == 2


def test_coded_but_negative_subject_is_all_false() -> None:
    """A subject with only non-target ICD-10 codes appears with all-False labels."""
    diagnoses = _diagnoses([(7, "Z000", 10)])
    labels = assign_disease_labels(diagnoses)
    assert 7 in labels.index
    assert not labels.loc[7].any()


def test_multiple_diseases_per_subject() -> None:
    """A subject with stroke + diabetes codes is positive for both."""
    diagnoses = _diagnoses([(5, "I639", 10), (5, "E119", 10)])
    labels = assign_disease_labels(diagnoses)
    assert bool(labels.at[5, "stroke"]) is True
    assert bool(labels.at[5, "diabetes"]) is True


# =============================================================================
# build_cohort — selection + join
# =============================================================================


def test_build_cohort_applies_age_gate() -> None:
    """Patients below min_age are excluded from the cohort."""
    patients = pd.DataFrame(
        {"subject_id": [1, 2], "gender": ["F", "M"], "anchor_age": [17, 40]}
    )
    diagnoses = _diagnoses([(2, "I639", 10)])
    cohort = build_cohort(patients, diagnoses, min_age=18)

    assert list(cohort["subject_id"]) == [2]
    assert bool(cohort.loc[0, "stroke"]) is True


def test_build_cohort_retains_undiagnosed_as_negatives() -> None:
    """An eligible patient with no diagnoses is kept with all-False labels."""
    patients = pd.DataFrame(
        {"subject_id": [9], "gender": ["M"], "anchor_age": [55]}
    )
    diagnoses = _diagnoses([])  # empty
    cohort = build_cohort(patients, diagnoses)

    assert list(cohort["subject_id"]) == [9]
    for disease in TARGET_DISEASES:
        assert bool(cohort.loc[0, disease]) is False


def test_build_cohort_has_expected_columns() -> None:
    """Cohort exposes subject_id, age, gender, and every target disease column."""
    patients = pd.DataFrame(
        {"subject_id": [1], "gender": ["F"], "anchor_age": [60]}
    )
    diagnoses = _diagnoses([(1, "N189", 10)])
    cohort = build_cohort(patients, diagnoses)

    expected = {"subject_id", "age", "gender", *TARGET_DISEASES}
    assert set(cohort.columns) == expected
    assert bool(cohort.loc[0, "ckd"]) is True
