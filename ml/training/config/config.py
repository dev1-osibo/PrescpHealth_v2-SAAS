"""
ML training config — MIMIC-IV cohort, disease definitions, feature mappings.

PROVENANCE: migrated verbatim (2026-07-16) from the research workspace
`ml_pipeline/config.py`. These definitions survived the 2026-07-05 statistical
reset as verified-clean external facts (ICD-10 maps, MIMIC-IV item IDs, cohort
criteria, candidate-model list) — see research DECISION_LOG.md reset banner.

PATH NOTE: the data paths below reflect the research-workspace layout. On the
AWS training instance (98.90.192.78, verified 2026-07-16) the data lives at
/home/ubuntu/mimic_data. Paths are reconciled to an env-driven base when the
training pipeline is wired — do not hardcode a single machine's layout.
"""
from pathlib import Path

# =============================================================================
# Data Paths (reconciled to AWS training box when pipeline is wired)
# =============================================================================
MIMIC_BASE = Path("mimic_iv_data/mimic-iv/mimic-iv-3.1")
MIMIC_HOSP = MIMIC_BASE / "hosp"
MIMIC_ICU = MIMIC_BASE / "icu"

PROCESSED_DATA_DIR = Path("ml/training/processed")

# =============================================================================
# Target Diseases and ICD-10 Code Mappings
# A patient has a disease if they have ANY of these ICD-10 code prefixes.
# These six diseases align exactly with ml/risk_engine cascade_network.DISEASE_NODES.
# =============================================================================
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

# =============================================================================
# Key Lab names (mapped to d_labitems item IDs during preprocessing)
# =============================================================================
KEY_LAB_NAMES = [
    "Glucose", "Hemoglobin A1c", "Creatinine", "BUN",
    "Potassium", "Sodium", "Chloride", "Bicarbonate",
    "Cholesterol, Total", "HDL Cholesterol", "LDL Calculated", "Triglycerides",
    "Troponin T", "Troponin I", "NT-proBNP", "BNP",
    "WBC", "Hemoglobin", "Hematocrit", "Platelets",
    "INR", "PT", "PTT",
    "Albumin", "Total Protein", "ALT", "AST",
    "Urea Nitrogen",
]

# =============================================================================
# Vital Signs from chartevents (itemid mappings — standard MIMIC-IV)
# =============================================================================
VITAL_ITEMIDS = {
    "heart_rate": [220045],
    "systolic_bp": [220050, 220179],       # Invasive + Non-invasive
    "diastolic_bp": [220051, 220180],      # Invasive + Non-invasive
    "mean_bp": [220052, 220181],
    "respiratory_rate": [220210, 224690],
    "temperature": [223761, 223762],       # Celsius + Fahrenheit
    "spo2": [220277],
    "weight": [224639, 226512],
    "height": [226730],
}

# =============================================================================
# Cohort Selection Criteria
# =============================================================================
COHORT_CRITERIA = {
    "min_age": 18,
    "min_admissions": 1,
    "min_icu_hours": 24,
    "max_missing_vitals_pct": 0.80,
}

# =============================================================================
# Model Training Config
# =============================================================================
RANDOM_SEED = 42
N_CV_FOLDS = 5
TEST_SIZE = 0.15
VAL_SIZE = 0.15

# Candidate models for the per-disease ensemble tournament.
# Option-3 robust ensemble (TabNet deferred, per product decision 2026-07-16).
CANDIDATE_MODELS = ["xgboost", "lightgbm", "catboost", "neural_net", "tft", "deepsurv"]

# Target diseases
TARGET_DISEASES = list(DISEASE_ICD10_CODES.keys())
