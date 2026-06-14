"""
Referrals Module — FastAPI Router
===================================
Exposes 5 endpoints for referral creation, listing, status updates,
and specialist completion recording.
All responses include HIPAA-compliant cache headers.
"""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from .schemas import ReferralCreate, ReferralStatusUpdate, ReferralCompletion, ReferralResponse
from .service import ReferralService
from .exceptions import ReferralNotFoundError, InvalidStatusTransitionError

router = APIRouter(tags=["referrals"])
log = structlog.get_logger(__name__)
_HIPAA = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
_svc = ReferralService()


@router.post("/api/v1/referrals", status_code=201)
async def create_referral(
    request: Request,
    body: ReferralCreate,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Create a new specialist referral in PENDING status."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        ref = await _svc.create_referral(
            db, tenant_id, body.patient_id, auth["user_id"],
            body.specialty, body.urgency, body.reason,
            encounter_id=body.encounter_id,
            receiving_clinician_id=body.receiving_clinician_id,
            clinical_summary=body.clinical_summary,
            referral_letter=body.referral_letter,
            scheduled_date=body.scheduled_date,
        )
    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(ref.id)}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.get("/api/v1/referrals")
async def list_referrals(
    request: Request,
    patient_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE)),
) -> JSONResponse:
    """Return a paginated list of referrals with optional filters."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        from .enums import ReferralStatus
        status_enum = ReferralStatus(status) if status else None
        items, total = await _svc.list_referrals(
            db, tenant_id, patient_id=patient_id,
            status=status_enum, limit=limit, offset=offset,
        )
    data = [ReferralResponse.model_validate(r).model_dump(mode="json") for r in items]
    return JSONResponse(
        content={"success": True, "data": data, "meta": {"request_id": rid, "total": total, "limit": limit, "offset": offset}},
        headers=_HIPAA,
    )


@router.get("/api/v1/referrals/{referral_id}")
async def get_referral(
    request: Request, referral_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE)),
) -> JSONResponse:
    """Retrieve a single referral record by ID."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            ref = await _svc.get_referral(db, referral_id)
        except ReferralNotFoundError as exc:
            return JSONResponse(status_code=404, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        content={"success": True, "data": ReferralResponse.model_validate(ref).model_dump(mode="json"), "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.put("/api/v1/referrals/{referral_id}/status")
async def update_referral_status(
    request: Request, referral_id: uuid.UUID, body: ReferralStatusUpdate,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Update the status of a referral (validates allowed transitions)."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            ref = await _svc.update_status(db, referral_id, body.new_status, auth["user_id"])
        except (ReferralNotFoundError, InvalidStatusTransitionError) as exc:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        content={"success": True, "data": {"id": str(ref.id), "status": ref.status}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.post("/api/v1/referrals/{referral_id}/completion")
async def complete_referral(
    request: Request, referral_id: uuid.UUID, body: ReferralCompletion,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Record specialist findings and mark the referral as completed."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            ref = await _svc.complete_referral(
                db, referral_id, body.specialist_findings,
                body.specialist_recommendations, auth["user_id"],
            )
        except (ReferralNotFoundError, InvalidStatusTransitionError) as exc:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        content={"success": True, "data": {"id": str(ref.id), "status": ref.status}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )
