"""
PrescpHealth Backend — Billing API Router.

Endpoints:
    POST   /api/v1/invoices                          Generate invoice from encounter
    GET    /api/v1/invoices                          List invoices
    GET    /api/v1/invoices/{id}                     Invoice detail
    POST   /api/v1/invoices/{id}/payments            Record payment
    POST   /api/v1/invoices/{id}/void                Void an invoice
    POST   /api/v1/insurance-claims                  Submit claim
    GET    /api/v1/insurance-claims                  List claims
    PUT    /api/v1/insurance-claims/{id}/status      Update claim status

RBAC: Clinic_Admin and above for all endpoints.
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
from app.modules.billing.enums import ClaimStatus, InvoiceStatus
from app.modules.billing.exceptions import BillingError
from app.modules.billing.schemas import (
    ClaimStatusUpdateRequest,
    ClaimSubmitRequest,
    InvoiceGenerateRequest,
    PaymentRecordRequest,
    VoidRequest,
)
from app.modules.billing.service import BillingService
from app.modules.billing.service_claims import ClaimsService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["billing"])

# Shared stateless service instances
_billing = BillingService()
_claims = ClaimsService()

# Applied to all PHI-bearing responses
_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _envelope(data: object, request_id: str) -> dict:
    """Build the standard response envelope."""
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def _err_envelope(message: str, request_id: str, status_code: int = 400) -> JSONResponse:
    """Build an error response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/invoices
# ---------------------------------------------------------------------------
@router.post("/api/v1/invoices", status_code=201, summary="Generate invoice from encounter")
async def generate_invoice(
    request: Request,
    body: InvoiceGenerateRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Create an invoice from a clinical encounter. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            inv = await _billing.generate_invoice(
                db=db, encounter_id=body.encounter_id, tenant_id=tenant_id,
                user_id=user_id, currency=body.currency, notes=body.notes,
            )
            await db.commit()
            await db.refresh(inv)
        except BillingError as exc:
            return _err_envelope(exc.message, rid, exc.status_code)

    return JSONResponse(status_code=201, content=_envelope(_serialize_invoice(inv), rid),
                        headers=_HIPAA_HEADERS)


# ---------------------------------------------------------------------------
# GET /api/v1/invoices
# ---------------------------------------------------------------------------
@router.get("/api/v1/invoices", summary="List invoices")
async def list_invoices(
    request: Request,
    status: Optional[InvoiceStatus] = Query(None),
    patient_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """List invoices for the current tenant. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        invoices, total = await _billing.list_invoices(
            db, tenant_id, status=status, patient_id=patient_id,
            limit=limit, offset=offset,
        )
    items = [_serialize_invoice_slim(i) for i in invoices]
    return JSONResponse(
        content=_envelope({"items": items, "total": total}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/invoices/{id}
# ---------------------------------------------------------------------------
@router.get("/api/v1/invoices/{invoice_id}", summary="Invoice detail")
async def get_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Return full invoice with line items and payments. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            inv = await _billing.get_invoice_detail(db, invoice_id)
        except BillingError as exc:
            return _err_envelope(exc.message, rid, exc.status_code)

    return JSONResponse(content=_envelope(_serialize_invoice(inv), rid), headers=_HIPAA_HEADERS)


# ---------------------------------------------------------------------------
# POST /api/v1/invoices/{id}/payments
# ---------------------------------------------------------------------------
@router.post("/api/v1/invoices/{invoice_id}/payments", status_code=201, summary="Record payment")
async def record_payment(
    request: Request,
    invoice_id: uuid.UUID,
    body: PaymentRecordRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Record a payment against an invoice. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            payment = await _billing.record_payment(
                db=db, invoice_id=invoice_id, tenant_id=tenant_id,
                user_id=user_id, data=body,
            )
            await db.commit()
        except BillingError as exc:
            return _err_envelope(exc.message, rid, exc.status_code)

    return JSONResponse(
        status_code=201,
        content=_envelope({"payment_id": str(payment.id)}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/invoices/{id}/void
# ---------------------------------------------------------------------------
@router.post("/api/v1/invoices/{invoice_id}/void", summary="Void an invoice")
async def void_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    body: VoidRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Void an invoice (soft delete). Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            await _billing.void_invoice(db, invoice_id, tenant_id, user_id, body.reason)
            await db.commit()
        except BillingError as exc:
            return _err_envelope(exc.message, rid, exc.status_code)

    return JSONResponse(content=_envelope({"voided": True}, rid), headers=_HIPAA_HEADERS)


# ---------------------------------------------------------------------------
# POST /api/v1/insurance-claims
# ---------------------------------------------------------------------------
@router.post("/api/v1/insurance-claims", status_code=201, summary="Submit insurance claim")
async def submit_claim(
    request: Request,
    body: ClaimSubmitRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Submit an insurance claim for an invoice. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            claim = await _claims.submit_claim(db, tenant_id, user_id, body)
            await db.commit()
        except BillingError as exc:
            return _err_envelope(exc.message, rid, exc.status_code)

    return JSONResponse(
        status_code=201,
        content=_envelope({"claim_id": str(claim.id)}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/insurance-claims
# ---------------------------------------------------------------------------
@router.get("/api/v1/insurance-claims", summary="List insurance claims")
async def list_claims(
    request: Request,
    status: Optional[ClaimStatus] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """List insurance claims for the current tenant. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        claims, total = await _claims.list_claims(db, tenant_id, status, limit, offset)

    items = [_serialize_claim(c) for c in claims]
    return JSONResponse(
        content=_envelope({"items": items, "total": total}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/insurance-claims/{id}/status
# ---------------------------------------------------------------------------
@router.put("/api/v1/insurance-claims/{claim_id}/status", summary="Update claim status")
async def update_claim_status(
    request: Request,
    claim_id: uuid.UUID,
    body: ClaimStatusUpdateRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Update insurance claim status. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            claim = await _claims.update_claim_status(db, claim_id, tenant_id, user_id, body)
            await db.commit()
        except BillingError as exc:
            return _err_envelope(exc.message, rid, exc.status_code)

    return JSONResponse(content=_envelope(_serialize_claim(claim), rid), headers=_HIPAA_HEADERS)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_invoice(inv) -> dict:
    """Convert Invoice ORM object to dict (with line items and payments)."""
    return {
        "id": str(inv.id),
        "tenant_id": str(inv.tenant_id),
        "patient_id": str(inv.patient_id),
        "encounter_id": str(inv.encounter_id),
        "invoice_number": inv.invoice_number,
        "status": inv.status if isinstance(inv.status, str) else inv.status.value,
        "total_amount": str(inv.total_amount),
        "paid_amount": str(inv.paid_amount),
        "currency": inv.currency,
        "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "notes": inv.notes,
        "created_at": inv.created_at.isoformat() if getattr(inv, "created_at", None) else None,
        "line_items": [
            {
                "id": str(li.id), "item_type": li.item_type if isinstance(li.item_type, str) else li.item_type.value,
                "description": li.description, "quantity": li.quantity,
                "unit_price": str(li.unit_price), "total_price": str(li.total_price),
                "code": li.code,
            }
            for li in getattr(inv, "line_items", [])
        ],
        "payments": [
            {
                "id": str(p.id), "amount": str(p.amount),
                "payment_method": p.payment_method if isinstance(p.payment_method, str) else p.payment_method.value,
                "paid_at": p.paid_at.isoformat(), "reference_number": p.reference_number,
            }
            for p in getattr(inv, "payments", [])
        ],
    }


def _serialize_invoice_slim(inv) -> dict:
    """Slim invoice dict for list responses."""
    return {
        "id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "status": inv.status if isinstance(inv.status, str) else inv.status.value,
        "total_amount": str(inv.total_amount),
        "paid_amount": str(inv.paid_amount),
        "currency": inv.currency,
        "created_at": inv.created_at.isoformat() if getattr(inv, "created_at", None) else None,
    }


def _serialize_claim(claim) -> dict:
    """Convert InsuranceClaim ORM object to dict."""
    return {
        "id": str(claim.id),
        "invoice_id": str(claim.invoice_id),
        "patient_id": str(claim.patient_id),
        "insurance_provider": claim.insurance_provider,
        "policy_number": claim.policy_number,
        "claim_number": claim.claim_number,
        "status": claim.status if isinstance(claim.status, str) else claim.status.value,
        "submitted_amount": str(claim.submitted_amount),
        "approved_amount": str(claim.approved_amount) if claim.approved_amount else None,
        "submitted_at": claim.submitted_at.isoformat(),
        "resolved_at": claim.resolved_at.isoformat() if claim.resolved_at else None,
        "created_at": claim.created_at.isoformat() if getattr(claim, "created_at", None) else None,
    }
