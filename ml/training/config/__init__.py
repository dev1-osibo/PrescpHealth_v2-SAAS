"""
Training configuration package.

Migrated from the research workspace `ml_pipeline/` on 2026-07-16 for clean
separation — the product workspace now owns the ML build. These modules hold
verified-clean external facts (ICD-10 disease maps, MIMIC-IV item IDs, cohort
criteria, candidate-model list, NHANES variable mappings) that survived the
2026-07-05 statistical reset.

Modules:
    config          — MIMIC-IV (train + internal test) definitions
    eicu_config     — eICU (sole external performance validation)
    inspire_config  — INSPIRE (secondary/supplementary validation)
    nhanes_config   — NHANES (Bayesian priors + lifestyle EDA only, NOT validation)
"""
