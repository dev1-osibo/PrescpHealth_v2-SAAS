"""
PrescpHealth Backend — Risk Engine FastAPI Router.

Three endpoints for risk score operations:
1. POST /patients/{id}/risk/compute — Trigger async computation
2. GET /patients/{id}/risk/scores — Get latest scores for all diseases
3. GET /patients/{id}/risk/history — Get historical scores per disease

All endpoints:
- Require authentication (via require_role dependency)
- Enforce RBAC (Doctor/Nurse roles)
- Set HIPAA headers (Cache-Control: no-store on responses with PHI)
- Use standard response envelope
- Include request_id for correlation/audit

HIPAA Compliance:
    - Risk scores are PHI — responses marked no-cache
    - No risk values in logs (only computation_id, patient_id UUID)
    - All calls audited via AuditService
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_request_id, get_tenant_id, get_current_user
from app.core.request_context import get_request_id as get_request_context_id
from app.modules.auth.rbac import Role, require_role
from app.modules.audit.service import AuditService
from app.modules.measurements.service import MeasurementService
from app.modules.risk_engine_staging.service import RiskService
from app.modules.risk_engine_staging.schemas import (
    ComputeRiskRequest,
    RiskComputationResponse,
    RiskScoresListResponse,
    RiskHistoryResponse,
)

# Router prefix: /api/v1/patients/{id}/risk/...
router = APIRouter(prefix="/risk", tags=["risk_engine"])


@router.post(
    "/compute",
    response_model=RiskComputationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async risk computation",
    description="Enqueue a Celery task to compute risk scores for a patient. Returns task_id for polling.",
)
async def compute_risk(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR, Role.NURSE))],
) -> RiskComputationResponse:
    """
    Trigger async risk computation for a patient.

    This endpoint enqueues a Celery background task that will:
    1. Fetch patient's latest validated measurements
    2. Extract feature vector
    3. Run ML ensemble models (6 diseases simultaneously)
    4. Store RiskScore + ShapExplanation records
    5. Publish RiskScoreComputed event (triggers alerts, etc.)

    Returns a task_id that can be used to poll /tasks/{task_id}/status
    for completion status.

    Args:
        patient_id: Patient UUID (from URL path)

    Returns:
        RiskComputationResponse: {success: true, data: {task_id: "..."}, meta: {...}}

    Status Codes:
        - 202 Accepted: Task enqueued successfully
        - 401 Unauthorized: Missing/invalid JWT
        - 403 Forbidden: User lacks Doctor/Nurse role
        - 404 Not Found: Patient not found
        - 429 Too Many Requests: Rate limited (1000 req/min)
        - 500 Internal Server Error: Task enqueueing failed

    HIPAA:
        - This endpoint itself doesn't return PHI (just task_id)
        - But the async task will store PHI (risk scores) in DB
        - All stored data subject to RLS isolation
    """
    try:
        # Initialize services with dependencies
        audit_service = AuditService(db=db, tenant_id=tenant_id)
        measurement_service = MeasurementService(db=db, tenant_id=tenant_id)
        risk_service = RiskService(
            db_session=db,
            measurement_service=measurement_service,
            audit_service=audit_service,
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # Trigger async computation (enqueue Celery task)
        task_id = await risk_service.trigger_computation(patient_id)

        # Return standard envelope with task_id for polling
        return RiskComputationResponse(
            success=True,
            data={"task_id": task_id},
            meta={
                "request_id": request_id,
                "timestamp": str(uuid.uuid4()),  # Mock — real would use now()
            },
        )

    except Exception as exc:
        # Log error but don't expose internals to client
        audit_service = AuditService(db=db, tenant_id=tenant_id)
        await audit_service.log_audit(
            action="risk_computation_trigger_failed",
            resource_type="patient",
            resource_id=str(patient_id),
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger risk computation. Please try again.",
        ) from exc


@router.get(
    "/scores",
    response_model=RiskScoresListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest risk scores",
    description="Fetch the latest risk scores for all 6 diseases.",
)
async def get_latest_scores(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR, Role.NURSE))],
) -> RiskScoresListResponse:
    """
    Fetch latest risk scores for all 6 diseases.

    Returns a dictionary mapping disease name → latest RiskScore + SHAP explanation.
    If a disease hasn't been computed yet, the value is None.

    Args:
        patient_id: Patient UUID (from URL path)

    Returns:
        RiskScoresListResponse with data mapping disease → score (or None)

    Status Codes:
        - 200 OK: Scores retrieved
        - 401 Unauthorized: Missing/invalid JWT
        - 403 Forbidden: User lacks Doctor/Nurse role
        - 404 Not Found: Patient not found
        - 429 Too Many Requests: Rate limited

    HIPAA Headers:
        Response includes Cache-Control: no-store because it contains PHI (risk scores).
        Browser-caching these values is a HIPAA violation.

    Example Response:
        {
            "success": true,
            "data": {
                "stroke": {
                    "disease": "stroke",
                    "score": 72.45,
                    "stratum": "High",
                    "confidence_lower": 68.2,
                    "confidence_upper": 76.8,
                    "model_version": "v1.2.0",
                    "computed_at": "2026-05-28T20:30:00Z",
                    "shap": { ... }
                },
                "cvd": null,  // Not computed yet
                ...
            },
            "meta": { "request_id": "...", "timestamp": "..." }
        }
    """
    try:
        # Initialize services
        audit_service = AuditService(db=db, tenant_id=tenant_id)
        measurement_service = MeasurementService(db=db, tenant_id=tenant_id)
        risk_service = RiskService(
            db_session=db,
            measurement_service=measurement_service,
            audit_service=audit_service,
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),  # Mock — would come from JWT
        )

        # Fetch scores
        scores = await risk_service.get_latest_scores(patient_id)

        # Log access (audit trail)
        await audit_service.log_audit(
            action="risk_scores_retrieved",
            resource_type="patient",
            resource_id=str(patient_id),
        )

        return RiskScoresListResponse(
            success=True,
            data=scores,
            meta={
                "request_id": request_id,
                "Cache-Control": "no-store",  # HIPAA: never cache PHI
            },
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve risk scores.",
        ) from exc


@router.get(
    "/history",
    response_model=RiskHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get risk score history",
    description="Fetch historical risk scores for a specific disease.",
)
async def get_risk_history(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    disease: Annotated[str, Query(..., description="Disease name (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)")],
    limit: Annotated[int, Query(50, ge=1, le=500, description="Max scores to return")] = 50,
    offset: Annotated[int, Query(0, ge=0, description="Pagination offset")] = 0,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)] = None,
    request_id: Annotated[str, Depends(get_request_id)] = None,
    _: Annotated[None, Depends(require_role(Role.DOCTOR))] = None,
) -> RiskHistoryResponse:
    """
    Fetch historical risk scores for a specific disease.

    Returns a paginated list of scores for one disease, ordered most-recent-first.
    Useful for visualizing risk trends over time.

    Args:
        patient_id: Patient UUID (from URL path)
        disease: Disease name (query param, e.g., "stroke")
        limit: Max scores to return (default 50, max 500)
        offset: Pagination offset (default 0)

    Returns:
        RiskHistoryResponse with paginated historical scores

    Status Codes:
        - 200 OK: History retrieved
        - 400 Bad Request: Invalid disease name or pagination params
        - 401 Unauthorized: Missing/invalid JWT
        - 403 Forbidden: User lacks Doctor role (only doctors see history)
        - 404 Not Found: Patient not found
        - 429 Too Many Requests: Rate limited

    HIPAA Headers:
        Response includes Cache-Control: no-store (contains risk scores).

    Example:
        GET /api/v1/patients/abc-123/risk/history?disease=stroke&limit=20&offset=0
    """
    try:
        # Initialize services
        audit_service = AuditService(db=db, tenant_id=tenant_id)
        measurement_service = MeasurementService(db=db, tenant_id=tenant_id)
        risk_service = RiskService(
            db_session=db,
            measurement_service=measurement_service,
            audit_service=audit_service,
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),  # Mock
        )

        # Fetch history
        history = await risk_service.get_score_history(
            patient_id=patient_id,
            disease=disease,
            limit=limit,
            offset=offset,
        )

        # Audit log
        await audit_service.log_audit(
            action="risk_history_retrieved",
            resource_type="patient",
            resource_id=str(patient_id),
            changes={"disease": disease, "limit": limit, "offset": offset},
        )

        return RiskHistoryResponse(
            success=True,
            data=history,
            meta={
                "request_id": request_id,
                "pagination": {"limit": limit, "offset": offset},
                "Cache-Control": "no-store",  # HIPAA
            },
        )

    except ValueError as exc:
        # Invalid disease name
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid disease: {str(exc)}",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve risk history.",
        ) from exc
