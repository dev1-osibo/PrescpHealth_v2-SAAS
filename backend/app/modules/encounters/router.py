"""
PrescpHealth Backend — Encounter API Router (Main).

REST endpoints for encounter lifecycle management:
- POST /api/v1/encounters — create encounter (Doctor+)
- GET /api/v1/encounters — list encounters (Nurse+)
- GET /api/v1/patients/{patient_id}/encounters — patient history (Nurse+)

Access Control:
- Nurse+: Read access (list, patient history)
- Doctor+: Write access (create)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- Never logs PHI — only encounter_id UUID in log messages
- RLS enforces tenant isolation at database level
- All mutations create audit trail entries
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.encounters.fhir_mapper import encounter_to_fhir
from app.modules.encounters.schemas import EncounterCreate
from app.modules.encounters.service import EncounterService

# ---------------------------------------------------------------------------
# Module logger — logs encounter API access without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition
# ---------------------------------------------------------------------------
router = APIRouter(tags=["encounters"])

# Shared service instance (stateless, safe to reuse)
_encounter_service = EncounterService()

# HIPAA header constant — applied to every response containing PHI
_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


# ---------------------------------------------------------------------------
# POST /api/v1/encounters — Create a new encounter
# ---------------------------------------------------------------------------
@router.post(
    "/api/v1/encounters",
    response_model=None,
    status_code=201,
    summary="Create a new encounter (patient check-in)",
    description="Creates a new encounter. Requires Doctor role or above. "
    "Stores computed FHIR R4 representation.",
)
async def create_encounter(
    request: Request,
    body: EncounterCreate,
    auth_context: dict = Depends(require_role(Role.DOCTOR)),
) -> JSONResponse:
    """Create a new encounter and compute FHIR representation."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        encounter = await _encounter_service.create_encounter(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            patient_id=body.patient_id,
            clinician_id=uuid.UUID(str(user_id)),
            reason=body.reason_for_visit,
            encounter_class=body.encounter_class,
        )

        # Compute and store FHIR R4 representation
        encounter.fhir_json = encounter_to_fhir(encounter)
        await db.commit()

        item = _serialize_encounter(encounter)

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": item, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/encounters — List encounters (tenant-scoped)
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/encounters",
    response_model=None,
    summary="List encounters",
    description="Returns encounters for the current tenant. Requires Nurse+.",
)
async def list_encounters(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """List encounters with pagination (tenant-scoped via RLS)."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        from sqlalchemy import select, func
        from app.modules.encounters.encounter_model import Encounter

        # Count total
        count_stmt = select(func.count(Encounter.id))
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Fetch page
        stmt = (
            select(Encounter)
            .order_by(Encounter.check_in_time.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        encounters = list(result.scalars().all())
        items = [_serialize_encounter(e) for e in encounters]

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {"items": items, "total": total},
            "meta": {"request_id": request_id},
        },
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/encounters — Patient encounter history
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/patients/{patient_id}/encounters",
    response_model=None,
    summary="Get patient encounter history",
    description="Returns all encounters for a patient. Requires Nurse+.",
)
async def list_patient_encounters(
    request: Request,
    patient_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=100),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """List encounters for a specific patient."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        encounters = await _encounter_service.list_patient_encounters(
            db=db, patient_id=patient_id, limit=limit
        )
        items = [_serialize_encounter(e) for e in encounters]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": items, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Serialization Helper
# ---------------------------------------------------------------------------
def _serialize_encounter(encounter) -> dict:
    """Convert Encounter model to JSON-serializable dict."""
    return {
        "id": str(encounter.id),
        "tenant_id": str(encounter.tenant_id),
        "patient_id": str(encounter.patient_id),
        "clinician_id": str(encounter.clinician_id),
        "status": encounter.status.value if hasattr(encounter.status, "value") else encounter.status,
        "encounter_class": encounter.encounter_class.value if hasattr(encounter.encounter_class, "value") else encounter.encounter_class,
        "reason_for_visit": encounter.reason_for_visit,
        "check_in_time": encounter.check_in_time.isoformat() if encounter.check_in_time else None,
        "check_out_time": encounter.check_out_time.isoformat() if encounter.check_out_time else None,
        "discharge_summary": encounter.discharge_summary,
        "fhir_json": encounter.fhir_json,
        "created_at": encounter.created_at.isoformat() if getattr(encounter, "created_at", None) else None,
    }


# ---------------------------------------------------------------------------
# Import sub-module to register detail routes on this router
# ---------------------------------------------------------------------------
from app.modules.encounters import router_detail  # noqa: E402, F401
