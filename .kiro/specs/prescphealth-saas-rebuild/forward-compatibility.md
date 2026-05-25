# Forward Compatibility Backlog

This document tracks gaps identified during checkpoint verification that need to be addressed before future tasks can build on current modules robustly. Updated at every checkpoint.

## Status Legend
- 🔴 **BLOCKING** — Must be implemented before the listed task can start
- 🟡 **DEFERRED** — Documented, will implement when the blocking task is next
- ✅ **DONE** — Implemented and verified

---

## Checkpoint 8 Findings (After Task 7 — Measurement Module)

### Gap 1: MeasurementSaved Event Missing Context Fields
- **Status**: 🔴 BLOCKING
- **Current**: `MeasurementSaved` carries only `measurement_id`, `measurement_type`, `patient_id`, `tenant_id`
- **Needed by**: Task 9 (Risk Engine), Task 14 (Alerts)
- **Problem**: Risk engine needs to know if measurement is validated (skip unvalidated). Alert system needs to know if measurement was flagged (>2σ) to generate alert immediately without re-querying.
- **Fix**: Add `is_flagged: bool`, `flag_reason: str | None`, `is_validated: bool` to `MeasurementSaved` event dataclass in `backend/app/core/events.py`
- **Implement**: NOW (before Task 9)
- **Effort**: Small (3 fields added to a dataclass + update publish call in save.py)

### Gap 2: No Feature Vector Extraction Interface
- **Status**: 🔴 BLOCKING
- **Current**: `get_latest_measurements()` returns raw Measurement objects
- **Needed by**: Task 9 (Risk Engine), Task 10 (Forecast Engine)
- **Problem**: ML models need a structured dict `{measurement_type: {value, unit, recorded_at, age_days, is_validated}}` with metadata about data staleness. Currently the risk engine would have to build this transformation itself, duplicating logic.
- **Fix**: Add `get_feature_vector(db, patient_id) -> dict` method to MeasurementService that returns the structured feature dict ready for ML consumption
- **Implement**: NOW (before Task 9)
- **Effort**: Medium (new method + helper function, ~60 lines)

### Gap 3: No Data Sufficiency Check
- **Status**: 🔴 BLOCKING
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

## Implementation Log

| Date | Gap | Action | Commit |
|------|-----|--------|--------|
| _(pending)_ | Gap 1 | Add fields to MeasurementSaved event | — |
| _(pending)_ | Gap 2 | Add get_feature_vector() | — |
| _(pending)_ | Gap 3 | Add check_data_sufficiency() | — |

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
