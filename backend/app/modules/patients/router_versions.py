"""
PrescpHealth Backend — Patient Version & Timeline API Endpoints.

Version history and timeline endpoints:
- GET /api/v1/patients/{id}/versions — all version records
- GET /api/v1/patients/{id}/versions/{version_number} — specific version
- GET /api/v1/patients/{id}/timeline — patient timeline events

These endpoints provide read-only access to the patient's change history.
Version records are immutable — they can never be modified or deleted.

Access Control:
- All endpoints: Nurse+ (read access to version history)

HIPAA Compliance:
- Cache-Control: no-store (version snapshots contain PHI)
- RLS tenant isolation enforced
- Access to version history is audit-logged
"""

import uuid

import structlog
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.patients.router import _HIPAA_HEADERS, _patient_service, router
from app.modules.patients.router_helpers import serialize_version

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/versions — Version history
# ---------------------------------------------------------------------------
@router.get(
    "/{patient_id}/versions",
    response_model=None,
    summary="Get patient version history",
    description="Returns all version records for a patient, ordered newest first. "
    "Each version includes the change type, diff, and full snapshot. "
    "Requires Nurse role or above.",
)
async def get_patient_versions(
    request: Request,
    patient_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Get the complete version history for a patient.

    Returns all PatientVersion records ordered by version_number DESC.
    Each record includes the snapshot at that point in time.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        versions = await _patient_service.get_patient_versions(
            db=db,
            patient_id=patient_id,
        )

        items = [serialize_version(v) for v in versions]

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {"items": items},
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/versions/{version_number}
# ---------------------------------------------------------------------------
@router.get(
    "/{patient_id}/versions/{version_number}",
    response_model=None,
    summary="Get a specific patient version",
    description="Returns the patient state at a specific version number. "
    "Used for point-in-time recovery and audit review. "
    "Requires Nurse role or above.",
)
async def get_patient_version(
    request: Request,
    patient_id: uuid.UUID,
    version_number: int,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Get a specific version of a patient record.

    Returns the full snapshot at that version, enabling point-in-time
    recovery. Returns 404 if the version number doesn't exist.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        version = await _patient_service.get_patient_at_version(
            db=db,
            patient_id=patient_id,
            version_number=version_number,
        )

        item = serialize_version(version)

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
# GET /api/v1/patients/{patient_id}/timeline — Patient timeline
# ---------------------------------------------------------------------------
@router.get(
    "/{patient_id}/timeline",
    response_model=None,
    summary="Get patient timeline",
    description="Returns a chronological list of events for a patient. "
    "Currently includes profile changes. Will be extended with "
    "measurements, risk scores, and alerts. Requires Nurse role or above.",
)
async def get_patient_timeline(
    request: Request,
    patient_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Get the patient timeline as a list of events.

    Returns profile change events ordered newest first.
    Each event includes type, timestamp, and human-readable description.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        timeline = await _patient_service.get_patient_timeline(
            db=db,
            patient_id=patient_id,
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {"items": timeline},
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )
