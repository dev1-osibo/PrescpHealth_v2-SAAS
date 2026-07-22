"""
PrescpHealth ML Training — Feature engineering subpackage.

Turns raw MIMIC-IV time-series (chartevents vitals, labevents labs) into a
per-subject feature matrix whose column names match the inference-time feature
schema (the keys of ml.risk_engine.imputation.POPULATION_PRIORS). Keeping the
training column names identical to the inference lookup keys is the contract
that lets a trained artifact actually score live patients.

Modules:
    vitals.py — aggregate chartevents vitals to one value per subject per vital

Design intent (same as data/): each step is pure and unit-tested against tiny
synthetic frames so correctness is verified before touching the real dataset.
"""
