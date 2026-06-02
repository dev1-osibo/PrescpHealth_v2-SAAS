"""
PrescpHealth Backend — Population Analytics FastAPI Router.

Exposes three HIPAA-compliant endpoints for population-level risk analytics.
All responses set Cache-Control: no-store to prevent PHI caching even though
the data is aggregate; tenant-scoped data must not be cached in shared layers.

RBAC: All endpoints require Doctor or Clinic_Admin role.
"""
import uuid
import structlog
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.core.audit import AuditService
from app.modules.auth.rbac import Role, require_role
from app.modules.population_staging.exceptions import ComputationError, PopulationError
from app.modules.population_staging.schemas import (
    DashboardEnvelope,
    TrendsResponse,
    WatchlistResponse,
)
from app.modules.population_staging.service import PopulationService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["population"])

_NO_STORE = "no-store"
_VALID_WINDOWS = {"1m", "3m", "6m", "12m"}


def _build_service(
    db: AsyncSession,
    current_user: dict,
    request_id: str,
) -> PopulationService:
    """Construct PopulationService with all required dependencies."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    audit_service = AuditService(db=db, tenant_id=tenant_id)
    return PopulationService(
        db=db,
        audit_service=audit_service,
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _meta(request_id: str, **extras) -> dict:
    """Build a standard response meta block with optional extra fields."""
    return {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extras,
    }


@router.get(
    "/api/v1/population/dashboard",
    response_model=DashboardEnvelope,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.CLINIC_ADMIN))],
    summary="Population risk dashboard metrics",
)
async def get_dashboard(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> DashboardEnvelope:
    """
    Return aggregate risk distribution, high/critical counts, and per-disease
    average scores for the current tenant's active patient population.

    PHI: aggregate data only; no individual records surfaced.
    Cache-Control: no-store — tenant-scoped aggregate data must not be cached.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)
    try:
        data = await svc.get_dashboard_metrics()
        return DashboardEnvelope(data=data, meta=_meta(request_id))
    except PopulationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error(
            "population_dashboard_error",
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard metrics",
        )


@router.get(
    "/api/v1/population/watchlist",
    response_model=WatchlistResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.CLINIC_ADMIN))],
    summary="High/Critical risk patient watchlist",
)
async def get_watchlist(
    response: Response,
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    sort_by: str = Query("score", description="Sort column (currently: score)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> WatchlistResponse:
    """
    Return a paginated list of patients whose latest risk stratum is High or Critical.
    Ordered by risk score descending by default.

    Cache-Control: no-store — list contains patient UUIDs (PHI adjacent).
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)
    try:
        patients = await svc.get_watchlist(limit=limit, offset=offset, sort_by=sort_by)
        return WatchlistResponse(
            data=patients,
            meta=_meta(request_id, total=len(patients), limit=limit, offset=offset),
        )
    except PopulationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error(
            "population_watchlist_error",
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve watchlist",
        )


@router.get(
    "/api/v1/population/trends",
    response_model=TrendsResponse,
    dependencies=[Depends(require_role(Role.DOCTOR, Role.CLINIC_ADMIN))],
    summary="Population risk score trends",
)
async def get_trends(
    response: Response,
    window: str = Query("3m", description="Time window: 1m | 3m | 6m | 12m"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> TrendsResponse:
    """
    Return monthly average risk score trends per disease for the given rolling window.

    Valid windows: 1m (1 month), 3m (3 months), 6m (6 months), 12m (12 months).
    Cache-Control: no-store — tenant-scoped aggregate data must not be cached.
    """
    response.headers["Cache-Control"] = _NO_STORE

    if window not in _VALID_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid window '{window}'. Must be one of: {sorted(_VALID_WINDOWS)}",
        )

    svc = _build_service(db, current_user, request_id)
    try:
        trends = await svc.get_trends(window=window)
        return TrendsResponse(
            data=trends,
            meta=_meta(request_id, window=window),
        )
    except ComputationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error(
            "population_trends_error",
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve trend data",
        )
