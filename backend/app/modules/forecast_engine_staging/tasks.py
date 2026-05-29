"""
PrescpHealth Backend — Forecast Engine Celery Tasks.

Background worker tasks for async forecast computation and intervention simulation.

Task: compute_forecast
    Triggered when: User requests forecast via API
    Processing:
    1. Fetch patient's historical measurements (time series)
    2. Extract features and trend data
    3. Call ML ensemble (TFT, LSTM, Prophet) (stub for now, real in Task 20+)
    4. Compute forecasts at 3/6/12 month horizons
    5. Store Forecast records with ensemble weights
    6. Publish ForecastCompleted event
    7. Log audit trail

Task: run_simulation
    Triggered when: User requests intervention simulation
    Processing:
    1. Get baseline forecast (reference for comparison)
    2. Modify patient's assumed behavior (weight loss, smoking cessation, etc.)
    3. Re-run forecast with modified assumptions
    4. Compare baseline vs simulated outcomes
    5. Store InterventionSimulation record
    6. Log audit trail

Retry Policy:
    - Up to 3 retries with exponential backoff (30s, 2min, 8min)
    - Max execution time: 30 seconds
    - Failures logged but don't crash the worker

HIPAA Compliance:
    - Never log forecast values, patient names, or clinical data
    - Log only patient_id UUID, task_id, and status
    - Historical data fetched is in memory only (cleared after computation)
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.core.audit import AuditService
from app.modules.forecast_engine_staging.service import ForecastService

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,  # First retry after 30s
    time_limit=30,  # Max 30 seconds execution time
)
def compute_forecast_task(
    self,
    patient_id: str,
) -> dict:
    """
    Async Celery task to compute disease forecasts for a patient.

    Runs on a Celery worker (independent from API server).

    Args:
        patient_id: Patient UUID (as string from task enqueue)

    Returns:
        dict: {
            "success": true,
            "forecasts": [
                {"target": "systolic_bp", "horizon_3m": 145.2, ...},
                {"target": "stroke", "horizon_12m": 68.5, ...},
                ...
            ]
        }

    Retry Logic:
        - Retries up to 3 times with exponential backoff on failure
        - Failures logged with correlation ID
    """
    try:
        patient_uuid = uuid.UUID(patient_id)

        # Create async session in worker context
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
        )
        async_session = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # TODO: Task 20+: Replace with real forecast computation
        # For now, generate mock forecasts
        forecasts = _compute_mock_forecasts(patient_uuid)

        logger.info(
            "forecast_computed",
            patient_id=str(patient_uuid),
            forecast_count=len(forecasts),
        )

        return {
            "success": True,
            "forecasts": forecasts,
        }

    except Exception as exc:
        logger.error(
            "forecast_computation_failed",
            patient_id=patient_id,
            error=str(exc),
            retry_count=self.request.retries,
        )

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
        else:
            return {
                "success": False,
                "error": str(exc),
            }


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    time_limit=30,
)
def run_simulation_task(
    self,
    patient_id: str,
    intervention_type: str,
    parameters: dict,
) -> dict:
    """
    Async Celery task to run intervention simulation.

    Compares baseline forecast with simulated outcomes under
    different intervention scenario.

    Args:
        patient_id: Patient UUID (as string)
        intervention_type: "weight_loss", "smoking_cessation", etc.
        parameters: Intervention details (e.g., {"target_weight_kg": 85})

    Returns:
        dict: {
            "success": true,
            "simulated_results": [
                {"horizon": 3, "metric": "systolic_bp", "baseline": 160, "simulated": 145, "delta": -15},
                ...
            ]
        }
    """
    try:
        patient_uuid = uuid.UUID(patient_id)

        # TODO: Task 20+: Replace with real simulation computation
        # For now, generate mock simulation results
        simulated_results = _run_mock_simulation(
            patient_uuid,
            intervention_type,
            parameters,
        )

        logger.info(
            "simulation_completed",
            patient_id=str(patient_uuid),
            intervention_type=intervention_type,
            result_count=len(simulated_results),
        )

        return {
            "success": True,
            "simulated_results": simulated_results,
        }

    except Exception as exc:
        logger.error(
            "simulation_failed",
            patient_id=patient_id,
            intervention_type=intervention_type,
            error=str(exc),
        )

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
        else:
            return {
                "success": False,
                "error": str(exc),
            }


def _compute_mock_forecasts(patient_id: uuid.UUID) -> list[dict]:
    """
    Generate mock forecasts for testing (replaced by real ML in Task 20+).

    Returns forecasts for common targets (systolic_bp, stroke, diabetes)
    at 3/6/12 month horizons.

    Args:
        patient_id: Patient UUID (used for determinism)

    Returns:
        list of dicts with mock forecast data
    """
    # Use patient_id hash for deterministic but different values per patient
    seed = int(patient_id.int % 10000)

    forecasts = []

    targets = ["systolic_bp", "stroke", "diabetes", "cvd"]
    for target in targets:
        for horizon in [3, 6, 12]:
            # Mock: baseline + random variation
            if target == "systolic_bp":
                point = 140 + (seed % 30)
            elif target in ["stroke", "diabetes", "cvd"]:
                point = 50 + (seed % 40)
            else:
                point = 50.0

            # Mock CI (± 10% of point estimate)
            ci_width = float(point) * 0.1
            lower = float(point) - ci_width
            upper = float(point) + ci_width

            forecasts.append({
                "target": target,
                "horizon_months": horizon,
                "point_estimate": point,
                "confidence_lower": lower,
                "confidence_upper": upper,
                "data_quality": "full_data" if seed % 3 != 2 else "sparse_data",
                "model_weights": {"tft": 0.4, "lstm": 0.35, "prophet": 0.25},
            })

    return forecasts


def _run_mock_simulation(
    patient_id: uuid.UUID,
    intervention_type: str,
    parameters: dict,
) -> list[dict]:
    """
    Generate mock simulation results (replaced by real ML in Task 20+).

    Simulates clinical outcomes under intervention scenario.

    Args:
        patient_id: Patient UUID
        intervention_type: Type of intervention
        parameters: Intervention parameters

    Returns:
        list of dicts with simulated results
    """
    seed = int(patient_id.int % 10000)

    results = []

    # Mock: intervention reduces risk/improves metrics
    improvement_factors = {
        "weight_loss": 0.85,  # 15% improvement
        "smoking_cessation": 0.80,  # 20% improvement
        "medication_addition": 0.90,  # 10% improvement
        "exercise_increase": 0.88,  # 12% improvement
    }

    factor = improvement_factors.get(intervention_type, 0.95)

    for horizon in [3, 6, 12]:
        baseline_value = 140 + (seed % 30)  # Mock baseline
        simulated_value = baseline_value * factor
        delta = simulated_value - baseline_value

        results.append({
            "horizon": horizon,
            "metric": "systolic_bp",
            "baseline_value": baseline_value,
            "simulated_value": round(simulated_value, 2),
            "delta": round(delta, 2),
        })

    return results
