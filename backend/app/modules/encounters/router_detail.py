"""
PrescpHealth Backend — Encounter Detail Router.

Detail and action endpoints for individual encounters:
- GET /api/v1/encounters/{id} — detail with SOAP, diagnoses, procedures
- PUT /api/v1/encounters/{id} — update encounter (Doctor+)
- POST /api/v1/encounters/{id}/soap-notes — add SOAP note (Doctor+)
- POST /api/v1/encounters/{id}/diagnoses — record diagnosis (Doctor+)
- POST /api/v1/encounters/{id}/procedures — record procedure (Doctor+)
- POST /api/v1/encounters/{id}/discharge — complete encounter (Doctor+)

Split from router.py to comply with ~150 line limit per file.
"""

import uuid

import structlog
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.encounters.fhir_mapper import diagnosis_to_fhir, encounter_to_fhir
from app.modules.encounters.router import _HIPAA_HEADERS, router
from app.modules.encounters.schemas import (
    DiagnosisCreate,
    DischargeRequest,
    EncounterUpdate,
    ProcedureCreate,
    SOAPNoteCreate,
)
from app.modules.encounters.service import EncounterService
from app.modules.encounters.service_diagnosis import DiagnosisService
from app.modules.encounters.service_soap import SOAPNoteService

logger = structlog.get_logger(__name__)

_encounter_service = EncounterService()
_soap_service = SOAPNoteService()
_diagnosis_service = DiagnosisService()


# ---------------------------------------------------------------------------
# GET /api/v1/encounters/{encounter_id} — Detail with related data
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/encounters/{encounter_id}",
    response_model=None,
    summary="Get encounter detail",
)
async def get_encounter(
    request: Request,
    encounter_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Retrieve encounter with SOAP notes, diagnoses, and procedures."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        encounter = await _encounter_service.get_encounter(db, encounter_id)
        item = _serialize_detail(encounter)

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": item, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/encounters/{encounter_id} — Update encounter
# ---------------------------------------------------------------------------
@router.put("/api/v1/encounters/{encounter_id}", response_model=None)
async def update_encounter(
    request: Request,
    encounter_id: uuid.UUID,
    body: EncounterUpdate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Update mutable encounter fields (clinician, class)."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        data = body.model_dump(exclude_none=True)
        encounter = await _encounter_service.update_encounter(
            db, encounter_id, uuid.UUID(str(user_id)), data
        )
        encounter.fhir_json = encounter_to_fhir(encounter)
        await db.commit()

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"id": str(encounter_id)}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/encounters/{encounter_id}/soap-notes
# ---------------------------------------------------------------------------
@router.post("/api/v1/encounters/{encounter_id}/soap-notes", status_code=201)
async def add_soap_note(
    request: Request,
    encounter_id: uuid.UUID,
    body: SOAPNoteCreate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Add a SOAP note to an encounter."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        note = await _soap_service.add_soap_note(
            db=db,
            encounter_id=encounter_id,
            tenant_id=uuid.UUID(str(tenant_id)),
            user_id=uuid.UUID(str(user_id)),
            **body.model_dump(exclude_none=True),
        )
        await db.commit()

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(note.id)}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/encounters/{encounter_id}/diagnoses
# ---------------------------------------------------------------------------
@router.post("/api/v1/encounters/{encounter_id}/diagnoses", status_code=201)
async def record_diagnosis(
    request: Request,
    encounter_id: uuid.UUID,
    body: DiagnosisCreate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Record a coded diagnosis for an encounter."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        # Get encounter to find patient_id
        enc = await _encounter_service.get_encounter(db, encounter_id)
        diagnosis = await _diagnosis_service.record_diagnosis(
            db=db,
            encounter_id=encounter_id,
            patient_id=enc.patient_id,
            tenant_id=uuid.UUID(str(tenant_id)),
            user_id=uuid.UUID(str(user_id)),
            icd10_code=body.icd10_code,
            is_chronic=body.is_chronic,
            is_primary=body.is_primary,
        )
        diagnosis.fhir_json = diagnosis_to_fhir(diagnosis)
        await db.commit()

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(diagnosis.id)}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/encounters/{encounter_id}/procedures
# ---------------------------------------------------------------------------
@router.post("/api/v1/encounters/{encounter_id}/procedures", status_code=201)
async def record_procedure(
    request: Request,
    encounter_id: uuid.UUID,
    body: ProcedureCreate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Record a procedure performed during an encounter."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        enc = await _encounter_service.get_encounter(db, encounter_id)
        from app.modules.encounters.procedure_model import Procedure
        procedure = Procedure(
            encounter_id=encounter_id,
            patient_id=enc.patient_id,
            tenant_id=uuid.UUID(str(tenant_id)),
            code=body.code,
            description=body.description,
            performed_by=uuid.UUID(str(user_id)),
            performed_at=body.performed_at,
        )
        db.add(procedure)
        await db.commit()

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(procedure.id)}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/encounters/{encounter_id}/discharge
# ---------------------------------------------------------------------------
@router.post("/api/v1/encounters/{encounter_id}/discharge", status_code=200)
async def discharge_encounter(
    request: Request,
    encounter_id: uuid.UUID,
    body: DischargeRequest,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Complete an encounter and generate discharge summary."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        encounter = await _encounter_service.complete_encounter(
            db, encounter_id, uuid.UUID(str(user_id))
        )
        encounter.fhir_json = encounter_to_fhir(encounter)
        await db.commit()

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"id": str(encounter_id), "status": "completed"}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Detail Serialization Helper
# ---------------------------------------------------------------------------
def _serialize_detail(encounter) -> dict:
    """Serialize encounter with nested SOAP notes, diagnoses, procedures."""
    from app.modules.encounters.router import _serialize_encounter
    base = _serialize_encounter(encounter)
    base["soap_notes"] = [
        {"id": str(n.id), "subjective": n.subjective, "objective": n.objective,
         "assessment": n.assessment, "plan": n.plan,
         "recorded_by": str(n.recorded_by),
         "created_at": n.created_at.isoformat() if getattr(n, "created_at", None) else None}
        for n in (encounter.soap_notes or [])
    ]
    base["diagnoses"] = [
        {"id": str(d.id), "icd10_code": d.icd10_code, "display_name": d.display_name,
         "is_chronic": d.is_chronic, "is_primary": d.is_primary}
        for d in (encounter.diagnoses or [])
    ]
    base["procedures"] = [
        {"id": str(p.id), "code": p.code, "description": p.description,
         "performed_at": p.performed_at.isoformat() if p.performed_at else None}
        for p in (encounter.procedures or [])
    ]
    return base
