"""
NHANES config — variable mappings and file locations.

PROVENANCE: migrated verbatim (2026-07-16) from research `ml_pipeline/nhanes_config.py`.

ROLE (D001, user-confirmed): NHANES is NOT a performance-validation dataset.
5 of 6 disease labels are self-reported (only CKD is lab-derived via eGFR).
Its use is lifestyle/social-determinant EDA + Bayesian prior construction for
the cold-start / population-transfer layer ONLY. Never report model AUROC
against NHANES labels.

Data location (verified on AWS training box 98.90.192.78, 2026-07-16):
/home/ubuntu/nhanes_data
"""
from pathlib import Path

NHANES_DIR = Path('/home/ubuntu/nhanes_data')
NHANES_PROCESSED = Path('/home/ubuntu/ml_pipeline/processed/nhanes')

# Survey cycles available (letter suffix -> years)
CYCLES = {
    'E': '2007-2008', 'F': '2009-2010', 'G': '2011-2012',
    'H': '2013-2014', 'I': '2015-2016', 'J': '2017-2018',
}

# File prefixes and what they contain
FILE_GROUPS = {
    'DEMO': 'Demographics (age, gender, race, income, education)',
    'BPX': 'Blood pressure examination',
    'BPQ': 'Blood pressure questionnaire (diagnosis, medication)',
    'BMX': 'Body measures (BMI, weight, height, waist circumference)',
    'GHB': 'Glycohemoglobin (HbA1c)',
    'GLU': 'Plasma fasting glucose',
    'TCHOL': 'Total cholesterol',
    'HDL': 'HDL cholesterol',
    'TRIGLY': 'Triglycerides and LDL',
    'ALB_CR': 'Albumin and creatinine (urine) - kidney function',
    'BIOPRO': 'Standard biochemistry profile (serum creatinine, BUN)',
    'CBC': 'Complete blood count',
    'DIQ': 'Diabetes questionnaire',
    'MCQ': 'Medical conditions questionnaire (CVD, stroke, etc.)',
    'SMQ': 'Smoking questionnaire',
    'RXQ_RX': 'Prescription medications',
}

DEMO_VARS = {
    'SEQN': 'respondent_id', 'RIAGENDR': 'gender', 'RIDAGEYR': 'age',
    'RIDRETH3': 'race_ethnicity', 'DMDEDUC2': 'education',
    'DMDMARTL': 'marital_status', 'INDHHIN2': 'household_income_category',
    'INDFMPIR': 'poverty_income_ratio', 'DMDHHSIZ': 'household_size',
}
BPX_VARS = {
    'SEQN': 'respondent_id', 'BPXSY1': 'systolic_bp_1', 'BPXDI1': 'diastolic_bp_1',
    'BPXSY2': 'systolic_bp_2', 'BPXDI2': 'diastolic_bp_2',
    'BPXSY3': 'systolic_bp_3', 'BPXDI3': 'diastolic_bp_3', 'BPXPLS': 'pulse',
}
BPQ_VARS = {
    'SEQN': 'respondent_id', 'BPQ020': 'told_high_bp',
    'BPQ040A': 'on_bp_medication', 'BPQ080': 'told_high_cholesterol',
}
BMX_VARS = {
    'SEQN': 'respondent_id', 'BMXWT': 'weight_kg', 'BMXHT': 'height_cm',
    'BMXBMI': 'bmi', 'BMXWAIST': 'waist_circumference_cm',
}
GHB_VARS = {'SEQN': 'respondent_id', 'LBXGH': 'hba1c'}
GLU_VARS = {'SEQN': 'respondent_id', 'LBXGLU': 'fasting_glucose'}
TCHOL_VARS = {'SEQN': 'respondent_id', 'LBXTC': 'total_cholesterol'}
HDL_VARS = {'SEQN': 'respondent_id', 'LBDHDD': 'hdl_cholesterol'}
TRIGLY_VARS = {'SEQN': 'respondent_id', 'LBXTR': 'triglycerides', 'LBDLDL': 'ldl_cholesterol'}
ALB_CR_VARS = {'SEQN': 'respondent_id', 'URXUMA': 'urine_albumin', 'URXUCR': 'urine_creatinine'}
BIOPRO_VARS = {
    'SEQN': 'respondent_id', 'LBXSCR': 'serum_creatinine', 'LBXSBU': 'blood_urea_nitrogen',
    'LBXSGL': 'serum_glucose', 'LBXSAL': 'serum_albumin',
    'LBXSKSI': 'serum_potassium', 'LBXSNASI': 'serum_sodium',
}
CBC_VARS = {
    'SEQN': 'respondent_id', 'LBXHGB': 'hemoglobin', 'LBXHCT': 'hematocrit',
    'LBXWBCSI': 'wbc_count', 'LBXPLTSI': 'platelet_count',
}
DIQ_VARS = {
    'SEQN': 'respondent_id', 'DIQ010': 'told_diabetes',
    'DIQ050': 'taking_insulin', 'DIQ070': 'taking_diabetic_pills',
}
MCQ_VARS = {
    'SEQN': 'respondent_id', 'MCQ160B': 'told_chf', 'MCQ160C': 'told_chd',
    'MCQ160D': 'told_angina', 'MCQ160E': 'told_heart_attack', 'MCQ160F': 'told_stroke',
    'MCQ160K': 'told_chronic_bronchitis', 'MCQ160O': 'told_copd_emphysema',
    'MCQ220': 'told_cancer', 'MCQ160L': 'told_liver_condition',
}
SMQ_VARS = {
    'SEQN': 'respondent_id', 'SMQ020': 'smoked_100_cigarettes', 'SMQ040': 'currently_smoke',
}

# Target NCDs mapped to MIMIC-IV disease definitions (self-reported — priors/EDA only)
NCD_MAPPING = {
    'stroke': 'told_stroke',
    'cvd': ['told_chf', 'told_chd', 'told_angina', 'told_heart_attack'],
    'diabetes': 'told_diabetes',
    'ckd': None,  # Derived from lab values (creatinine, albumin via eGFR)
    'hypertensive_crisis': 'told_high_bp',
    'copd': 'told_copd_emphysema',
}
