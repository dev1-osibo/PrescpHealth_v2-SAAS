"""
ICD-10 → 6-disease label assignment for the MIMIC-IV training cohort.

Turns raw `diagnoses_icd` rows into a per-patient binary label matrix for the
six PrescpHealth target diseases. A patient is positive for a disease if ANY of
their diagnosis codes starts with one of that disease's ICD-10 prefixes
(config.DISEASE_ICD10_CODES).

IMPORTANT correctness note (ICD-9 vs ICD-10):
    MIMIC-IV mixes ICD-9 and ICD-10 coded diagnoses (`icd_version` column).
    The prefix map in config is ICD-10 ONLY. We therefore label using
    icd_version == 10 rows and DELIBERATELY DO NOT guess ICD-9 equivalents here.
    `icd9_diagnosis_count()` exposes how many rows are being excluded so the gap
    is measured and visible, not silently hidden — per the statistical-discipline
    rule in docs/ml/dataset-roles-and-validation.md. ICD-9 cross-walking is a
    tracked follow-up, not a silent assumption.
"""

from __future__ import annotations

import pandas as pd

from ml.training.config.config import DISEASE_ICD10_CODES, TARGET_DISEASES

# ICD versions as encoded in MIMIC-IV's diagnoses_icd.icd_version column.
ICD_VERSION_9: int = 9
ICD_VERSION_10: int = 10


def label_icd_code(icd_code: str) -> set[str]:
    """Return the set of target diseases a single ICD-10 code maps to.

    Matching is by prefix on the dot-less code as stored in MIMIC-IV
    (e.g., "I639" matches the "I63" stroke prefix). A code can map to multiple
    diseases only if prefixes overlap (they do not in the current config), but
    the set return type keeps the contract robust to future config changes.

    Args:
        icd_code: A single ICD-10 diagnosis code (dot-less), case-insensitive.

    Returns:
        Set of disease identifiers this code belongs to (possibly empty).
    """
    if not icd_code:
        return set()
    code = str(icd_code).strip().upper()
    matched: set[str] = set()
    for disease, spec in DISEASE_ICD10_CODES.items():
        for prefix in spec["prefix"]:
            if code.startswith(prefix.upper()):
                matched.add(disease)
                break
    return matched


def icd9_diagnosis_count(diagnoses: pd.DataFrame) -> int:
    """Count ICD-9 diagnosis rows being excluded from labelling.

    Used for reporting/verification so the excluded fraction is explicit.

    Args:
        diagnoses: Frame with an `icd_version` column.

    Returns:
        Number of rows where icd_version == 9.
    """
    if "icd_version" not in diagnoses.columns:
        return 0
    return int((diagnoses["icd_version"] == ICD_VERSION_9).sum())


def assign_disease_labels(diagnoses: pd.DataFrame) -> pd.DataFrame:
    """Build a per-subject binary disease-label matrix from ICD-10 diagnoses.

    Args:
        diagnoses: MIMIC-IV `diagnoses_icd`-shaped frame with at least
            `subject_id`, `icd_code`, and `icd_version` columns.

    Returns:
        DataFrame indexed by `subject_id` with one boolean column per target
        disease (in config.TARGET_DISEASES order). Only subjects that have at
        least one ICD-10 diagnosis row appear. Subjects with ICD-10 rows but no
        matching prefix appear with all-False labels (true negatives).

    Raises:
        KeyError: If required columns are missing (fail loud, not silent).
    """
    required = {"subject_id", "icd_code", "icd_version"}
    missing = required - set(diagnoses.columns)
    if missing:
        raise KeyError(f"diagnoses frame missing required columns: {sorted(missing)}")

    icd10 = diagnoses[diagnoses["icd_version"] == ICD_VERSION_10]

    # Accumulate per-subject disease flags. Start every subject that has any
    # ICD-10 row at all-False so "coded but negative" is distinguishable from
    # "never appeared".
    subjects = icd10["subject_id"].unique()
    labels = pd.DataFrame(
        False, index=pd.Index(subjects, name="subject_id"), columns=list(TARGET_DISEASES)
    )

    for subject_id, code in zip(icd10["subject_id"], icd10["icd_code"], strict=False):
        for disease in label_icd_code(code):
            labels.at[subject_id, disease] = True

    return labels
