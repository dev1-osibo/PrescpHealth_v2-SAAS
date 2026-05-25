"""
PrescpHealth Backend — Measurement API Router (Main).

REST endpoints for clinical measurement management:
- POST /api/v1/patients/{patient_id}/measurements — save single measurement
- POST /api/v1/patients/{patient_id}/measurements/bulk — bulk import
- GET /api/v1/patients/{patient_id}/measurements — list/history (filtered)
- GET /api/v1/patients/{patient_id}/measurements/latest — latest of each type

Access Control:
- Patient_User+: Can POST measurements (self-report via patient_portal)
- Nurse+: Read access (list, history, latest)
- Doctor+: Bulk import (higher trust level for batch operations)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- Never logs PHI — only measurement_id UUID and type in log messages
- RLS enforces tenant isolation at database level
- All mutations create audit trail entries

Per API design steering rule:
- Standard response envelope (success, data, meta with request_id)
- Cursor-based pagination for list endpoints
- Consistent error format with machine-readable codes
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.core.pagination import PaginationParams, get_pagination
from app.modules.auth.rbac import Role, require_role
from app.modules.measurements.history import HistoryFilters
from app.modules.measurements.router_helpers import serialize_measurement
from app.modules.measurements.schemas import BulkImportRequest, MeasurementCreate
from app.modules.measurements.service import MeasurementService

# ---------------------------------------------------------------------------
# Module logger — logs measurement API access without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition — measurement CRUD for patient-scoped endpoints
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/api/v1/patients/{patient_id}/measurements",
    tags=["measurements"],
)

# Shared service instance (stateless, safe to reuse)
_measurement_service = MeasurementService()

# ---------------------------------------------------------------------------
# HIPAA header constant — applied to every response containing PHI
# ---------------------------------------------------------------------------
_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


# ---------------------------------------------------------------------------
# POST /api/v1/patients/{patient_id}/measurements — Save single measurement
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=None,
    status_code=201,
    summary="Record a clinical measurement",
    description="Saves a single measurement for a patient. Patient_User can "
    "self-report (source=patient_portal, requires clinician validation). "
    "Clinicians (Nurse+) can record directly (auto-validated).",
)
async def create_measurement(
    request: Request,
    patient_id: uuid.UUID,
    body: MeasurementCreate,
    auth_context: dict = Depends(require_role(Role.PATIENT_USER)),
) -> JSONResponse:
    """
    Record a single clinical measurement for a patient.

    Validates input via MeasurementCreate schema, delegates to
    MeasurementService which handles physiological validation,
    idempotency, deviation detection, and audit logging.

    Patient_User submissions default to is_validated=False and
    require clinician approval before affecting risk scores.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Build data dict for the service layer
        measurement_data = body.model_dump(exclude_none=True)

        measurement = await _measurement_service.save_measurement(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            patient_id=patient_id,
            user_id=uuid.UUID(str(user_id)),
            data=measurement_data,
        )

        item = serialize_measurement(measurement)

    logger.info(
        "measurement_created",
        measurement_id=item["id"],
        measurement_type=item["measurement_type"],
        patient_id=str(patient_id),
    )

    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "data": item,
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/patients/{patient_id}/measurements/bulk — Bulk import
# ---------------------------------------------------------------------------
@router.post(
    "/bulk",
    response_model=None,
    status_code=200,
    summary="Bulk import measurements",
    description="Import multiple measurements for a patient. Each row is "
    "validated independently — valid rows succeed, invalid rows are "
    "reported in the error summary. Requires Doctor role or above.",
)
async def bulk_import_measurements(
    request: Request,
    patient_id: uuid.UUID,
    body: BulkImportRequest,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """
    Bulk import measurements for a patient.

    Delegates to MeasurementService.bulk_import which processes each
    row independently. Source is forced to 'import' for all rows.
    Duplicates are skipped (idempotent), invalid rows reported.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Convert Pydantic models to dicts for the service layer
        measurements_list = [
            item.model_dump(exclude_none=True) for item in body.measurements
        ]

        result = await _measurement_service.bulk_import(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            patient_id=patient_id,
            user_id=uuid.UUID(str(user_id)),
            measurements_list=measurements_list,
        )

    logger.info(
        "bulk_import_completed",
        patient_id=str(patient_id),
        created=result.created,
        skipped=result.skipped_duplicates,
        errors=len(result.errors),
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": result.to_dict(),
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Import sub-modules to register their routes on this router instance.
# These imports MUST be at the bottom to avoid circular import issues
# (sub-modules import `router` from this file).
# ---------------------------------------------------------------------------
from app.modules.measurements import router_list  # noqa: E402, F401
from app.modules.measurements import router_detail  # noqa: E402, F401
