# Forecast Engine Module

## Purpose

The Forecast Engine predicts disease trajectories and clinical outcomes over time. It runs an ensemble of time-series models (Temporal Fusion Transformer, LSTM, Prophet) to forecast measurement values and disease risk changes at 3, 6, and 12-month horizons.

Key capabilities:
- **Disease Trajectory Forecasting**: Predict future measurement values (e.g., systolic BP, glucose)
- **Risk Trajectory Forecasting**: Predict how disease risk will evolve
- **Intervention Simulation**: "What-if" analysis — forecast outcomes if patient takes action
- **Ensemble Explainability**: Weights for each model (TFT, LSTM, Prophet) show which models drove the forecast

This is the **API layer** (Task 10). The actual ML forecast ensemble (TFT, LSTM, Prophet, SHAP) is implemented in Task 20+.

## Key Concepts

### Forecast
A prediction of future measurement or risk value at a specific horizon (3, 6, or 12 months ahead).

Example: "Patient's systolic BP will be 145 (95% CI: 140–150) in 6 months"

Fields:
- **point_estimate**: Best prediction (single value)
- **confidence_lower/upper**: 95% confidence interval
- **data_quality**: "full_data" (enough history), "sparse_data" (limited history), or "prior_only" (bootstrapped)
- **model_ensemble_weights**: {tft: 0.4, lstm: 0.35, prophet: 0.25} — which models contributed

### Intervention Simulation
Counterfactual analysis: "If patient loses 10kg, what happens to their systolic BP forecast?"

Simulations support:
- **weight_loss**: Target weight reduction (e.g., 85kg target)
- **smoking_cessation**: Assume patient quits smoking
- **medication_addition**: Add medication to regimen
- **exercise_increase**: Assume increased physical activity

### Data Quality Flags
Warns clinician about forecast confidence:
- **full_data**: ≥12 months historical measurements → high confidence
- **sparse_data**: 3–11 months of history → moderate confidence
- **prior_only**: <3 months of history → forecast based on prior/population baseline

## Dependencies

### Other Modules
- **Risk Engine** (Task 9): Risk score context for risk trajectory forecasts
- **Measurements** (Task 7): Historical measurement time series for trend extraction
- **Patients** (Task 5): Patient profile and baseline features
- **Audit** (core): Audit logging for forecast triggers and data access
- **Events** (core): Event bus for publishing ForecastCompleted events

### External Services
- **ML Forecast Ensemble** (Task 20+): TFT, LSTM, Prophet models
- **Celery**: Async task queue (background computation)
- **PostgreSQL**: Data persistence (Forecast, InterventionSimulation tables)
- **Redis**: Celery broker (not directly used, but required)

## API Surface

### Public Functions (ForecastService)

```python
# Trigger async forecast computation
task_id: str = await forecast_service.trigger_forecast(patient_id)

# Get latest forecasts for all targets
forecasts: dict = await forecast_service.get_latest_forecast(patient_id)

# Trigger intervention simulation
task_id: str = await forecast_service.trigger_simulation(patient_id, intervention_type, parameters)

# Store computed forecast (called by Celery task)
await forecast_service.store_forecast(patient_id, forecast_type, target, horizon_months, point_estimate, ...)
```

### API Endpoints

**POST** `/api/v1/patients/{id}/forecast` (202 Accepted)
- Trigger async forecast computation
- Returns `task_id` for polling `/tasks/{task_id}/status`
- Requires: Doctor role

**GET** `/api/v1/patients/{id}/forecast/latest` (200 OK)
- Fetch latest forecasts for all targets (all horizons)
- Returns dict: {systolic_bp: {horizon_3m: {...}, ...}, stroke: {...}, ...}
- Requires: Doctor role
- HIPAA: Response marked `Cache-Control: no-store`

**POST** `/api/v1/patients/{id}/forecast/simulate` (202 Accepted)
- Run intervention simulation (what-if analysis)
- Request: {intervention_type: "weight_loss", parameters: {...}}
- Returns `task_id` for polling
- Requires: Doctor role

## How to Test

### Unit Tests
```bash
pytest backend/tests/unit/forecast_engine/ -v
```

### Integration Tests
```bash
pytest backend/tests/integration/test_forecast_flow.py -v
```

### Manual Test (with real DB)

1. Create a patient (see Patients module)
2. Record measurements (see Measurements module)
3. Trigger forecast:
   ```bash
   curl -X POST http://localhost:8000/api/v1/patients/<id>/forecast \
     -H "Authorization: Bearer <jwt>"
   # Returns: {"success": true, "data": {"task_id": "celery-task-uuid"}}
   ```
4. Poll for completion:
   ```bash
   curl http://localhost:8000/api/v1/tasks/<task-id>/status \
     -H "Authorization: Bearer <jwt>"
   # Returns: {"status": "pending"} then {"status": "completed"}
   ```
5. Fetch forecasts:
   ```bash
   curl http://localhost:8000/api/v1/patients/<id>/forecast/latest \
     -H "Authorization: Bearer <jwt>"
   ```
6. Run simulation:
   ```bash
   curl -X POST http://localhost:8000/api/v1/patients/<id>/forecast/simulate \
     -H "Authorization: Bearer <jwt>" \
     -d '{
       "intervention_type": "weight_loss",
       "parameters": {"target_weight_kg": 85, "duration_months": 6}
     }'
   ```

## HIPAA Compliance

### PHI Fields
- `forecasts.point_estimate`: Numeric prediction (PHI when tied to patient_id)
- `forecasts.target`: What we're forecasting (PHI — may reference diseases)
- `intervention_simulations.simulated_results`: Simulated outcomes (PHI)

### Protections
- **Storage**: Encrypted at rest (column-level or TDE)
- **Transit**: TLS 1.2+ (enforced by FastAPI middleware)
- **Caching**: No-store headers on responses with PHI
- **Logging**: Never log forecast values or targets (only UUIDs and status)
- **Audit Trail**: Every forecast triggered and accessed logged with who and when
- **Immutable Records**: Forecasts are append-only (no updates/deletes)
- **Retention**: 7-year minimum per HIPAA (preserved in encrypted DB)

### Example Audit Log Entry
```json
{
  "timestamp": "2026-05-28T20:55:00Z",
  "action": "forecast_triggered",
  "resource_type": "patient",
  "resource_id": "abc-123-uuid",
  "user_id": "doctor-uuid",
  "changes": {"task_id": "xyz-456-uuid"}
}
```

## Architecture Decisions

### Why Async Celery?
Forecast computation can take 10–30 seconds (running TFT, LSTM, Prophet on time series). Running synchronously would block API. Celery enables:
- API returns 202 Accepted immediately (task_id for polling)
- Background workers compute in parallel
- Independent scaling (10 API servers, 20 forecast workers)
- Automatic retry on failure (up to 3 times)

### Why Store Ensemble Weights?
Clinicians need to understand predictions. Ensemble weights enable:
- "This forecast is 40% TFT, 35% LSTM, 25% Prophet" — transparency
- Debugging (which model predicted what)
- Model accountability (can audit which models are active)

### Why Three Horizons?
Clinical decision-making operates at different timescales:
- **3 months**: Short-term management decisions
- **6 months**: Medium-term intervention planning
- **12 months**: Long-term risk stratification

### Why Intervention Simulations?
Enable shared decision-making:
- Clinician: "If you lose 10kg, your BP forecast improves from 160 → 145"
- Patient: Clear, concrete outcome of behavior change
- Better adherence when patients see tangible benefits

## Forward Compatibility

### Task 11 (AI Assistant) Needs
- Forecast data accessible via ForecastService.get_latest_forecast()
- Can reference forecasts in clinical reasoning

### Task 14 (Alerts) Needs
- ForecastCompleted event to trigger alert rules based on forecast thresholds
- Simulation results to power "expected vs actual" alerts

### Task 20+ (ML Pipeline) Needs
- Celery task hook point in `compute_forecast_task()` (currently stubbed with mock)
- Integration with TFT, LSTM, Prophet model loaders
- Ensemble weight calculation and storage

## Performance

### Computation Time
- **Single patient, all targets, all horizons**: <10 seconds (target)
- **Celery task timeout**: 30 seconds (kill if exceeded)
- **Celery retry**: Up to 3 attempts with backoff (30s, 2min, 8min)

### Database Queries
- Get latest forecasts: 1 query + index → <50ms
- Store forecasts: 12 inserts (3 horizons × 4 targets) → <100ms

### Throughput
- Platform target: 500 concurrent tenants
- At peak: ~5 forecasts/hour per tenant (reasonable for 5–10 clinicians)
- Celery workers scale horizontally as load increases

## Monitoring & Debugging

### Celery Task Status
```bash
celery -A app.workers.celery_app inspect active
celery -A app.workers.celery_app events
```

### Database Queries
```sql
-- Last 10 forecasts
SELECT patient_id, target, horizon_months, point_estimate, computed_at
FROM forecasts
ORDER BY computed_at DESC
LIMIT 10;

-- Forecasts for one patient
SELECT target, horizon_months, point_estimate, confidence_lower, confidence_upper, data_quality
FROM forecasts
WHERE patient_id = '...'
ORDER BY target, horizon_months, computed_at DESC;

-- Latest forecast per target
SELECT DISTINCT ON (target, horizon_months) patient_id, target, horizon_months, point_estimate, computed_at
FROM forecasts
WHERE patient_id = '...'
ORDER BY target, horizon_months, computed_at DESC;
```

### Audit Logs
```sql
-- Forecast triggers
SELECT timestamp, action, user_id, resource_id
FROM audit_logs
WHERE action IN ('forecast_triggered', 'forecast_accessed')
ORDER BY timestamp DESC
LIMIT 20;
```

## Known Limitations (Task 10)

1. **ML Ensemble is Stubbed**: Actual models (TFT, LSTM, Prophet) not yet implemented (Task 20+)
2. **Mock Forecasts**: Computations return deterministic mock forecasts, not real predictions
3. **No Advanced Features**: Forecast revision, model A/B testing, confidence calibration (Tasks 20+)
4. **No Historical Drift Detection**: Can't warn if forecast accuracy is declining
5. **Simulation Logic is Simplified**: Mock simulations use fixed improvement factors (Task 20+)

## Related Tasks

- **Task 9** (Risk Engine): Provides risk score context
- **Task 7** (Measurements): Provides historical time series
- **Task 11** (AI Assistant): Subscribes to ForecastCompleted events
- **Task 14** (Alerts): Uses forecasts to trigger alerts
- **Task 20+** (ML Pipeline): Implements real TFT, LSTM, Prophet models
- **Task 23** (Security): Adds RLS policy tests
- **Task 33** (Integration): Wires router into main FastAPI app
