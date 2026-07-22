# Forward Compatibility Backlog

This document tracks gaps identified during checkpoint verification that need to be addressed before future tasks can build on current modules robustly. Updated at every checkpoint.

## Status Legend
- 🔴 **BLOCKING** — Must be implemented before the listed task can start
- 🟡 **DEFERRED** — Documented, will implement when the blocking task is next
- ✅ **DONE** — Implemented and verified

---

## Checkpoint 8 Findings (After Task 7 — Measurement Module)

### Gap 1: MeasurementSaved Event Missing Context Fields
- **Status**: ✅ DONE
- **Current**: `MeasurementSaved` carries only `measurement_id`, `measurement_type`, `patient_id`, `tenant_id`
- **Needed by**: Task 9 (Risk Engine), Task 14 (Alerts)
- **Problem**: Risk engine needs to know if measurement is validated (skip unvalidated). Alert system needs to know if measurement was flagged (>2σ) to generate alert immediately without re-querying.
- **Fix**: Add `is_flagged: bool`, `flag_reason: str | None`, `is_validated: bool` to `MeasurementSaved` event dataclass in `backend/app/core/events.py`
- **Implement**: NOW (before Task 9)
- **Effort**: Small (3 fields added to a dataclass + update publish call in save.py)

### Gap 2: No Feature Vector Extraction Interface
- **Status**: ✅ DONE
- **Current**: `get_latest_measurements()` returns raw Measurement objects
- **Needed by**: Task 9 (Risk Engine), Task 10 (Forecast Engine)
- **Problem**: ML models need a structured dict `{measurement_type: {value, unit, recorded_at, age_days, is_validated}}` with metadata about data staleness. Currently the risk engine would have to build this transformation itself, duplicating logic.
- **Fix**: Add `get_feature_vector(db, patient_id) -> dict` method to MeasurementService that returns the structured feature dict ready for ML consumption
- **Implement**: NOW (before Task 9)
- **Effort**: Medium (new method + helper function, ~60 lines)

### Gap 3: No Data Sufficiency Check
- **Status**: ✅ DONE
- **Current**: No way to ask "does this patient have enough data for risk/forecast computation?"
- **Needed by**: Task 9 (Risk Engine), Task 10 (Forecast Engine)
- **Problem**: Design doc specifies `data_quality` field on forecasts (`full_data`, `sparse_data`, `prior_only`). Engines need to know what's available before computing. Without this, the risk engine would have to implement its own sufficiency logic.
- **Fix**: Add `check_data_sufficiency(db, patient_id) -> DataSufficiencyResult` method that returns which measurement types are available, how recent, and whether minimum requirements are met per disease model
- **Implement**: NOW (before Task 9)
- **Effort**: Medium (new method + dataclass for result, ~80 lines)

### Gap 4: No Patient Context Aggregation for LLM
- **Status**: 🟡 DEFERRED
- **Current**: Patient data, measurements, and risk scores are in separate modules with no cross-module aggregation
- **Needed by**: Task 11 (AI Assistant)
- **Problem**: The LLM needs an anonymized "patient context" combining demographics + latest measurements + risk scores + active medications. No service currently aggregates this.
- **Fix**: Create `backend/app/core/patient_context.py` with `get_patient_context(db, patient_id) -> PatientContext` that assembles the anonymized clinical summary
- **Implement**: Before Task 11 (AI Assistant)
- **Effort**: Medium-Large (new module, cross-module queries, anonymization logic)

### Gap 5: RiskScoreComputed Event Missing Score Details
- **Status**: 🟡 DEFERRED
- **Current**: `RiskScoreComputed` carries only `patient_id`, `disease_count`, `computation_id`
- **Needed by**: Task 14 (Alerts)
- **Problem**: Alert system needs actual scores and strata to evaluate thresholds (e.g., "alert if stroke > 80") without re-querying
- **Fix**: Add `scores: list[dict]` field with `[{disease, score, stratum}]` to the event
- **Implement**: During Task 9 (when the event is first published with real data)
- **Effort**: Small (add field to dataclass + populate when publishing)

### Gap 6: No Standardized Router Registration Pattern
- **Status**: 🟡 DEFERRED
- **Current**: Measurements has `detail_router` on separate prefix needing separate registration. Other modules use single router.
- **Needed by**: Task 33 (Wire Routers)
- **Problem**: Inconsistent patterns make wiring error-prone
- **Fix**: Create `register_routers()` helper in main.py or document the multi-router pattern
- **Implement**: During Task 33
- **Effort**: Small

### Gap 7: deps.py Stubs Not Wired
- **Status**: 🟡 DEFERRED
- **Current**: `get_current_user()` and `get_tenant_db()` are stubs that raise errors. Routers use `require_role()` instead.
- **Needed by**: Task 33 (Wire Routers)
- **Problem**: Confusing to have dead stubs alongside working auth. Could cause bugs if someone uses the wrong dependency.
- **Fix**: Either wire them to use same JWT logic as `require_role()`, or remove them entirely and standardize on `require_role()`
- **Implement**: During Task 33
- **Effort**: Small

---

## ML Training Pipeline Findings (2026-07-20 — during MIMIC-IV cohort + feature engineering)

These are deferred data/labelling limitations in the training pipeline
(`ml/training/`). They do not block writing the training code, but each must be
resolved (or explicitly accepted) BEFORE trained models are validated and shipped,
because each can bias metrics or the learned models. Also noted in code comments
at the relevant module and in `memory/2026-07-20.md`.

### Gap 8: ICD-9 diagnoses excluded from disease labelling
- **Status**: 🟡 DEFERRED
- **Current**: `disease_labels.py` labels only `icd_version == 10` rows; ICD-9 rows are skipped. `icd9_diagnosis_count()` reports how many are excluded.
- **Needed by**: Per-disease model training (before eICU validation / shipping).
- **Problem**: MIMIC-IV mixes ICD-9 and ICD-10. Dropping ICD-9 undercounts positives (false negatives in labels), especially for older admissions — biases prevalence and model recall. Magnitude is currently unquantified.
- **Fix**: Either (a) add an ICD-9→ICD-10 crosswalk (GEMs) for the six target diseases, or (b) measure the excluded fraction and explicitly accept it as a threat-to-validity in the methods writeup.
- **Implement**: Before training runs on real MIMIC data.
- **Effort**: Medium (crosswalk table + tests) or Small (quantify + accept).

### Gap 9: `min_icu_hours` cohort criterion not applied
- **Status**: 🟡 DEFERRED
- **Current**: `build_cohort` applies only `min_age`. `assemble.filter_by_vital_completeness` applies `max_missing_vitals_pct`. The `min_icu_hours` (24h) criterion in `COHORT_CRITERIA` is NOT applied.
- **Needed by**: Cohort finalization before training.
- **Problem**: Without the ICU-stay-duration gate, very short stays (little data, different population) enter the cohort, diluting/biasing training. Needs the `icustays` table (not currently loaded).
- **Fix**: Add an `icustays`-based filter step (`los`/`intime`/`outtime` → hours) applied after cohort build.
- **Implement**: Before training runs.
- **Effort**: Small–Medium (load icustays, compute stay hours, filter).

### Gap 10: Sparse schema features not extracted
- **Status**: 🟡 DEFERRED
- **Current**: `fev1`, `fev1_fvc_ratio`, `waist_circumference`, `albumin_creatinine_ratio` are in the inference schema (`POPULATION_PRIORS`) but are NOT extracted by `features/`. At inference the imputer fills them; in training they are simply absent.
- **Needed by**: COPD (fev1/ratio) and CKD (ACR) model quality especially.
- **Problem**: These are sparse in MIMIC ICU data. Absent training features weaken exactly the disease models that depend on them (COPD, CKD), and create a train/inference asymmetry (imputed-only at inference, never learned).
- **Fix**: Investigate MIMIC itemids/labs for spirometry + urine ACR; extract where present, else document per-disease as unavailable and rely on the meta-learner's clinical-standard fallback for those diseases.
- **Implement**: Before per-disease training of COPD and CKD.
- **Effort**: Medium (source itemids, extraction + tests) — or Small to formally accept the gap per disease.

### Note: `Glucose → fasting_glucose` approximation
- **Status**: 🟡 DEFERRED (validity caveat, not a blocker)
- **Current**: `labs.py` maps MIMIC "Glucose" (serum, not necessarily fasting) to the `fasting_glucose` feature — documented in the module.
- **Fix/Decide**: Accept as approximation (label as such in methods) or source a fasting-specific signal. Relevant to diabetes model interpretation.
- **Implement**: Before diabetes model is reported/shipped.

---

## Implementation Log

| Date | Gap | Action | Commit |
|------|-----|--------|--------|
| 2025-07-12 | Gap 1 | Added is_flagged, flag_reason, is_validated to MeasurementSaved event | feat/measurement-module |
| 2025-07-12 | Gap 2 | Created feature_vector.py + added get_feature_vector() to MeasurementService | feat/measurement-module |
| 2025-07-12 | Gap 3 | Created data_sufficiency.py + added check_data_sufficiency() to MeasurementService | feat/measurement-module |

---

## Future Checkpoints

### Checkpoint 13 (After Tasks 9-12: Risk, Forecast, AI, Drugs)
- Review what Tasks 14-19 need (Alerts, Reports, Population, Admin)
- Expected gaps: alert threshold configuration interface, report data aggregation

### Checkpoint 19 (After Tasks 14-18: Alerts, Reports, Population, Admin)
- Review what Tasks 20-21 need (ML Pipelines)
- Expected gaps: model registry interface, training data extraction

### Checkpoint 22 (After Tasks 20-21: ML Pipelines)
- Review what Tasks 23-24 need (Security Hardening)
- Expected gaps: RLS policy completeness for new tables

### Checkpoint 24 (After Tasks 23: Security)
- Review what Tasks 25-31 need (Frontend)
- Expected gaps: API response format consistency, WebSocket for real-time alerts

### Checkpoint 32 (After Tasks 25-31: Frontend)
- Review what Tasks 33-35 need (Integration, Docker)
- Expected gaps: router registration, environment config, health checks
