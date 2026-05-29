"""
PrescpHealth Backend — Forecast Engine Module (Staging).

The Forecast Engine predicts future disease trajectories and clinical outcomes.

Module Responsibility:
    - Expose API endpoints for triggering forecasts and intervention simulations
    - Manage async Celery tasks for background forecast computation
    - Store disease forecasts at 3/6/12-month horizons
    - Simulate clinical interventions (weight loss, smoking cessation, etc.)
    - Publish ForecastCompleted domain events for downstream subscribers

Key Components:
    - models.py: SQLAlchemy models (Forecast, InterventionSimulation)
    - service.py: ForecastService (trigger forecast, get latest, simulate)
    - tasks.py: Celery tasks for async forecast computation and simulation
    - router.py: FastAPI endpoints with RBAC
    - schemas.py: Pydantic request/response models
    - engine.py: Forecast computation logic (TFT, LSTM, Prophet ensemble)

Dependencies:
    - Requires Task 9 (Risk Engine) for risk score context
    - Requires Task 7 (Measurement module) for historical trends
    - Requires Task 5 (Patient module) for patient data
    - Requires core services: audit, events, pagination
    - Requires ML forecast pipeline (Task 20+) — currently stubbed

HIPAA Compliance:
    - Forecasts are PHI when tied to patient_id — never log values
    - All responses include Cache-Control: no-store
    - All computation audited via AuditService
"""

from app.modules.forecast_engine_staging.service import ForecastService
from app.modules.forecast_engine_staging.router import router

__all__ = ["ForecastService", "router"]
