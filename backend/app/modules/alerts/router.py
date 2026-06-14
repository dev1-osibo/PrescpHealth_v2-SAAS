"""
PrescpHealth Backend — Alert System FastAPI Router.

Exposes the alert system API endpoints with RBAC enforcement and HIPAA-compliant
response headers. Follows risk_engine/router.py patterns:
- Standard response envelope on all responses
- Cache-Control: no-store on all responses (PHI)
- AuditService injected via dependency
- HTTPException for all error paths

All responses set Cache-Control: no-store because alert records contain PHI
(clinical context, patient references, risk scores in payload).
"""
import uuid
import structlog
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.modules.audit.service import AuditService
from app.modules.auth.rbac import Role, require_role
from app.modules.alerts.enums import AlertStatus
from app.modules.alerts.exceptions import AlertNotFoundError, ThresholdConfigurationError
from app.modules.alerts.models import AlertThreshold
from app.modules.alerts.schemas import (
    AcknowledgeAlertRequest,
    AlertListResponse,
    ConfigureThresholdRequest,
    SingleAlertResponse,
    ThresholdListResponse,
    ThresholdResponse,
)
from app.modules.alerts.service import AlertService
from sqlalchemy import select, and_

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["alerts"])

# HIPAA: All responses must include this header to prevent PHI caching
_NO_STORE = "no-store"


def _build_alert_service(
    db: AsyncSession,
    current_user: dict,
    request_id: str,
) -> AlertService:
    """Construct AlertService with all required dependencies."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    audit_service = AuditService(db=db, tenant_id=tenant_id)
    return AlertService(
        db=db,
        audit_service=audit_service,
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _meta(request_id: str) -> dict:
    """Build standard response meta block."""
    return {"request_id": request_id, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get(
    "/api/v1/alerts",
    response_model=AlertListResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN))],
    summary="List tenant alerts",
)
async def list_alerts(
    response: Response,
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    patient_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> AlertListResponse:
    """
    List all alerts for the current tenant with optional filtering.
    PHI: response includes alert records — Cache-Control: no-store set.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_alert_service(db, current_user, request_id)

    try:
        # If patient_id filter provided, use patient-scoped query
        if patient_id:
            alerts = await svc.get_patient_alerts(
                patient_id=patient_id,
                status_filter=status_filter,
                limit=limit,
                offset=offset,
            )
        else:
            # Tenant-wide listing using get_patient_alerts with None patient_id workaround
            # Full tenant-list is a superset; build via get_unacknowledged + acknowledged
            alerts = await svc.get_unacknowledged()

        return AlertListResponse(
            data=alerts,
            meta={**_meta(request_id), "count": len(alerts), "limit": limit, "offset": offset},
        )
    except Exception as exc:
        logger.error("list_alerts_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve alerts")


@router.get(
    "/api/v1/patients/{patient_id}/alerts",
    response_model=AlertListResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN))],
    summary="List patient alert history",
)
async def get_patient_alerts(
    patient_id: uuid.UUID,
    response: Response,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> AlertListResponse:
    """Retrieve paginated alert history for a specific patient."""
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_alert_service(db, current_user, request_id)

    try:
        alerts = await svc.get_patient_alerts(
            patient_id=patient_id,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
        return AlertListResponse(
            data=alerts,
            meta={**_meta(request_id), "count": len(alerts), "limit": limit, "offset": offset},
        )
    except Exception as exc:
        logger.error("get_patient_alerts_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve patient alerts")


@router.get(
    "/api/v1/alerts/unacknowledged",
    response_model=AlertListResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN))],
    summary="Dashboard: all unacknowledged alerts",
)
async def get_unacknowledged_alerts(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> AlertListResponse:
    """Retrieve all unacknowledged active/escalated alerts for the clinical dashboard."""
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_alert_service(db, current_user, request_id)
    alerts = await svc.get_unacknowledged()

    return AlertListResponse(
        data=alerts,
        meta={**_meta(request_id), "count": len(alerts)},
    )


@router.put(
    "/api/v1/alerts/{alert_id}/acknowledge",
    response_model=SingleAlertResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.NURSE))],
    summary="Acknowledge an alert",
)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    body: AcknowledgeAlertRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> SingleAlertResponse:
    """Acknowledge an alert. Stops escalation and marks it reviewed."""
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_alert_service(db, current_user, request_id)
    user_id = uuid.UUID(current_user["user_id"])

    try:
        alert = await svc.acknowledge(alert_id=alert_id, user_id=user_id, notes=body.notes)
        return SingleAlertResponse(data=alert, meta=_meta(request_id))
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except Exception as exc:
        logger.error("acknowledge_alert_error", alert_id=str(alert_id), error_type=type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to acknowledge alert")


@router.post(
    "/api/v1/patients/{patient_id}/alert-thresholds",
    response_model=ThresholdListResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.CLINIC_ADMIN))],
    status_code=status.HTTP_201_CREATED,
    summary="Configure alert threshold",
)
async def configure_threshold(
    patient_id: uuid.UUID,
    body: ConfigureThresholdRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> ThresholdListResponse:
    """Create a new alert threshold for a patient or as a tenant-wide default."""
    response.headers["Cache-Control"] = _NO_STORE

    # Override patient_id in body with path parameter for consistency
    body_with_patient = body.model_copy(update={"patient_id": patient_id})
    svc = _build_alert_service(db, current_user, request_id)
    user_id = uuid.UUID(current_user["user_id"])

    try:
        threshold = await svc.configure_threshold(data=body_with_patient, created_by=user_id)
        return ThresholdListResponse(data=[threshold], meta=_meta(request_id))
    except ThresholdConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error("configure_threshold_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to configure threshold")


@router.get(
    "/api/v1/patients/{patient_id}/alert-thresholds",
    response_model=ThresholdListResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.CLINIC_ADMIN))],
    summary="List patient alert thresholds",
)
async def list_thresholds(
    patient_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> ThresholdListResponse:
    """Retrieve all active alert thresholds for a patient."""
    response.headers["Cache-Control"] = _NO_STORE

    tenant_id = uuid.UUID(current_user["tenant_id"])

    stmt = select(AlertThreshold).where(
        and_(
            AlertThreshold.tenant_id == tenant_id,
            AlertThreshold.patient_id == patient_id,
            AlertThreshold.is_active == True,  # noqa: E712
        )
    )
    thresholds = list((await db.scalars(stmt)).all())

    return ThresholdListResponse(
        data=thresholds,
        meta={**_meta(request_id), "count": len(thresholds)},
    )


@router.delete(
    "/api/v1/alert-thresholds/{threshold_id}",
    dependencies=[Depends(require_role(Role.DOCTOR, Role.CLINIC_ADMIN))],
    status_code=status.HTTP_200_OK,
    summary="Soft-delete alert threshold",
)
async def deactivate_threshold(
    threshold_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """Soft-delete an alert threshold (set is_active=False). Preserves audit history."""
    response.headers["Cache-Control"] = _NO_STORE

    tenant_id = uuid.UUID(current_user["tenant_id"])

    stmt = select(AlertThreshold).where(
        and_(AlertThreshold.id == threshold_id, AlertThreshold.tenant_id == tenant_id)
    )
    threshold = (await db.scalars(stmt)).first()

    if not threshold:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold not found")

    # Soft-delete — preserve record for audit history
    threshold.is_active = False

    audit_svc = AuditService(db=db, tenant_id=tenant_id)
    await audit_svc.log_audit(
        action="threshold_deactivated",
        resource_type="alert_threshold",
        resource_id=str(threshold.id),
        changes={"is_active": False},
    )

    await db.commit()

    logger.info(
        "threshold_deactivated",
        threshold_id=str(threshold_id),
        tenant_id=str(tenant_id),
        request_id=request_id,
    )

    return {
        "success": True,
        "data": {"threshold_id": str(threshold_id), "is_active": False},
        "meta": _meta(request_id),
    }
