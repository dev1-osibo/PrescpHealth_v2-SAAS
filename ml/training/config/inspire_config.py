"""
INSPIRE dataset config — SECONDARY/supplementary validation (D005/D006).

PROVENANCE: migrated verbatim (2026-07-16) from research `ml_pipeline/inspire_config.py`.

INSPIRE is a perioperative (surgical) cohort from Seoul National University
Hospital, South Korea. Per D005/D006 it is a SECONDARY validation set only —
NOT a co-equal AUROC benchmark against eICU — because its population (all
surgical patients) differs from general-admission cohorts. Target NCDs appear
as comorbidities, not primary admission diagnoses.

INSPIRE's icd10_cm field is already truncated to 3 characters (dataset
anonymization), which matches our prefix length for all six diseases.
"""
from pathlib import Path

INSPIRE_BASE = Path("inspire_data/inspire-a-publicly-available-research-dataset-for-perioperative-medicine-1.4.2")
PROCESSED_DATA_DIR = Path("ml/training/processed/inspire")

DISEASE_ICD10_CODES = {
    "stroke": {
        "prefix": ["I60", "I61", "I62", "I63", "I64", "I65", "I66", "I67", "I68", "I69"],
        "description": "Cerebrovascular diseases (hemorrhagic + ischemic stroke)",
    },
    "cvd": {
        "prefix": ["I20", "I21", "I22", "I23", "I24", "I25"],
        "description": "Ischemic heart disease (angina, MI, chronic IHD)",
    },
    "diabetes": {
        "prefix": ["E10", "E11", "E12", "E13", "E14"],
        "description": "Diabetes mellitus (Type 1, Type 2, other)",
    },
    "ckd": {
        "prefix": ["N18", "N19"],
        "description": "Chronic kidney disease and unspecified kidney failure",
    },
    "hypertensive_crisis": {
        "prefix": ["I10", "I11", "I12", "I13", "I15", "I16"],
        "description": "Hypertensive diseases including hypertensive crisis",
    },
    "copd": {
        "prefix": ["J40", "J41", "J42", "J43", "J44", "J45", "J46", "J47"],
        "description": "Chronic lower respiratory diseases (COPD, asthma, bronchiectasis)",
    },
}

TARGET_DISEASES = list(DISEASE_ICD10_CODES.keys())

# INSPIRE is perioperative — most patients are NOT ICU patients, so the
# ">=24h ICU stay" filter from MIMIC-IV is NOT applied here. Age filter kept.
COHORT_CRITERIA = {"min_age": 18}
RANDOM_SEED = 42
