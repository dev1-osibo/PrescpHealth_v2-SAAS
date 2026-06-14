"""
Documents Module — FastAPI Router
====================================
Exposes 5 endpoints for document upload, listing, metadata retrieval,
streamed download, and patient document listing.
All responses include HIPAA-compliant cache headers.
Download endpoint uses StreamingResponse for memory-efficient transfer.
"""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from .schemas import DocumentResponse
from .service import DocumentService
from .enums import DocumentType
from .exceptions import DocumentNotFoundError, InvalidMimeTypeError, FileSizeExceededError

router = APIRouter(tags=["documents"])
log = structlog.get_logger(__name__)
_HIPAA = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
_svc = DocumentService()


@router.post("/api/v1/documents", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    patient_id: uuid.UUID = Form(...),
    document_type: DocumentType = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    encounter_id: Optional[uuid.UUID] = Form(None),
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE, Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Upload a clinical document via multipart/form-data."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    file_data = await file.read()
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        try:
            doc = await _svc.upload_document(
                db, tenant_id, patient_id, auth["user_id"],
                file_data, file.filename or "upload", file.content_type or "application/octet-stream",
                document_type, title, encounter_id, description,
            )
        except (InvalidMimeTypeError, FileSizeExceededError) as exc:
            return JSONResponse(status_code=422, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        status_code=201,
        content={"success": True, "data": {"id": str(doc.id)}, "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.get("/api/v1/documents")
async def list_documents(
    request: Request,
    patient_id: Optional[uuid.UUID] = Query(None),
    document_type: Optional[DocumentType] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE)),
) -> JSONResponse:
    """Return a paginated list of documents with optional filters."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        items, total = await _svc.list_documents(db, tenant_id, patient_id, document_type, limit, offset)
    data = [DocumentResponse.model_validate(d).model_dump(mode="json") for d in items]
    return JSONResponse(
        content={"success": True, "data": data, "meta": {"request_id": rid, "total": total, "limit": limit, "offset": offset}},
        headers=_HIPAA,
    )


@router.get("/api/v1/documents/{document_id}")
async def get_document(
    request: Request, document_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE)),
) -> JSONResponse:
    """Retrieve document metadata (not file bytes) by ID."""
    rid = getattr(request.state, "request_id", "unknown")
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            doc = await _svc.get_document(db, document_id)
        except DocumentNotFoundError as exc:
            return JSONResponse(status_code=404, content={"success": False, "error": str(exc)}, headers=_HIPAA)
    return JSONResponse(
        content={"success": True, "data": DocumentResponse.model_validate(doc).model_dump(mode="json"), "meta": {"request_id": rid}},
        headers=_HIPAA,
    )


@router.get("/api/v1/documents/{document_id}/download")
async def download_document(
    request: Request, document_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE)),
) -> StreamingResponse:
    """Stream document bytes to the client with appropriate Content-Type headers."""
    factory = get_session_factory()
    async with factory() as db:
        if auth.get("tenant_id"):
            await set_tenant_context(db, str(auth["tenant_id"]))
        try:
            doc, data = await _svc.download_document(db, document_id)
        except DocumentNotFoundError:
            return JSONResponse(status_code=404, content={"success": False, "error": "Document not found"}, headers=_HIPAA)

    async def _iter():
        yield data

    return StreamingResponse(
        content=_iter(),
        media_type=doc.mime_type,
        headers={
            **_HIPAA,
            "Content-Disposition": f'attachment; filename="{doc.file_name}"',
            "Content-Length": str(doc.file_size_bytes),
        },
    )


@router.get("/api/v1/patients/{patient_id}/documents")
async def get_patient_documents(
    request: Request, patient_id: uuid.UUID,
    document_type: Optional[DocumentType] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.DOCTOR, Role.NURSE)),
) -> JSONResponse:
    """List all documents associated with a specific patient."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = auth["tenant_id"]
    factory = get_session_factory()
    async with factory() as db:
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))
        items, total = await _svc.list_documents(db, tenant_id, patient_id, document_type, limit, offset)
    data = [DocumentResponse.model_validate(d).model_dump(mode="json") for d in items]
    return JSONResponse(
        content={"success": True, "data": data, "meta": {"request_id": rid, "total": total}},
        headers=_HIPAA,
    )
