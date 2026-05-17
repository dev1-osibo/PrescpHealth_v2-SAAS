"""
PrescpHealth Backend — Patient API Router.

REST endpoints for patient profile management:
- POST /api/v1/patients — create patient (Doctor+)
- GET /api/v1/patients — list/search patients (Nurse+)
- GET /api/v1/patients/{id} — get single patient (Nurse+)
- PUT /api/v1/patients/{id} — update patient (Doctor+)
- DELETE /api/v1/patients/{id} — soft delete (Doctor+)
- POST /api/v1/patients/{id}/restore — restore (Doctor+)
- GET /api/v1/patients/{id}/versions — version history (Nurse+)
- GET /api/v1/patients/{id}/versions/{version_number} — specific version (Nurse+)
- GET /api/v1/patients/{id}/timeline — patient timeline (Nurse+)

Access Control:
- Nurse+: Read access (list, get, versions, timeline)
- Doctor+: Write access (create, update, delete, restore)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- Never logs PHI — only patient_id UUID in log messages
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
from app.modules.patients.router_helpers import (
    serialize_patient,
    serialize_version,
)
from app.modules.patients.schemas import PatientCreate, PatientUpdate
from app.modules.patients.search import PatientSearchFilters
from app.modules.patients.service import PatientService

# ---------------------------------------------------------------------------
# Module logger — logs patient API access without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition — patient CRUD + versioning + timeline
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/api/v1/patients",
    tags=["patients"],
)

# Shared service instance (stateless, safe to reuse)
_patient_service = PatientService()

# ---------------------------------------------------------------------------
# HIPAA header constant — applied to every response containing PHI
# ---------------------------------------------------------------------------
_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


# ---------------------------------------------------------------------------
# POST /api/v1/patients — Create a new patient
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=None,
    status_code=201,
    summary="Create a new patient",
    description="Creates a new patient record. Requires Doctor role or above. "
    "Creates version 1 and logs to audit trail.",
)
async def create_patient(
    request: Request,
    body: PatientCreate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """
    Create a new patient record with initial version.

    Validates input via PatientCreate schema, delegates to PatientService,
    and returns the created patient in the standard envelope format.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Convert schema to dict, excluding None values for optional fields
        patient_data = body.model_dump(exclude_none=True)

        patient = await _patient_service.create_patient(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            user_id=uuid.UUID(str(user_id)),
            data=patient_data,
        )

        item = serialize_patient(patient)

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
# GET /api/v1/patients — List/search patients (paginated)
# ---------------------------------------------------------------------------
@router.get(
    "",
    response_model=None,
    summary="List or search patients",
    description="Returns a paginated list of patients with optional filters. "
    "Supports name search, MRN lookup, status filter, and date range. "
    "Requires Nurse role or above.",
)
async def list_patients(
    request: Request,
    pagination: PaginationParams = Depends(get_pagination),
    name: Optional[str] = Query(None, description="Partial name search"),
    mrn: Optional[str] = Query(None, description="Partial MRN search"),
    status: Optional[str] = Query(None, description="Filter by status"),
    created_after: Optional[datetime] = Query(None, description="Created after (UTC)"),
    created_before: Optional[datetime] = Query(None, description="Created before (UTC)"),
    include_deleted: bool = Query(False, description="Include soft-deleted patients"),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    List patients with search filters and cursor-based pagination.

    Results ordered by created_at DESC (newest first).
    RLS ensures only the current tenant's patients are returned.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    # Build search filters from query parameters
    from app.modules.patients.models import PatientStatus as PS

    status_enum = None
    if status:
        try:
            status_enum = PS(status)
        except ValueError:
            pass  # Invalid status ignored — returns unfiltered

    filters = PatientSearchFilters(
        name_query=name,
        mrn_query=mrn,
        status=status_enum,
        created_after=created_after,
        created_before=created_before,
        include_deleted=include_deleted,
    )

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        result = await _patient_service.search_patients(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            filters=filters,
            pagination=pagination,
        )

        items = [serialize_patient(p) for p in result.items]

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
# Import sub-modules to register their routes on this router instance.
# These imports MUST be at the bottom to avoid circular import issues
# (sub-modules import `router` from this file).
# ---------------------------------------------------------------------------
from app.modules.patients import router_detail  # noqa: E402, F401
from app.modules.patients import router_versions  # noqa: E402, F401
