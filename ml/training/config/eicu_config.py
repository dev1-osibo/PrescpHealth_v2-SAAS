"""
eICU pipeline config — SOLE external performance-validation dataset (D001/D006).

PROVENANCE: migrated verbatim (2026-07-16) from research `ml_pipeline/eicu_config.py`.

eICU structure differs from MIMIC-IV:
- No hadm_id: the admission-like unit is `patientunitstayid` (one ICU stay).
- Patient identifier is `uniquepid` (a single patient can have multiple stays).
- diagnosis.csv icd9code field holds a comma-separated "ICD9, ICD10" pair
  (e.g. "486, J18.9"); the ICD-10 code is the second token when present.
- age field uses "> 89" for de-identified elderly patients.

Data location (verified on AWS training box 98.90.192.78, 2026-07-16):
/home/ubuntu/eicu_extracted/eicu-collaborative-research-database-2.0
"""
from pathlib import Path

EICU_BASE = Path("/home/ubuntu/eicu_extracted/eicu-collaborative-research-database-2.0")
PROCESSED_DATA_DIR = Path("/home/ubuntu/eicu_processed")

# Reused verbatim from config.py DISEASE_ICD10_CODES to keep cross-dataset
# comparisons valid (identical labels -> fair like-for-like benchmark).
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

COHORT_CRITERIA = {"min_age": 18}
RANDOM_SEED = 42
