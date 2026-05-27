"""
PrescpHealth Backend — Prescription API Router.

REST endpoints for prescription lifecycle management:
- POST /api/v1/prescriptions — write prescription (Doctor+, triggers DDI)
- GET /api/v1/prescriptions — list prescriptions (Nurse+)
- GET /api/v1/prescriptions/{id} — detail with dispensings (Nurse+)
- PUT /api/v1/prescriptions/{id}/status — discontinue/hold/resume (Doctor+)
- POST /api/v1/prescriptions/{id}/refill — process refill (Doctor+)
- GET /api/v1/patients/{patient_id}/prescriptions — patient history (Nurse+)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- Never logs PHI — only prescription_id UUID in log messages
- RLS enforces tenant isolation at database level
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.prescriptions.fhir_mapper import prescription_to_fhir
from app.modules.prescriptions.schemas import (
    PrescriptionCreate,
    PrescriptionStatusUpdate,
    RefillRequest,
)
from app.modules.prescriptions.service import PrescriptionService
from app.modules.prescriptions.service_refill import RefillService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["prescriptions"])

_prescription_service = PrescriptionService()
_refill_service = RefillService()

_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


# ---------------------------------------------------------------------------
# POST /api/v1/prescriptions — Write a new prescription
# ---------------------------------------------------------------------------
@router.post("/api/v1/prescriptions", status_code=201, response_model=None)
async def write_prescription(
    request: Request,
    body: PrescriptionCreate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Write a new prescription with ATC validation and DDI check."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        drug_data = body.model_dump(exclude={"patient_id", "encounter_id"})
        prescription = await _prescription_service.write_prescription(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            patient_id=body.patient_id,
            user_id=uuid.UUID(str(user_id)),
            encounter_id=body.encounter_id,
            drug_data=drug_data,
        )
        # Compute and store FHIR R4 representation
        prescription.fhir_json = prescription_to_fhir(prescription)
        await db.commit()
        item = _serialize_prescription(prescription)

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": item, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/prescriptions — List prescriptions
# ---------------------------------------------------------------------------
@router.get("/api/v1/prescriptions", response_model=None)
async def list_prescriptions(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """List prescriptions (tenant-scoped via RLS)."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        from sqlalchemy import select, func
        from app.modules.prescriptions.prescription_model import Prescription

        base = select(Prescription).order_by(Prescription.created_at.desc())
        if status:
            base = base.where(Prescription.status == status)
        count_stmt = select(func.count(Prescription.id))
        if status:
            count_stmt = count_stmt.where(Prescription.status == status)

        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = base.limit(limit).offset(offset)
        result = await db.execute(stmt)
        items = [_serialize_prescription(p) for p in result.scalars().all()]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"items": items, "total": total}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/prescriptions/{prescription_id} — Detail with dispensings
# ---------------------------------------------------------------------------
@router.get("/api/v1/prescriptions/{prescription_id}", response_model=None)
async def get_prescription(
    request: Request,
    prescription_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Get prescription detail with dispensing history."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        prescription = await _prescription_service.get_prescription(db, prescription_id)
        item = _serialize_prescription(prescription)
        item["dispensings"] = [
            {"id": str(d.id), "dispensed_quantity": d.dispensed_quantity,
             "dispensed_at": d.dispensed_at.isoformat() if d.dispensed_at else None,
             "is_refill": d.is_refill}
            for d in (prescription.dispensings or [])
        ]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": item, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/prescriptions/{prescription_id}/status
# ---------------------------------------------------------------------------
@router.put("/api/v1/prescriptions/{prescription_id}/status", response_model=None)
async def update_prescription_status(
    request: Request,
    prescription_id: uuid.UUID,
    body: PrescriptionStatusUpdate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Discontinue, hold, or resume a prescription."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        uid = uuid.UUID(str(user_id))
        if body.action == "discontinue":
            await _prescription_service.discontinue_prescription(
                db, prescription_id, uid, body.reason or "No reason provided"
            )
        elif body.action == "hold":
            await _prescription_service.hold_prescription(db, prescription_id, uid)
        elif body.action == "resume":
            await _prescription_service.resume_prescription(db, prescription_id, uid)
        await db.commit()

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"id": str(prescription_id), "action": body.action}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/prescriptions/{prescription_id}/refill
# ---------------------------------------------------------------------------
@router.post("/api/v1/prescriptions/{prescription_id}/refill", status_code=201)
async def process_refill(
    request: Request,
    prescription_id: uuid.UUID,
    body: RefillRequest,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Process a prescription refill."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        dispensing = await _refill_service.process_refill(
            db=db,
            prescription_id=prescription_id,
            user_id=uuid.UUID(str(user_id)),
            dispensed_quantity=body.dispensed_quantity,
        )
        await db.commit()

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(dispensing.id)}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/prescriptions — Patient history
# ---------------------------------------------------------------------------
@router.get("/api/v1/patients/{patient_id}/prescriptions", response_model=None)
async def list_patient_prescriptions(
    request: Request,
    patient_id: uuid.UUID,
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """List prescriptions for a specific patient."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        from app.modules.prescriptions.enums import PrescriptionStatus
        status_filter = PrescriptionStatus(status) if status else None
        prescriptions = await _prescription_service.list_patient_prescriptions(
            db=db, patient_id=patient_id, status_filter=status_filter, limit=limit
        )
        items = [_serialize_prescription(p) for p in prescriptions]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": items, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Serialization Helper
# ---------------------------------------------------------------------------
def _serialize_prescription(prescription) -> dict:
    """Convert Prescription model to JSON-serializable dict."""
    return {
        "id": str(prescription.id),
        "tenant_id": str(prescription.tenant_id),
        "patient_id": str(prescription.patient_id),
        "encounter_id": str(prescription.encounter_id) if prescription.encounter_id else None,
        "drug_name": prescription.drug_name,
        "atc_code": prescription.atc_code,
        "dosage": prescription.dosage,
        "frequency": prescription.frequency,
        "duration_days": prescription.duration_days,
        "route": prescription.route,
        "status": prescription.status.value if hasattr(prescription.status, "value") else prescription.status,
        "refills_allowed": prescription.refills_allowed,
        "refills_remaining": prescription.refills_remaining,
        "prescribed_by": str(prescription.prescribed_by),
        "fhir_json": prescription.fhir_json,
        "created_at": prescription.created_at.isoformat() if getattr(prescription, "created_at", None) else None,
    }
