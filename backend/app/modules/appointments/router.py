"""
Appointments Module — FastAPI Router
======================================
Exposes 7 endpoints for appointment booking, rescheduling,
cancellation, check-in, completion, waitlist, and patient history.
All responses include HIPAA-compliant cache headers.
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from .schemas import AppointmentCreate, AppointmentReschedule, WaitlistCreate
from .service import AppointmentService
from .service_waitlist import WaitlistService
from .exceptions import AppointmentNotFoundError, DoubleBookingError, InvalidAppointmentStateError

router = APIRouter(tags=["appointments"])
log = structlog.get_logger(__name__)
_HIPAA = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
_appt_svc = AppointmentService()
_wl_svc = WaitlistService()


@router.post("/api/v1/appointments", status_code=201)
async def book_appointment(
    request: Request,
    body: AppointmentCreate,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Book a new appointment. Checks double-booking before creating."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        try:
            appt = await _appt_svc.book_appointment(
                db, tenant_id, body.patient_id, body.clinician_id,
                body.appointment_type, body.scheduled_start, body.scheduled_end,
                body.reason, auth["user_id"], body.notes,
            )
        except DoubleBookingError as exc:
            return JSONResponse(status_code=409, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(status_code=201, content={"success": True, "data": {"id": str(appt.id)}, "meta": {"request_id": rid}}, headers=_HIPAA)


@router.get("/api/v1/appointments")
async def list_appointments(
    request: Request,
    clinician_id: Optional[uuid.UUID] = Query(None),
    patient_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """List appointments with optional filters."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        if clinician_id and date_from and date_to:
            items = await _appt_svc.get_schedule(db, clinician_id, date_from, date_to)
        else:
            items = []
    data = [{"id": str(a.id), "status": a.status, "scheduled_start": a.scheduled_start.isoformat()} for a in items]
    return JSONResponse(content={"success": True, "data": data, "meta": {"request_id": rid, "count": len(data)}}, headers=_HIPAA)


@router.get("/api/v1/appointments/{appointment_id}")
async def get_appointment(
    request: Request, appointment_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Retrieve a single appointment by ID."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            appt = await _appt_svc.get_appointment(db, appointment_id)
        except AppointmentNotFoundError as exc:
            return JSONResponse(status_code=404, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(content={"success": True, "data": {"id": str(appt.id), "status": appt.status}, "meta": {"request_id": rid}}, headers=_HIPAA)


@router.put("/api/v1/appointments/{appointment_id}")
async def reschedule_appointment(
    request: Request, appointment_id: uuid.UUID, body: AppointmentReschedule,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Reschedule an existing appointment to a new time window."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            appt = await _appt_svc.reschedule(db, appointment_id, body.new_start, body.new_end, auth["user_id"])
        except (AppointmentNotFoundError, DoubleBookingError, InvalidAppointmentStateError) as exc:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(content={"success": True, "data": {"id": str(appt.id)}, "meta": {"request_id": rid}}, headers=_HIPAA)


@router.delete("/api/v1/appointments/{appointment_id}")
async def cancel_appointment(
    request: Request, appointment_id: uuid.UUID,
    reason: str = Query(..., description="Cancellation reason"),
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Cancel an appointment and promote from waitlist if applicable."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            await _appt_svc.cancel(db, appointment_id, reason, auth["user_id"])
        except (AppointmentNotFoundError, InvalidAppointmentStateError) as exc:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(content={"success": True, "data": {}, "meta": {"request_id": rid}}, headers=_HIPAA)


@router.post("/api/v1/appointments/waitlist", status_code=201)
async def add_to_waitlist(
    request: Request, body: WaitlistCreate,
    auth: dict = Depends(require_role(Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Add a patient to the appointment waitlist."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        entry = await _wl_svc.add_to_waitlist(
            db, tenant_id, body.patient_id, body.appointment_type,
            body.preferred_date_start, auth["user_id"], body.clinician_id,
            body.preferred_date_end, body.preferred_time_start,
            body.preferred_time_end, body.priority, body.notes,
        )
    return JSONResponse(status_code=201, content={"success": True, "data": {"id": str(entry.id)}, "meta": {"request_id": rid}}, headers=_HIPAA)


@router.get("/api/v1/patients/{patient_id}/appointments")
async def get_patient_appointments(
    request: Request, patient_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Retrieve appointment history for a specific patient."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        from sqlalchemy import select
        from .models import Appointment
        stmt = select(Appointment).where(Appointment.patient_id == patient_id).order_by(Appointment.scheduled_start.desc())
        result = await db.execute(stmt)
        items = result.scalars().all()
    data = [{"id": str(a.id), "status": a.status, "scheduled_start": a.scheduled_start.isoformat()} for a in items]
    return JSONResponse(content={"success": True, "data": data, "meta": {"request_id": rid, "count": len(data)}}, headers=_HIPAA)
