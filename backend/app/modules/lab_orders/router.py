"""
PrescpHealth Backend — Lab Order API Router.

REST endpoints for lab order lifecycle management:
- POST /api/v1/lab-orders — create lab order (Doctor/Nurse+, validates LOINC)
- GET /api/v1/lab-orders — list lab orders (Nurse+)
- GET /api/v1/lab-orders/{id} — detail with results (Nurse+)
- PUT /api/v1/lab-orders/{id}/status — update status (Nurse+)
- POST /api/v1/lab-orders/{id}/results — record result (Nurse+)
- GET /api/v1/patients/{patient_id}/lab-orders — patient history (Nurse+)

HIPAA Compliance:
- Cache-Control: no-store on ALL responses (PHI present)
- Never logs PHI — only lab_order_id UUID in log messages
- RLS enforces tenant isolation at database level
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.lab_orders.fhir_mapper import order_to_fhir, result_to_fhir
from app.modules.lab_orders.schemas import (
    LabOrderCreate,
    LabOrderStatusUpdate,
    LabResultCreate,
)
from app.modules.lab_orders.service import LabOrderService
from app.modules.lab_orders.service_results import LabResultService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["lab-orders"])

_lab_order_service = LabOrderService()
_lab_result_service = LabResultService()

_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


# ---------------------------------------------------------------------------
# POST /api/v1/lab-orders — Create a new lab order
# ---------------------------------------------------------------------------
@router.post("/api/v1/lab-orders", status_code=201, response_model=None)
async def create_lab_order(
    request: Request,
    body: LabOrderCreate,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Create a new lab order with LOINC code validation."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        lab_order = await _lab_order_service.create_lab_order(
            db=db,
            tenant_id=uuid.UUID(str(tenant_id)),
            patient_id=body.patient_id,
            user_id=uuid.UUID(str(user_id)),
            encounter_id=body.encounter_id,
            test_name=body.test_name,
            loinc_code=body.loinc_code,
            priority=body.priority,
            clinical_indication=body.clinical_indication,
        )
        # Compute and store FHIR R4 representation
        lab_order.fhir_json = order_to_fhir(lab_order)
        await db.commit()
        item = _serialize_lab_order(lab_order)

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": item, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/lab-orders — List lab orders
# ---------------------------------------------------------------------------
@router.get("/api/v1/lab-orders", response_model=None)
async def list_lab_orders(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """List lab orders (tenant-scoped via RLS)."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        from sqlalchemy import select, func
        from app.modules.lab_orders.models import LabOrder

        base = select(LabOrder).order_by(LabOrder.created_at.desc())
        if status:
            base = base.where(LabOrder.status == status)
        count_stmt = select(func.count(LabOrder.id))
        if status:
            count_stmt = count_stmt.where(LabOrder.status == status)

        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = base.limit(limit).offset(offset)
        result = await db.execute(stmt)
        items = [_serialize_lab_order(o) for o in result.scalars().all()]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"items": items, "total": total}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/lab-orders/{order_id} — Detail with results
# ---------------------------------------------------------------------------
@router.get("/api/v1/lab-orders/{order_id}", response_model=None)
async def get_lab_order(
    request: Request,
    order_id: uuid.UUID,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Get lab order detail with results."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        lab_order = await _lab_order_service.get_lab_order(db, order_id)
        item = _serialize_lab_order(lab_order)
        item["results"] = [
            _serialize_lab_result(r) for r in (lab_order.results or [])
        ]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": item, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/lab-orders/{order_id}/status — Update status
# ---------------------------------------------------------------------------
@router.put("/api/v1/lab-orders/{order_id}/status", response_model=None)
async def update_lab_order_status(
    request: Request,
    order_id: uuid.UUID,
    body: LabOrderStatusUpdate,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Update lab order status with transition validation."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        lab_order = await _lab_order_service.update_status(
            db, order_id, body.status, uuid.UUID(str(user_id))
        )
        lab_order.fhir_json = order_to_fhir(lab_order)
        await db.commit()

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"id": str(order_id), "status": body.status}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/lab-orders/{order_id}/results — Record result
# ---------------------------------------------------------------------------
@router.post("/api/v1/lab-orders/{order_id}/results", status_code=201)
async def record_lab_result(
    request: Request,
    order_id: uuid.UUID,
    body: LabResultCreate,
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """Record a lab result for an order."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]
    user_id = auth_context["user_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        lab_result = await _lab_result_service.record_result(
            db=db,
            order_id=order_id,
            tenant_id=uuid.UUID(str(tenant_id)),
            user_id=uuid.UUID(str(user_id)),
            value=body.value,
            numeric_value=body.numeric_value,
            unit=body.unit,
            reference_range_low=body.reference_range_low,
            reference_range_high=body.reference_range_high,
            resulted_at=body.resulted_at,
        )
        lab_result.fhir_json = result_to_fhir(lab_result)
        await db.commit()

    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(lab_result.id), "is_abnormal": lab_result.is_abnormal}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/lab-orders — Patient history
# ---------------------------------------------------------------------------
@router.get("/api/v1/patients/{patient_id}/lab-orders", response_model=None)
async def list_patient_lab_orders(
    request: Request,
    patient_id: uuid.UUID,
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    auth_context: dict = Depends(require_role(Role.NURSE)),
) -> JSONResponse:
    """List lab orders for a specific patient."""
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        orders, total = await _lab_order_service.list_patient_lab_orders(
            db=db, patient_id=patient_id, status_filter=status, limit=limit
        )
        items = [_serialize_lab_order(o) for o in orders]

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"items": items, "total": total}, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Serialization Helpers
# ---------------------------------------------------------------------------
def _serialize_lab_order(order) -> dict:
    """Convert LabOrder model to JSON-serializable dict."""
    return {
        "id": str(order.id),
        "tenant_id": str(order.tenant_id),
        "patient_id": str(order.patient_id),
        "encounter_id": str(order.encounter_id) if order.encounter_id else None,
        "test_name": order.test_name,
        "loinc_code": order.loinc_code,
        "priority": order.priority,
        "status": order.status,
        "ordered_by": str(order.ordered_by),
        "specimen_collected_at": order.specimen_collected_at.isoformat() if order.specimen_collected_at else None,
        "fhir_json": order.fhir_json,
        "created_at": order.created_at.isoformat() if getattr(order, "created_at", None) else None,
    }


def _serialize_lab_result(result) -> dict:
    """Convert LabResult model to JSON-serializable dict."""
    return {
        "id": str(result.id),
        "value": result.value,
        "numeric_value": result.numeric_value,
        "unit": result.unit,
        "reference_range_low": result.reference_range_low,
        "reference_range_high": result.reference_range_high,
        "is_abnormal": result.is_abnormal,
        "resulted_at": result.resulted_at.isoformat() if result.resulted_at else None,
    }
