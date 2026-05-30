# Risk Engine Module

## Purpose

The Risk Engine module computes disease risk predictions for patients using an ensemble of machine learning models. It runs six disease models simultaneously (Stroke, CVD, Diabetes, CKD, Hypertensive Crisis, COPD) and produces:

- **Risk Score** (0–100) per disease with confidence intervals
- **Risk Stratum** (Low/Moderate/High/Critical) classification
- **SHAP Explanation** showing which features drove each prediction

This is the **API layer** (Task 9). The actual ML models (ensemble, SHAP explainer, etc.) are implemented in Task 20.

## Key Concepts

### Risk Score
A numeric prediction (0–100) representing the probability of a clinical event within a defined timeframe (typically 10 years for stroke/CVD, 5 years for diabetes). Higher scores = higher risk.

### Risk Stratum
Categorical classification derived from the score:
- **Low** (0–24): Minimal risk, standard care
- **Moderate** (25–49): Monitor closely, consider preventive interventions
- **High** (50–74): Significant risk, recommend clinical interventions
- **Critical** (75–100): Urgent risk, immediate clinical action needed

### SHAP Explanation
SHapley Additive exPlanations breakdown showing each feature's contribution to the prediction. Example:
```
base_value: 50.0 (model baseline)
+ systolic_bp (160): +15.0 contribution → higher risk
- exercise (low): -5.0 contribution → lower risk
= final_score: 72.0
```

### Computation ID
A UUID that groups all 6 disease scores from a single risk computation run. Enables linking related scores, tracking computation time, and auditing.

### Model Version
Versioned ML model artifacts (XGBoost pkl, PyTorch pt file, etc.). One active version per disease. Enables:
- A/B testing (route X% of requests to v1, Y% to v2)
- Rollback (revert to v1 if v2 has issues)
- Performance tracking (compare AUC-ROC across versions)
- Audit trail (which model produced which score)

## Dependencies

### Other Modules
- **Patients** (`app.modules.patients`): Patient profile + baseline features
- **Measurements** (`app.modules.measurements`): Clinical measurements (vitals, labs) + feature vector extraction
- **Audit** (`app.core.audit`): Audit logging for computation events
- **Auth** (`app.modules.auth`): RBAC for endpoint access control

### External Services
- **ML Engine** (Task 20): XGBoost, LightGBM, Random Forest, Neural Network ensembles
- **Celery**: Async task queue (background computation)
- **PostgreSQL**: Data persistence (RiskScore, ShapExplanation, ModelVersion tables)
- **Redis**: Celery broker (not directly used by this module, but required for async tasks)

### Core Services
- `app.core.events`: Domain event bus (publishes RiskScoreComputed events)
- `app.core.deps`: FastAPI dependency injection
- `app.core.pagination`: Cursor-based pagination for history queries

## API Surface

### Public Functions (RiskService)

```python
# Trigger async computation
task_id: str = await risk_service.trigger_computation(patient_id)

# Get latest scores for all diseases
scores: dict[str, Optional[dict]] = await risk_service.get_latest_scores(patient_id)

# Get historical scores for one disease (paginated)
history: list[dict] = await risk_service.get_score_history(patient_id, disease, limit=50)

# Store computed scores (called by Celery task)
await risk_service.store_scores(patient_id, computation_id, scores, input_snapshot, model_version_id)
```

### API Endpoints

**POST** `/api/v1/patients/{id}/risk/compute` (202 Accepted)
- Trigger async risk computation
- Returns `task_id` for polling `/tasks/{task_id}/status`
- Requires: Doctor or Nurse role

**GET** `/api/v1/patients/{id}/risk/scores` (200 OK)
- Fetch latest risk scores for all 6 diseases
- Returns dict mapping disease → score (or None if not computed)
- Requires: Doctor or Nurse role
- HIPAA: Response marked `Cache-Control: no-store`

**GET** `/api/v1/patients/{id}/risk/history?disease=stroke&limit=50&offset=0` (200 OK)
- Fetch historical scores for one disease (paginated)
- Returns list of scores ordered most-recent-first
- Requires: Doctor role only
- HIPAA: Response marked `Cache-Control: no-store`

## How to Test

### Unit Tests
```bash
pytest backend/tests/unit/risk_engine/ -v
```

### Property Tests
```bash
pytest backend/tests/property/ -k risk -v
```

### Integration Tests
```bash
pytest backend/tests/integration/test_risk_engine_flow.py -v
```

### Manual Test (with real DB)

1. Create a patient:
   ```bash
   curl -X POST http://localhost:8000/api/v1/patients \
     -H "Authorization: Bearer <jwt>" \
     -d '{"full_name": "Jane Doe", ...}'
   ```

2. Record measurements:
   ```bash
   curl -X POST http://localhost:8000/api/v1/patients/<id>/measurements \
     -H "Authorization: Bearer <jwt>" \
     -d '{"measurement_type": "systolic_bp", "value": 160, ...}'
   ```

3. Trigger risk computation:
   ```bash
   curl -X POST http://localhost:8000/api/v1/patients/<id>/risk/compute \
     -H "Authorization: Bearer <jwt>"
   # Returns: {"success": true, "data": {"task_id": "celery-task-uuid"}}
   ```

4. Poll for completion:
   ```bash
   curl http://localhost:8000/api/v1/tasks/<task-id>/status \
     -H "Authorization: Bearer <jwt>"
   # Returns: {"status": "pending"} then {"status": "completed", "result": {...}}
   ```

5. Fetch computed scores:
   ```bash
   curl http://localhost:8000/api/v1/patients/<id>/risk/scores \
     -H "Authorization: Bearer <jwt>"
   ```

## HIPAA Compliance

### PHI Fields
- `risk_scores.score`: Risk prediction (PHI when tied to patient_id)
- `risk_scores.input_snapshot`: Feature values at computation time (PHI)
- `shap_explanations.feature_contributions`: Feature values and names (PHI)

### Protections
- **Storage**: Encrypted at rest (column-level or TDE)
- **Transit**: TLS 1.2+ (enforced by FastAPI middleware)
- **Caching**: No-store headers on responses with PHI
- **Logging**: Never log scores or features (only UUIDs and status)
- **Audit Trail**: Every computation logged with who triggered it, when, and result status
- **Soft Delete**: Risk scores are immutable (never deleted, only marked stale)
- **Retention**: 7-year minimum per HIPAA (preserved in encrypted DB)

### Example Audit Log Entry
```json
{
  "timestamp": "2026-05-28T20:30:00Z",
  "action": "risk_computation_triggered",
  "resource_type": "patient",
  "resource_id": "abc-123-uuid",
  "user_id": "doctor-uuid",
  "changes": {
    "computation_id": "xyz-456-uuid"
  }
}
```

## Architecture Decisions

### Why Async Celery?
Risk computation can take 5–30 seconds (running 6 ML models). Running synchronously on the API would block requests. Celery allows:
- API returns 202 Accepted immediately (task_id for polling)
- Background workers compute in parallel
- Independent scaling (10 API servers, 20 ML workers)
- Automatic retry on failure (up to 3 times)

### Why Store Input Snapshots?
Features vary over time (BP changes, new labs added). Storing the exact input dict enables:
- Reproducing old scores (audit trail)
- Debugging model predictions
- Comparing inputs across computation runs

### Why Model Versions?
Without versioning, deploying a new model overwrites the old one. Versions enable:
- A/B testing (route % to different versions)
- Rollback (revert to v1 if v2 has poor performance)
- Performance tracking (compare metrics across versions)
- Audit (which model produced which score)

### Why SHAP Explanations?
Machine learning models are "black boxes." SHAP breaks down predictions into interpretable feature contributions, enabling clinicians to:
- Understand why a score is high/low
- Verify the model makes clinical sense
- Catch potential data quality issues (e.g., typo in measurement)

## Forward Compatibility

### Task 10 (Forecast Engine) Needs
- RiskScoreComputed event to carry actual scores → alert system can evaluate thresholds
- Model version reference for forecast comparisons

### Task 14 (Alerts) Needs
- RiskScoreComputed event with scores in payload → can evaluate threshold rules without re-querying
- Risk stratum in event → alert escalation based on stratum

### Task 20 (ML Pipeline) Needs
- Celery task hook point in `compute_risk_scores_task` (currently stubbed with mock)
- Model version registry (ModelVersion table) ✓ already in place
- SHAP explanation format (feature_contributions JSONB structure) ✓ already in place

## Performance

### Computation Time
- **Single patient, all 6 diseases**: <3 seconds (target from Req 6.6)
- **Celery task timeout**: 30 seconds (kill if exceeded)
- **Celery retry**: Up to 3 attempts with backoff (30s, 2min, 8min)

### Database Queries
- Get latest scores: 6 queries (one per disease) + index lookup → <50ms
- Get history (limit 50): 1 query + index → <50ms
- Store scores: 6 RiskScore + 6 ShapExplanation inserts + 1 event publish → <100ms

### Throughput
- Platform target: 500 concurrent tenants, each with 100+ patients
- At peak: ~10 risk computations/minute per tenant (reasonable for 5-10 clinicians)
- Celery workers scale horizontally as load increases

## Monitoring & Debugging

### Celery Task Status
```bash
# Check task status
celery -A app.workers.celery_app inspect active

# View task history
celery -A app.workers.celery_app events
```

### Database Queries
```sql
-- Last 10 computations
SELECT computation_id, patient_id, COUNT(*) as disease_count
FROM risk_scores
GROUP BY computation_id, patient_id
ORDER BY computed_at DESC
LIMIT 10;

-- Scores for one patient
SELECT disease, score, stratum, computed_at
FROM risk_scores
WHERE patient_id = '...'
ORDER BY computed_at DESC;

-- Model versions
SELECT disease, version, is_active, deployed_at
FROM model_versions
ORDER BY disease, deployed_at DESC;
```

### Audit Logs
```sql
-- Risk computations triggered
SELECT timestamp, action, user_id, resource_id
FROM audit_logs
WHERE action = 'risk_computation_triggered'
ORDER BY timestamp DESC
LIMIT 20;
```

## Known Limitations (Task 9)

1. **ML Engine is Stubbed**: Actual models (XGBoost, LightGBM, etc.) not yet implemented (Task 20)
2. **Mock Scores**: Computations return deterministic mock scores, not real predictions
3. **No Model Rollback**: Admin endpoints for deploying/rolling back models not yet built (Task 17)
4. **No Confidence Intervals**: CI calculation is stubbed (Task 20 implements real CI calculation)
5. **No Advanced Scheduling**: Can't schedule periodic recomputation (Task 15 implements scheduling)

## Related Tasks

- **Task 7** (Measurements): Provides `get_feature_vector()` and `check_data_sufficiency()`
- **Task 10** (Forecast): Subscribes to `RiskScoreComputed` events
- **Task 14** (Alerts): Subscribes to `RiskScoreComputed` events, evaluates thresholds
- **Task 20** (ML Pipeline): Implements real ensemble models and SHAP explainer
- **Task 23** (Security): Adds RLS policy tests
- **Task 33** (Integration): Wires router into main FastAPI app
