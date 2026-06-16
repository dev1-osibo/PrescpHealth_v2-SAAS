"""
PrescpHealth Backend — Bed Management API Router.

Endpoints:
    POST   /api/v1/admissions                        Admit patient
    GET    /api/v1/beds                              Bed availability (by ward)
    GET    /api/v1/admissions/{id}                   Admission details
    POST   /api/v1/admissions/{id}/nursing-notes     Add nursing note
    POST   /api/v1/admissions/{id}/vitals            Chart vitals
    POST   /api/v1/admissions/{id}/discharge         Discharge patient

RBAC:
    Admit/discharge  = Doctor+
    Notes/vitals     = Nurse+
    Bed status view  = Nurse+

HIPAA: Cache-Control: no-store on all responses.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.bed_management.exceptions import BedManagementError
from app.modules.bed_management.schemas import (
    AdmitPatientRequest,
    DischargeRequest,
    NursingNoteRequest,
    VitalsRequest,
)
from app.modules.bed_management.service import BedManagementService
from app.modules.bed_management.service_nursing import NursingService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["bed_management"])

_bed_svc = BedManagementService()
_nursing_svc = NursingService()

_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _envelope(data: object, request_id: str) -> dict:
    """Standard response envelope."""
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def _err(message: str, request_id: str, status_code: int = 400) -> JSONResponse:
    """Error response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admissions — Admit patient (Doctor+)
# ---------------------------------------------------------------------------
@router.post("/api/v1/admissions", status_code=201, summary="Admit patient to bed")
async def admit_patient(
    request: Request,
    body: AdmitPatientRequest,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Admit a patient to a bed. Doctor+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    doctor_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            admission = await _bed_svc.admit_patient(db, body, tenant_id, doctor_id)
            await db.commit()
            await db.refresh(admission)
        except BedManagementError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        status_code=201,
        content=_envelope(_serialize_admission(admission), rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/beds — Bed availability (Nurse+)
# ---------------------------------------------------------------------------
@router.get("/api/v1/beds", summary="Bed availability by ward")
async def get_bed_availability(
    request: Request,
    ward_id: Optional[uuid.UUID] = Query(None),
    auth: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Return bed availability. Optionally filtered by ward. Nurse+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        if ward_id:
            data = await _bed_svc.get_bed_availability(db, ward_id)
            result = {
                "ward_id": data["ward_id"],
                "counts": data["counts"],
                "beds": [_serialize_bed(b) for b in data["beds"]],
            }
        else:
            # Return overview of all wards
            result = await _bed_svc.get_ward_overview(db, tenant_id)

    return JSONResponse(content=_envelope(result, rid), headers=_HIPAA_HEADERS)


# ---------------------------------------------------------------------------
# GET /api/v1/admissions/{id} — Admission detail (Nurse+)
# ---------------------------------------------------------------------------
@router.get("/api/v1/admissions/{admission_id}", summary="Admission details")
async def get_admission(
    request: Request,
    admission_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Return full admission record. Nurse+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            admission = await _bed_svc.get_admission(db, admission_id)
        except BedManagementError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        content=_envelope(_serialize_admission(admission), rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admissions/{id}/nursing-notes — Add note (Nurse+)
# ---------------------------------------------------------------------------
@router.post("/api/v1/admissions/{admission_id}/nursing-notes",
             status_code=201, summary="Add nursing note")
async def add_nursing_note(
    request: Request,
    admission_id: uuid.UUID,
    body: NursingNoteRequest,
    auth: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Attach a nursing note to an active admission. Nurse+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    nurse_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            note = await _nursing_svc.add_nursing_note(
                db, admission_id, tenant_id, nurse_id, body
            )
            await db.commit()
        except BedManagementError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        status_code=201,
        content=_envelope({"note_id": str(note.id), "note_type": note.note_type.value
                           if hasattr(note.note_type, "value") else note.note_type}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admissions/{id}/vitals — Chart vitals (Nurse+)
# ---------------------------------------------------------------------------
@router.post("/api/v1/admissions/{admission_id}/vitals",
             status_code=201, summary="Chart vitals")
async def chart_vitals(
    request: Request,
    admission_id: uuid.UUID,
    body: VitalsRequest,
    auth: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Record vitals for an admitted patient. Nurse+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    nurse_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            result = await _nursing_svc.chart_vitals(
                db, admission_id, tenant_id, nurse_id, body
            )
            await db.commit()
        except BedManagementError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        status_code=201,
        content=_envelope(result, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admissions/{id}/discharge — Discharge (Doctor+)
# ---------------------------------------------------------------------------
@router.post("/api/v1/admissions/{admission_id}/discharge", summary="Discharge patient")
async def discharge_patient(
    request: Request,
    admission_id: uuid.UUID,
    body: DischargeRequest,
    auth: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Discharge a patient from their bed. Doctor+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            admission = await _bed_svc.discharge_patient(
                db, admission_id, tenant_id, user_id, body
            )
            await db.commit()
            await db.refresh(admission)
        except BedManagementError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        content=_envelope(_serialize_admission(admission), rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_admission(a) -> dict:
    """Convert Admission ORM object to dict."""
    return {
        "id": str(a.id),
        "tenant_id": str(a.tenant_id),
        "patient_id": str(a.patient_id),
        "bed_id": str(a.bed_id),
        "encounter_id": str(a.encounter_id) if a.encounter_id else None,
        "admitting_doctor_id": str(a.admitting_doctor_id),
        "admitted_at": a.admitted_at.isoformat(),
        "discharged_at": a.discharged_at.isoformat() if a.discharged_at else None,
        "discharge_type": (a.discharge_type.value if hasattr(a.discharge_type, "value")
                           else a.discharge_type),
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "discharge_plan": a.discharge_plan,
        "created_at": a.created_at.isoformat() if getattr(a, "created_at", None) else None,
    }


def _serialize_bed(b) -> dict:
    """Convert Bed ORM object to dict."""
    return {
        "id": str(b.id),
        "ward_id": str(b.ward_id),
        "bed_number": b.bed_number,
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "bed_type": b.bed_type.value if hasattr(b.bed_type, "value") else b.bed_type,
        "notes": b.notes,
    }
