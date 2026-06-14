"""
Registration Module — FastAPI Router
=======================================
Exposes 5 endpoints for patient intake, registration updates,
consent capture, identity verification, and registration completion.
All responses include HIPAA-compliant cache headers.

PHI NOTICE: No patient names or document numbers are emitted in logs.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from .schemas import (
    IntakeCreate,
    RegistrationUpdate,
    ConsentCapture,
    ConsentResponse,
    IdentityVerificationCreate,
    IdentityVerificationResponse,
)
from .service import RegistrationService
from .service_consent import ConsentService
from .exceptions import (
    RegistrationNotFoundError,
    RegistrationIncompleteError,
    ConsentNotFoundError,
)
from .models import IdentityVerification
from .enums import VerificationType
from datetime import datetime, timezone

router = APIRouter(tags=["registration"])
log = structlog.get_logger(__name__)
_HIPAA = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
_reg_svc = RegistrationService()
_consent_svc = ConsentService()


@router.post("/api/v1/registration/intake", status_code=201)
async def start_intake(
    request: Request,
    body: IntakeCreate,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Start patient intake by creating a minimal patient record."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        patient_id = await _reg_svc.start_intake(
            db, tenant_id, body.first_name, body.last_name,
            body.date_of_birth, auth["user_id"],
        )
    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"patient_id": str(patient_id)}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.put("/api/v1/registration/{patient_id}")
async def update_registration(
    request: Request, patient_id: uuid.UUID, body: RegistrationUpdate,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Incrementally update patient registration fields."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            await _reg_svc.update_registration(
                db, patient_id, body.model_dump(exclude_none=True), auth["user_id"],
            )
        except RegistrationNotFoundError as exc:
            return JSONResponse(status_code=404, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        content={"success": True, "data": {"patient_id": str(patient_id)}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.post("/api/v1/registration/{patient_id}/consent", status_code=201)
async def capture_consent(
    request: Request, patient_id: uuid.UUID, body: ConsentCapture,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Record a patient consent event (grant or denial)."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        consent = await _consent_svc.capture_consent(
            db, tenant_id, patient_id, body.consent_type, body.version,
            body.is_granted, auth["user_id"],
            digital_signature=body.digital_signature,
            witness_name=body.witness_name,
            expires_at=body.expires_at,
            metadata=body.metadata,
        )
    return JSONResponse(
        status_code=201,
        content={"success": True, "data": ConsentResponse.model_validate(consent).model_dump(mode="json"), "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.post("/api/v1/registration/{patient_id}/identity", status_code=201)
async def record_identity_verification(
    request: Request, patient_id: uuid.UUID, body: IdentityVerificationCreate,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Record an identity verification event for the patient."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        # document_number is stored but NEVER logged
        verification = IdentityVerification(
            tenant_id=tenant_id,
            patient_id=patient_id,
            verification_type=body.verification_type,
            document_number=body.document_number,  # PHI — not logged
            issuing_authority=body.issuing_authority,
            expiry_date=body.expiry_date,
            notes=body.notes,
            is_verified=False,
        )
        db.add(verification)
        await db.flush()
        from app.modules.audit.service import AuditService
        await AuditService().log_action(
            db, action="identity_verification.created",
            resource_id=str(verification.id),
            tenant_id=str(tenant_id), user_id=str(auth["user_id"]),
        )
        await db.commit()
        await db.refresh(verification)
    return JSONResponse(
        status_code=201,
        content={"success": True, "data": IdentityVerificationResponse.model_validate(verification).model_dump(mode="json"), "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.post("/api/v1/registration/{patient_id}/complete")
async def complete_registration(
    request: Request, patient_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Finalize patient registration: validate fields, generate MRN, activate patient."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            mrn = await _reg_svc.complete_registration(db, patient_id, auth["user_id"])
        except RegistrationNotFoundError as exc:
            return JSONResponse(status_code=404, content={"success": False, "error": str(exc)}, headers=_HIPAA)
        except RegistrationIncompleteError as exc:
            return JSONResponse(status_code=422, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        content={"success": True, "data": {"patient_id": str(patient_id), "mrn": mrn}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )
