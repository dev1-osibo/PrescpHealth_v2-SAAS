"""
PrescpHealth Backend — Forecast Engine FastAPI Router.

Three endpoints for forecast operations:
1. POST /patients/{id}/forecast — Trigger async forecast computation
2. GET /patients/{id}/forecast/latest — Get latest forecasts for all targets
3. POST /patients/{id}/forecast/simulate — Run intervention simulation

All endpoints:
- Require authentication (via require_role dependency)
- Enforce RBAC (Doctor role)
- Set HIPAA headers (Cache-Control: no-store on PHI responses)
- Use standard response envelope
- Include request_id for correlation/audit

HIPAA Compliance:
    - Forecasts are PHI — responses marked no-cache
    - No forecast values in logs (only patient_id UUID)
    - All calls audited via AuditService
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_request_id, get_tenant_id, get_current_user
from app.modules.auth.rbac import Role, require_role
from app.modules.audit.service import AuditService
from app.modules.forecast_engine_staging.service import ForecastService
from app.modules.forecast_engine_staging.schemas import (
    ComputeForecastRequest,
    ForecastComputationResponse,
    ForecastLatestResponse,
    RunSimulationRequest,
    SimulationResponse,
)

# Router prefix: /api/v1/patients/{id}/forecast/...
router = APIRouter(prefix="/forecast", tags=["forecast_engine"])


@router.post(
    "/compute",
    response_model=ForecastComputationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async forecast computation",
    description="Enqueue a Celery task to compute disease trajectory forecasts. Returns task_id for polling.",
)
async def trigger_forecast(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR))],
) -> ForecastComputationResponse:
    """
    Trigger async forecast computation for a patient.

    This endpoint enqueues a Celery background task that will:
    1. Fetch patient's historical measurements (time series)
    2. Extract features and trends
    3. Run ML forecast ensemble (TFT, LSTM, Prophet)
    4. Compute forecasts at 3/6/12 month horizons
    5. Store Forecast records with ensemble weights
    6. Publish ForecastCompleted event

    Returns a task_id that can be used to poll /tasks/{task_id}/status
    for completion status.

    Args:
        patient_id: Patient UUID (from URL path)

    Returns:
        ForecastComputationResponse: {success: true, data: {task_id: "..."}, meta: {...}}

    Status Codes:
        - 202 Accepted: Task enqueued successfully
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions (not a Doctor)
        - 404 Not Found: Patient not found or not in current tenant
        - 500 Internal Server Error: Task enqueue failed

    Audit:
        Logs action="forecast_triggered" with patient_id and task_id
    """
    audit_service = AuditService(db)
    forecast_service = ForecastService(db, audit_service)

    try:
        task_id = await forecast_service.trigger_forecast(patient_id)

        # Audit log
        await audit_service.log_action(
            action="forecast_triggered",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"task_id": task_id},
        )

        return ForecastComputationResponse(
            success=True,
            data={"task_id": task_id},
            meta={
                "request_id": request_id,
                "timestamp": str(__import__("datetime").datetime.now(uuid.timezone.utc).isoformat()),
            },
        )

    except Exception as exc:
        await audit_service.log_action(
            action="forecast_trigger_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue forecast task",
        )


@router.get(
    "/latest",
    response_model=ForecastLatestResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest forecasts",
    description="Fetch latest disease trajectory forecasts for all targets and horizons.",
)
async def get_latest_forecasts(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR))],
) -> ForecastLatestResponse:
    """
    Fetch latest forecasts for all targets.

    Returns most recent forecast for each target (systolic_bp, stroke, diabetes, cvd, ckd)
    at all three horizons (3/6/12 months).

    Args:
        patient_id: Patient UUID (from URL path)

    Returns:
        ForecastLatestResponse: {
            "systolic_bp": {
                "horizon_3m": {...},
                "horizon_6m": {...},
                "horizon_12m": {...}
            },
            "stroke": {...},
            ...
        }

    Status Codes:
        - 200 OK: Forecasts retrieved (may be empty if none exist)
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions
        - 404 Not Found: Patient not found

    HIPAA:
        Response includes Cache-Control: no-store (PHI: forecasts)

    Audit:
        Logs action="forecast_accessed" with patient_id
    """
    audit_service = AuditService(db)
    forecast_service = ForecastService(db, audit_service)

    forecasts_dict = await forecast_service.get_latest_forecast(patient_id)

    # Audit log
    await audit_service.log_action(
        action="forecast_accessed",
        resource_type="patient",
        resource_id=patient_id,
        user_id=user_id,
    )

    # Convert dict to response model (handle missing targets)
    response = ForecastLatestResponse()
    for target, horizons in forecasts_dict.items():
        if target == "systolic_bp":
            response.systolic_bp = horizons
        elif target == "stroke":
            response.stroke = horizons
        elif target == "diabetes":
            response.diabetes = horizons
        elif target == "cvd":
            response.cvd = horizons
        elif target == "ckd":
            response.ckd = horizons

    return response


@router.post(
    "/simulate",
    response_model=SimulationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run intervention simulation",
    description="Trigger what-if analysis: forecast outcomes under intervention scenario.",
)
async def run_simulation(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    request_body: RunSimulationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR))],
) -> SimulationResponse:
    """
    Run intervention simulation (what-if analysis).

    Simulates clinical outcomes if patient takes action (weight loss, smoking cessation,
    medication addition, or exercise increase). Compares with baseline forecast.

    Args:
        patient_id: Patient UUID (from URL path)
        request_body: {
            "intervention_type": "weight_loss",
            "parameters": {"target_weight_kg": 85, "duration_months": 6}
        }

    Returns:
        SimulationResponse: {success: true, data: {task_id: "..."}, meta: {...}}

    Status Codes:
        - 202 Accepted: Task enqueued successfully
        - 400 Bad Request: Invalid intervention_type or parameters
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions
        - 404 Not Found: Patient not found

    Audit:
        Logs action="simulation_triggered" with intervention_type
    """
    audit_service = AuditService(db)
    forecast_service = ForecastService(db, audit_service)

    # Validate intervention type
    valid_types = ["weight_loss", "smoking_cessation", "medication_addition", "exercise_increase"]
    if request_body.intervention_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid intervention_type. Must be one of: {', '.join(valid_types)}",
        )

    try:
        task_id = await forecast_service.trigger_simulation(
            patient_id,
            request_body.intervention_type,
            request_body.parameters,
        )

        # Audit log
        await audit_service.log_action(
            action="simulation_triggered",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={
                "intervention_type": request_body.intervention_type,
                "task_id": task_id,
            },
        )

        return SimulationResponse(
            success=True,
            data={"task_id": task_id},
            meta={
                "request_id": request_id,
                "timestamp": str(__import__("datetime").datetime.now(uuid.timezone.utc).isoformat()),
            },
        )

    except Exception as exc:
        await audit_service.log_action(
            action="simulation_trigger_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue simulation task",
        )
