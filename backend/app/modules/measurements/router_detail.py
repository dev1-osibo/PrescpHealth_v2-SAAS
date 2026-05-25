"""
PrescpHealth Backend — Measurement Detail Router.

Handles single-measurement endpoints that use measurement_id:
- GET /api/v1/measurements/{measurement_id} — get single measurement
- PATCH /api/v1/measurements/{measurement_id}/validate — clinician validates

These endpoints are NOT nested under /patients/{patient_id} because they
operate on a specific measurement by its own UUID (no patient context needed
in the URL — RLS handles tenant scoping).

Split from the main router for modularity (~150 line max per file rule).

Access Control:
- Nurse+: Read single measurement
- Nurse+: Validate measurement (Patient_User CANNOT validate)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- RLS enforces tenant isolation at database level
- Never logs measurement values — only measurement_id and type
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.measurements.exceptions import MeasurementNotFoundError
from app.modules.measurements.models import Measurement
from app.modules.measurements.router import _HIPAA_HEADERS, _measurement_service
from app.modules.measurements.router_helpers import serialize_measurement

# ---------------------------------------------------------------------------
# Module logger — logs measurement detail access without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Separate router for measurement-id-scoped endpoints
# These are NOT nested under /patients/{patient_id} — they use measurement_id
# ---------------------------------------------------------------------------
detail_router = APIRouter(
    prefix="/api/v1/measurements",
    tags=["measurements"],
)


# ---------------------------------------------------------------------------
# GET /api/v1/measurements/{measurement_id} — Get single measurement
# ---------------------------------------------------------------------------
@detail_router.get(
    "/{measurement_id}",
    response_model=None,
    summary="Get a single measurement",
    description="Retrieve a specific measurement by its UUID. "
    "RLS ensures the measurement is only visible within the "
    "requesting user's tenant. Requires Nurse role or above.",
)
async def get_measurement(
    request: Request,
    measurement_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Get a single measurement by ID.

    Returns 404 if the measurement doesn't exist or belongs to a
    different tenant (RLS hides cross-tenant data — always 404,
    never 403, to prevent tenant enumeration attacks).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Query measurement by ID (RLS filters by tenant automatically)
        query = select(Measurement).where(Measurement.id == measurement_id)
        result = await db.execute(query)
        measurement = result.scalar_one_or_none()

        if measurement is None:
            raise MeasurementNotFoundError(measurement_id)

        item = serialize_measurement(measurement)

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
# PATCH /api/v1/measurements/{measurement_id}/validate — Clinician validates
# ---------------------------------------------------------------------------
@detail_router.patch(
    "/{measurement_id}/validate",
    response_model=None,
    summary="Validate a measurement",
    description="Clinician marks a measurement as validated. Required for "
    "Patient_User submissions before they affect risk scores. "
    "Only Nurse+ roles can validate (Patient_User cannot).",
)
async def validate_measurement(
    request: Request,
    measurement_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """
    Mark a measurement as validated by a clinician.

    Sets is_validated=True, validated_by=user_id, validated_at=now().
    Only clinician roles (Nurse, Doctor, Clinic_Admin, Super_Admin)
    can validate. Patient_User is forbidden by the require_role check.

    This is a prerequisite for Patient_User measurements to be included
    in risk score computation (Requirement 5.4).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]
    user_role = auth_context["role_str"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        measurement = await _measurement_service.validate_measurement(
            db=db,
            measurement_id=measurement_id,
            user_id=uuid.UUID(str(user_id)),
            user_role=user_role,
        )

        item = serialize_measurement(measurement)

    logger.info(
        "measurement_validated",
        measurement_id=str(measurement_id),
        validated_by=str(user_id),
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": item,
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )
