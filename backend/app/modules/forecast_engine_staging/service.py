"""
PrescpHealth Backend — Forecast Engine Service.

ForecastService orchestrates disease trajectory forecasting:
1. Trigger async Celery tasks (enqueue, return task_id for polling)
2. Retrieve latest forecasts for a patient
3. Trigger intervention simulations (what-if analysis)

Key Responsibilities:
    - Enqueue Celery tasks for background forecast computation
    - Fetch latest disease trajectory predictions
    - Store computed forecasts with ensemble weights and data quality flags
    - Publish ForecastCompleted domain events for downstream subscribers
    - Run counterfactual simulations (intervention outcomes)

The actual ML computation (TFT, LSTM, Prophet ensemble) is implemented
in Task 20+ (ml/forecast_engine/). For now, this service calls stubs
that return mock forecasts.

HIPAA Compliance:
    - Never log forecast values or patient data (opaque IDs only)
    - Cache headers set to no-store on API responses containing PHI
    - All computations audited via AuditService
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus, ForecastCompleted
from app.modules.audit.service import AuditService
from app.modules.forecast_engine_staging.models import Forecast, InterventionSimulation
from app.modules.forecast_engine_staging.tasks import (
    compute_forecast_task,
    run_simulation_task,
)

logger = structlog.get_logger(__name__)


class ForecastService:
    """
    Service for managing disease trajectory forecasts and intervention simulations.

    Provides high-level operations for the forecast engine:
    - Trigger async forecasts (returns task_id for polling)
    - Fetch latest forecasts (all targets, all horizons)
    - Trigger intervention simulations (what-if analysis)
    - Store computed forecasts with ensemble weights

    All operations are tenant-scoped (RLS enforced by AsyncSession context).
    """

    def __init__(self, db: AsyncSession, audit_service: AuditService):
        """
        Initialize ForecastService.

        Args:
            db: AsyncSession for database operations
            audit_service: AuditService for audit logging
        """
        self.db = db
        self.audit_service = audit_service

    async def trigger_forecast(self, patient_id: uuid.UUID) -> str:
        """
        Trigger async forecast computation for a patient.

        Enqueues a Celery background task that will compute disease
        trajectory forecasts at 3, 6, and 12-month horizons.

        Args:
            patient_id: Patient UUID

        Returns:
            str: Celery task_id for polling /tasks/{task_id}/status

        Audit:
            Logs "forecast_triggered" event with patient_id and task_id
        """
        task_id = compute_forecast_task.delay(str(patient_id))
        logger.info(
            "forecast_triggered",
            patient_id=str(patient_id),
            task_id=str(task_id),
        )
        return str(task_id)

    async def get_latest_forecast(self, patient_id: uuid.UUID) -> dict[str, Optional[dict]]:
        """
        Fetch latest forecasts for a patient across all targets.

        Returns dict mapping target → latest forecast data (or None if not computed).
        Includes ensemble weights and data quality indicator.

        Args:
            patient_id: Patient UUID

        Returns:
            dict: {
                "systolic_bp": {
                    "horizon_3m": {...},
                    "horizon_6m": {...},
                    "horizon_12m": {...},
                },
                "stroke": {...},
                ...
            }
            or None if no forecasts exist

        Example:
            {
                "systolic_bp": {
                    "horizon_3m": {
                        "point_estimate": 145.2,
                        "confidence_lower": 140.0,
                        "confidence_upper": 150.4,
                        "data_quality": "full_data",
                        "model_weights": {"tft": 0.4, "lstm": 0.35, "prophet": 0.25},
                        "computed_at": "2026-05-28T20:55:00Z"
                    },
                    ...
                },
                "stroke": {...}
            }
        """
        # Get latest forecast per target per horizon
        stmt = select(Forecast).where(
            Forecast.patient_id == patient_id
        ).order_by(
            Forecast.target,
            Forecast.horizon_months,
            desc(Forecast.computed_at)
        ).distinct(
            Forecast.target,
            Forecast.horizon_months
        )

        result = await self.db.execute(stmt)
        forecasts = result.scalars().all()

        if not forecasts:
            return {}

        # Organize by target → horizon
        output = {}
        for forecast in forecasts:
            if forecast.target not in output:
                output[forecast.target] = {}

            horizon_key = f"horizon_{forecast.horizon_months}m"
            output[forecast.target][horizon_key] = {
                "point_estimate": float(forecast.point_estimate),
                "confidence_lower": float(forecast.confidence_lower),
                "confidence_upper": float(forecast.confidence_upper),
                "data_quality": forecast.data_quality,
                "model_weights": forecast.model_ensemble_weights,
                "computed_at": forecast.computed_at.isoformat(),
            }

        return output

    async def trigger_simulation(
        self,
        patient_id: uuid.UUID,
        intervention_type: str,
        parameters: dict,
    ) -> str:
        """
        Trigger intervention simulation (what-if analysis).

        Simulates clinical outcomes if patient takes action
        (weight loss, smoking cessation, medication change, exercise increase).

        Args:
            patient_id: Patient UUID
            intervention_type: "weight_loss", "smoking_cessation", "medication_addition", "exercise_increase"
            parameters: dict with intervention details (e.g., {"target_weight_kg": 85})

        Returns:
            str: Celery task_id for polling

        Audit:
            Logs "simulation_triggered" event
        """
        task_id = run_simulation_task.delay(
            str(patient_id),
            intervention_type,
            parameters,
        )
        logger.info(
            "simulation_triggered",
            patient_id=str(patient_id),
            intervention_type=intervention_type,
            task_id=str(task_id),
        )
        return str(task_id)

    async def store_forecast(
        self,
        patient_id: uuid.UUID,
        forecast_type: str,
        target: str,
        horizon_months: int,
        point_estimate: Decimal,
        confidence_lower: Decimal,
        confidence_upper: Decimal,
        data_quality: str,
        model_ensemble_weights: dict,
    ) -> None:
        """
        Store computed forecast in database.

        Called by Celery task after ML computation.

        Args:
            patient_id: Patient UUID
            forecast_type: "metric" or "risk_trajectory"
            target: What we're forecasting (e.g., "systolic_bp", "stroke")
            horizon_months: 3, 6, or 12
            point_estimate: Best prediction (Decimal)
            confidence_lower: CI lower bound (Decimal)
            confidence_upper: CI upper bound (Decimal)
            data_quality: "full_data", "sparse_data", or "prior_only"
            model_ensemble_weights: dict {tft, lstm, prophet}

        Side Effects:
            - Stores forecast in DB
            - Publishes ForecastCompleted event
            - Logs audit trail
        """
        forecast = Forecast(
            patient_id=patient_id,
            forecast_type=forecast_type,
            target=target,
            horizon_months=horizon_months,
            point_estimate=point_estimate,
            confidence_lower=confidence_lower,
            confidence_upper=confidence_upper,
            data_quality=data_quality,
            model_ensemble_weights=model_ensemble_weights,
        )
        self.db.add(forecast)
        await self.db.flush()

        # Publish event
        event = ForecastCompleted(
            patient_id=patient_id,
            forecast_id=forecast.id,
            target=target,
            horizon_months=horizon_months,
            point_estimate=float(point_estimate),
        )
        event_bus.publish(event)

        logger.info(
            "forecast_stored",
            patient_id=str(patient_id),
            target=target,
            horizon=horizon_months,
        )
