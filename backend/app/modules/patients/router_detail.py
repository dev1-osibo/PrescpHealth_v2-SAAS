"""
PrescpHealth Backend — Patient Detail API Endpoints.

Single-patient endpoints split from the main router for modularity:
- GET /api/v1/patients/{id} — get single patient
- PUT /api/v1/patients/{id} — update patient
- DELETE /api/v1/patients/{id} — soft delete
- POST /api/v1/patients/{id}/restore — restore soft-deleted patient

These endpoints operate on a single patient identified by UUID.
All mutations create version records and audit trail entries.

Access Control:
- GET: Nurse+ (read access)
- PUT/DELETE/POST restore: Doctor+ (write access)

HIPAA Compliance:
- Cache-Control: no-store on all responses
- RLS tenant isolation enforced
- Audit logging on all mutations
"""

import uuid

import structlog
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.patients.router import _HIPAA_HEADERS, _patient_service, router
from app.modules.patients.router_helpers import serialize_patient
from app.modules.patients.schemas import PatientUpdate

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id} — Get single patient
# ---------------------------------------------------------------------------
@router.get(
    "/{patient_id}",
    response_model=None,
    summary="Get a single patient",
    description="Returns a single patient record by UUID. "
    "Requires Nurse role or above. RLS ensures tenant isolation.",
)
async def get_patient(
    request: Request,
    patient_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Retrieve a single patient by ID.

    Returns 404 if the patient doesn't exist or belongs to a different
    tenant (RLS makes it invisible, appearing as not found).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        patient = await _patient_service.get_patient(db=db, patient_id=patient_id)
        item = serialize_patient(patient)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": item,
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/patients/{patient_id} — Update patient
# ---------------------------------------------------------------------------
@router.put(
    "/{patient_id}",
    response_model=None,
    summary="Update a patient",
    description="Updates patient fields. Only provided fields are changed. "
    "Creates a version record with diff. Requires Doctor role or above.",
)
async def update_patient(
    request: Request,
    patient_id: uuid.UUID,
    body: PatientUpdate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """
    Update patient fields (partial update).

    Only non-None fields from the request body are applied.
    A version record is created with the diff of changes.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Only include fields that were explicitly set (not None)
        update_data = body.model_dump(exclude_unset=True)

        patient = await _patient_service.update_patient(
            db=db,
            patient_id=patient_id,
            user_id=uuid.UUID(str(user_id)),
            data=update_data,
        )

        item = serialize_patient(patient)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": item,
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/patients/{patient_id} — Soft delete
# ---------------------------------------------------------------------------
@router.delete(
    "/{patient_id}",
    response_model=None,
    summary="Soft delete a patient",
    description="Marks a patient as deleted (sets deleted_at). "
    "HIPAA requires 7-year retention — never hard-deletes. "
    "Requires Doctor role or above.",
)
async def delete_patient(
    request: Request,
    patient_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """
    Soft-delete a patient record.

    Sets deleted_at timestamp. Patient is excluded from search results
    but remains accessible for audit and compliance purposes.
    Returns 409 if already deleted.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        await _patient_service.soft_delete_patient(
            db=db,
            patient_id=patient_id,
            user_id=uuid.UUID(str(user_id)),
        )

    # 204 No Content for successful deletion (per API design steering)
    return JSONResponse(
        status_code=204,
        content=None,
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/patients/{patient_id}/restore — Restore soft-deleted patient
# ---------------------------------------------------------------------------
@router.post(
    "/{patient_id}/restore",
    response_model=None,
    summary="Restore a soft-deleted patient",
    description="Clears the deleted_at timestamp, making the patient "
    "visible in search results again. Requires Doctor role or above.",
)
async def restore_patient(
    request: Request,
    patient_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """
    Restore a soft-deleted patient.

    Clears deleted_at, creates a version record with 'restore' type.
    Returns 409 if the patient isn't currently deleted.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        patient = await _patient_service.restore_patient(
            db=db,
            patient_id=patient_id,
            user_id=uuid.UUID(str(user_id)),
        )

        item = serialize_patient(patient)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": item,
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )
