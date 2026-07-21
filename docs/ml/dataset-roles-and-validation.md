# ML Datasets, Roles & Validation Rules (Product-Side Reference)

**Consolidated:** 2026-07-16 into the product workspace for clean separation.
**Source of truth:** distilled from the research workspace `DECISION_LOG.md`
(entries D001, D005, D006) which is now being wound down. This file is the
authoritative reference for the product ML build going forward.

> Patent/paper are discontinued (2026-07-09). All ML work is product-only.
> "Patent Claim N" strings in `ml/` docstrings are legacy naming, not objectives.

---

## Datasets and their ROLES (non-negotiable)

| Dataset | Role | Labels | Notes |
|---|---|---|---|
| **MIMIC-IV 3.1** | **Train + internal test** | ICD-10 (clinical) | 364,627 patients. Temporal split by `anchor_year_group` bucket (exact dates not recoverable). On AWS box: `/home/ubuntu/mimic_data` (10 GB). |
| **eICU 2.0** | **SOLE external performance validation** | ICD-10 (clinical) | All AUROC/AUPRC/Brier/ECE/NRI numbers come from eICU only. ~200K stays, 208 US hospitals. On AWS box: `/home/ubuntu/eicu_extracted` (5.2 GB). |
| **INSPIRE 1.4.2** | **Secondary/supplementary validation** | ICD-10 (3-char) | Perioperative (surgical) cohort, South Korea. NOT a co-equal benchmark — population differs (NCDs appear as comorbidities). Generalizability checks only. |
| **NHANES** | **Bayesian priors + lifestyle EDA ONLY** | Self-reported (5/6) | NEVER report model performance against NHANES labels. Only CKD is lab-derived (eGFR). Feeds cold-start priors + social-determinant EDA. On AWS box: `/home/ubuntu/nhanes_data` (185 MB). |
| **WHO STEPS** | **Bayesian priors ONLY** | Self-reported | Cross-country prior input for cold-start. Not validation. |
| MIMIC-BR | Pending/maybe | ICD-10 | 3-year window — cross-sectional metrics only, NOT longitudinal/cascade timing. Access not confirmed. |
| Kaggle sets | **RETIRED** | — | No further use. |

### The core validation rule
**Performance metrics (discrimination, calibration) are reported on eICU only**,
because mixing self-reported labels (NHANES/WHO STEPS) with clinically-coded
labels (MIMIC-IV/eICU) in one table is an apples-to-oranges comparison a
reviewer would reject. Self-report label noise understates true model
performance for reasons unrelated to the model.

### Temporal-span scoping rule (D006)
- **Cross-sectional** claims (AUROC, calibration, NRI, DCA) are span-independent —
  reportable on any adequately-sized dataset (eICU's 2-year span is fine).
- **Longitudinal** claims (cascade velocity, multi-hop timing, temporal decay,
  multi-year progression) require MIMIC-IV's 15-year span. Do NOT attempt these
  on short-window datasets (eICU 2yr, MIMIC-BR 3yr).

---

## Disease targets (align exactly with `ml/risk_engine` DISEASE_NODES)

stroke, cvd, diabetes, ckd, hypertensive_crisis, copd — ICD-10 prefix maps in
`ml/training/config/config.py` (`DISEASE_ICD10_CODES`).

---

## Model / ensemble decisions (2026-07-16, product)

- **Robust weighted ensemble (Option B)** per disease — run all candidates,
  combine by validated per-(disease, model) weights. NOT single-winner.
- **Candidate set:** xgboost, lightgbm, catboost, neural_net, tft, deepsurv.
  **TabNet deferred** (marginal diversity over existing neural + TFT; addable
  later as a cheap tournament candidate if a disease underperforms).
- **Forecast ensemble:** tft, lstm, prophet (trajectory) + cox_ph, deepsurv
  (survival), also validated-weighted.
- Weight assignment: start with inverse-error weighting; upgrade to constrained
  stacking. Prune members failing a calibration/discrimination floor (ECE > 0.05)
  to weight 0. Validate the COMBINED ensemble's calibration, not just members.

---

## Statistical-discipline caution (learned the hard way)

The research EDA was reset on 2026-07-05 after three compounding statistical
bugs (OR/RR conflation; a chronological-ordering bug). All pre-reset numeric
findings are retired. **Rebuild the training/EDA pipeline with verification at
every step** (cohort counts, label logic, calibration) rather than rushing to
trained artifacts. The raw data and the ICD/schema configs were unaffected.

---

## Compute (verified 2026-07-16)

- **Training box `98.90.192.78`** — 8 vCPU, 15 GB RAM, 96 GB disk (63 GB free),
  **no GPU**, Python 3.12, Ubuntu 24.04. Data already staged here. Tree models
  train fine on CPU; TFT/DeepSurv/neural are CPU-bound (slower). Spin up a
  temporary GPU spot instance only if the deep-learning members prove necessary.
- **`98.87.133.69`** — Cortafy production box (2 core, 3.7 GB). NOT for training.
