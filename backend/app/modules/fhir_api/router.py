"""
PrescpHealth Backend — FHIR R4 CRUD Router.

Endpoints:
    GET    /api/v1/fhir/r4/{resourceType}        Search
    GET    /api/v1/fhir/r4/{resourceType}/{id}   Read
    POST   /api/v1/fhir/r4/{resourceType}        Create
    PUT    /api/v1/fhir/r4/{resourceType}/{id}   Update
    POST   /api/v1/fhir/r4/Subscription          Create webhook subscription

RBAC:
    External systems: OAuth 2.0 client credentials (see auth_oauth.py)
    Internal staff: Doctor or Clinic_Admin JWT

HIPAA: Cache-Control: no-store on all responses.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.fhir_api import SUPPORTED_RESOURCES
from app.modules.fhir_api.auth_oauth import OAuthTokenInfo, get_fhir_auth
from app.modules.fhir_api.schemas import SubscriptionIn
from app.modules.fhir_api.search import parse_search_params
from app.modules.fhir_api.service import FHIRService
from app.modules.fhir_api.subscriptions import SubscriptionManager

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["fhir"])

_fhir_svc = FHIRService()
_sub_mgr = SubscriptionManager()

_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Content-Type": "application/fhir+json",
}


def _unsupported_resource(resource_type: str, rid: str) -> JSONResponse:
    """Return 404 OperationOutcome for unsupported resource types."""
    return JSONResponse(
        status_code=404,
        content={
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "not-found",
                        "diagnostics": f"Resource type '{resource_type}' not supported"}],
            "meta": {"request_id": rid},
        },
        headers=_HIPAA_HEADERS,
    )


def _fhir_response(data: Any, status_code: int = 200, request_id: str = "unknown") -> JSONResponse:
    """Wrap a FHIR resource in an HTTP response with HIPAA headers."""
    return JSONResponse(
        status_code=status_code,
        content=data,
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/fhir/r4/{resourceType} — Search
# ---------------------------------------------------------------------------
@router.get("/api/v1/fhir/r4/{resource_type}", summary="FHIR Search")
async def fhir_search(
    request: Request,
    resource_type: str,
    _id: Optional[str] = Query(None),
    patient: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    _count: int = Query(20, ge=1, le=100),
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Search FHIR resources. Doctor+."""
    rid = getattr(request.state, "request_id", "unknown")
    if resource_type not in SUPPORTED_RESOURCES:
        return _unsupported_resource(resource_type, rid)

    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    raw_params: dict[str, str] = {}
    if _id:
        raw_params["_id"] = _id
    if patient:
        raw_params["patient"] = patient
    if status:
        raw_params["status"] = status
    if date:
        raw_params["date"] = date
    if code:
        raw_params["code"] = code
    raw_params["_count"] = str(_count)

    search_params = parse_search_params(resource_type, raw_params)

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        resources, total = await _fhir_svc.search(db, resource_type, search_params, tenant_id)

    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": total,
        "entry": [{"resource": r} for r in resources],
    }
    logger.info("fhir_search", resource_type=resource_type, total=total, tenant_id=str(tenant_id))
    return _fhir_response(bundle, request_id=rid)


# ---------------------------------------------------------------------------
# GET /api/v1/fhir/r4/{resourceType}/{id} — Read
# ---------------------------------------------------------------------------
@router.get("/api/v1/fhir/r4/{resource_type}/{resource_id}", summary="FHIR Read")
async def fhir_read(
    request: Request,
    resource_type: str,
    resource_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Read a FHIR resource by ID. Doctor+."""
    rid = getattr(request.state, "request_id", "unknown")
    if resource_type not in SUPPORTED_RESOURCES:
        return _unsupported_resource(resource_type, rid)

    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        resource = await _fhir_svc.read_resource(db, resource_type, resource_id)

    if resource is None:
        return JSONResponse(
            status_code=404,
            content={"resourceType": "OperationOutcome",
                     "issue": [{"severity": "error", "code": "not-found",
                                 "diagnostics": f"{resource_type}/{resource_id} not found"}]},
            headers=_HIPAA_HEADERS,
        )

    logger.info("fhir_read", resource_type=resource_type,
                resource_id=str(resource_id), tenant_id=str(tenant_id))
    return _fhir_response(resource, request_id=rid)


# ---------------------------------------------------------------------------
# POST /api/v1/fhir/r4/{resourceType} — Create
# ---------------------------------------------------------------------------
@router.post("/api/v1/fhir/r4/{resource_type}", status_code=201, summary="FHIR Create")
async def fhir_create(
    request: Request,
    resource_type: str,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Create a FHIR resource. Doctor+."""
    rid = getattr(request.state, "request_id", "unknown")
    if resource_type not in SUPPORTED_RESOURCES:
        return _unsupported_resource(resource_type, rid)

    # Parse raw body as FHIR JSON
    fhir_json: dict[str, Any] = await request.json()
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    # Validate before persisting
    outcome = _fhir_svc.validate_resource(resource_type, fhir_json)
    if outcome:
        return JSONResponse(status_code=422, content=outcome, headers=_HIPAA_HEADERS)

    # Parse to internal representation
    internal = _fhir_svc.parse_to_internal(resource_type, fhir_json)

    # Assign a server-side ID if not provided
    resource_id = uuid.UUID(fhir_json["id"]) if "id" in fhir_json else uuid.uuid4()
    fhir_json["id"] = str(resource_id)

    # STUB: In production, persist via the relevant module service
    logger.info("fhir_create_stub", resource_type=resource_type,
                resource_id=str(resource_id), tenant_id=str(tenant_id))

    return _fhir_response(fhir_json, status_code=201, request_id=rid)


# ---------------------------------------------------------------------------
# PUT /api/v1/fhir/r4/{resourceType}/{id} — Update
# ---------------------------------------------------------------------------
@router.put("/api/v1/fhir/r4/{resource_type}/{resource_id}", summary="FHIR Update")
async def fhir_update(
    request: Request,
    resource_type: str,
    resource_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Update a FHIR resource. Doctor+."""
    rid = getattr(request.state, "request_id", "unknown")
    if resource_type not in SUPPORTED_RESOURCES:
        return _unsupported_resource(resource_type, rid)

    fhir_json: dict[str, Any] = await request.json()
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    # Validate before updating
    outcome = _fhir_svc.validate_resource(resource_type, fhir_json)
    if outcome:
        return JSONResponse(status_code=422, content=outcome, headers=_HIPAA_HEADERS)

    # Enforce ID consistency: URL id must match resource id
    fhir_json["id"] = str(resource_id)

    # STUB: In production, persist via the relevant module service
    logger.info("fhir_update_stub", resource_type=resource_type,
                resource_id=str(resource_id), tenant_id=str(tenant_id))

    return _fhir_response(fhir_json, request_id=rid)


# ---------------------------------------------------------------------------
# POST /api/v1/fhir/r4/Subscription — Create subscription
# ---------------------------------------------------------------------------
@router.post("/api/v1/fhir/r4/Subscription", status_code=201, summary="Create FHIR Subscription")
async def create_subscription(
    request: Request,
    body: SubscriptionIn,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Register a FHIR webhook subscription. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    try:
        stored = _sub_mgr.create_subscription(body.model_dump(), tenant_id)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"resourceType": "OperationOutcome",
                     "issue": [{"severity": "error", "code": "required",
                                 "diagnostics": str(exc)}]},
            headers=_HIPAA_HEADERS,
        )

    return _fhir_response(stored, status_code=201, request_id=rid)
