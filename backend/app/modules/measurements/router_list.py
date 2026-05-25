"""
PrescpHealth Backend — Measurement List/History Router.

Handles read-only list endpoints for measurements:
- GET /api/v1/patients/{patient_id}/measurements — history with filters
- GET /api/v1/patients/{patient_id}/measurements/latest — latest per type

These endpoints are split from the main router for modularity
(~150 line max per file rule).

Access Control:
- Nurse+: All read endpoints (list, history, latest)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- RLS enforces tenant isolation at database level
- Never logs measurement values — only patient_id and type
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.core.pagination import PaginationParams, get_pagination
from app.modules.auth.rbac import Role, require_role
from app.modules.measurements.history import HistoryFilters
from app.modules.measurements.models import MeasurementType
from app.modules.measurements.router import _HIPAA_HEADERS, _measurement_service, router
from app.modules.measurements.router_helpers import serialize_measurement

# ---------------------------------------------------------------------------
# Module logger — logs measurement query access without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/measurements — List/history
# ---------------------------------------------------------------------------
@router.get(
    "",
    response_model=None,
    summary="List measurement history",
    description="Returns paginated measurement history for a patient. "
    "Supports filtering by type, date range, validated-only, and "
    "flagged-only. Requires Nurse role or above.",
)
async def list_measurements(
    request: Request,
    patient_id: uuid.UUID,
    pagination: PaginationParams = Depends(get_pagination),
    measurement_type: Optional[str] = Query(
        None, description="Filter by measurement type (e.g., systolic_bp)"
    ),
    date_from: Optional[datetime] = Query(
        None, description="Only measurements recorded on or after (UTC)"
    ),
    date_to: Optional[datetime] = Query(
        None, description="Only measurements recorded on or before (UTC)"
    ),
    validated_only: bool = Query(
        False, description="Only return clinician-validated measurements"
    ),
    flagged_only: bool = Query(
        False, description="Only return flagged measurements (>2σ deviation)"
    ),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    List measurement history with optional filters and cursor pagination.

    If measurement_type is provided, returns time-series for that type.
    If omitted, returns all measurement types (mixed) ordered by recorded_at.
    Results ordered by recorded_at DESC (newest first).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    # Build history filters from query parameters
    filters = HistoryFilters(
        date_from=date_from,
        date_to=date_to,
        validated_only=validated_only,
        flagged_only=flagged_only,
    )

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Validate measurement_type if provided
        type_filter = measurement_type
        if type_filter:
            try:
                MeasurementType(type_filter)
            except ValueError:
                # Invalid type — return empty result rather than error
                # (prevents information leakage about valid types)
                type_filter = None

        result = await _measurement_service.get_measurement_history(
            db=db,
            patient_id=patient_id,
            measurement_type=type_filter or "",
            pagination=pagination,
            filters=filters,
        )

        items = [serialize_measurement(m) for m in result.items]

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "items": items,
                "cursor": result.cursor,
                "has_more": result.has_more,
            },
            "meta": {
                "request_id": request_id,
                "pagination": result.to_meta(),
            },
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/measurements/latest — Latest per type
# ---------------------------------------------------------------------------
@router.get(
    "/latest",
    response_model=None,
    summary="Get latest measurement of each type",
    description="Returns the most recent measurement of each type for a "
    "patient. Used by the risk engine for feature extraction and by "
    "the frontend for the patient dashboard summary.",
)
async def get_latest_measurements(
    request: Request,
    patient_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Get the most recent measurement of each type for a patient.

    Returns one measurement per type that has data. Types with no
    measurements are simply absent from the response.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        measurements = await _measurement_service.get_latest_measurements(
            db=db,
            patient_id=patient_id,
        )

        items = [serialize_measurement(m) for m in measurements]

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {"items": items},
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )
