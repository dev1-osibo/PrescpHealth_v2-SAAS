"""
Documents Module — DocumentService
=====================================
Handles document upload validation, storage persistence,
and retrieval for clinical documents.
No PHI in log messages — document UUID only.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .models import Document
from .enums import DocumentType, ALLOWED_MIME_TYPES, MAX_FILE_SIZE_BYTES
from .exceptions import (
    DocumentNotFoundError,
    InvalidMimeTypeError,
    FileSizeExceededError,
)
from .storage import StorageBackend, get_storage_backend

log = structlog.get_logger(__name__)
_audit = AuditService()


class DocumentService:
    """Service layer for document lifecycle management."""

    def __init__(self, storage: Optional[StorageBackend] = None) -> None:
        """Initialise with an optional storage backend (defaults to local)."""
        self._storage = storage or get_storage_backend("local")

    def _build_storage_path(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        file_name: str,
    ) -> str:
        """Return a logical storage path under tenant/document subdirectory."""
        return f"{tenant_id}/{document_id}/{file_name}"

    async def upload_document(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        uploaded_by: uuid.UUID,
        file_data: bytes,
        file_name: str,
        mime_type: str,
        document_type: DocumentType,
        title: str,
        encounter_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
        doc_metadata: Optional[dict] = None,
    ) -> Document:
        """
        Validate MIME type and size, persist file to storage, then create DB record.

        Raises:
            InvalidMimeTypeError: If mime_type is not in ALLOWED_MIME_TYPES.
            FileSizeExceededError: If file exceeds MAX_FILE_SIZE_BYTES.
        """
        if mime_type not in ALLOWED_MIME_TYPES:
            raise InvalidMimeTypeError(mime_type)
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise FileSizeExceededError(len(file_data), MAX_FILE_SIZE_BYTES)

        document_id = uuid.uuid4()
        storage_path = self._build_storage_path(tenant_id, document_id, file_name)
        resolved_path = await self._storage.save(storage_path, file_data)

        doc = Document(
            id=document_id,
            tenant_id=tenant_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            document_type=document_type,
            title=title,
            description=description,
            file_name=file_name,
            mime_type=mime_type,
            file_size_bytes=len(file_data),
            storage_path=storage_path,
            storage_backend="local",
            is_encrypted=True,
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(timezone.utc),
            doc_metadata=doc_metadata,
        )
        db.add(doc)
        await db.flush()
        await _audit.log_action(
            db, action="document.uploaded", resource_id=str(doc.id),
            tenant_id=str(tenant_id), user_id=str(uploaded_by),
        )
        await db.commit()
        await db.refresh(doc)
        log.info("document.created", document_id=str(doc.id))
        return doc

    async def get_document(
        self, db: AsyncSession, document_id: uuid.UUID,
    ) -> Document:
        """Fetch document metadata by UUID or raise DocumentNotFoundError."""
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        doc = result.scalars().first()
        if not doc:
            raise DocumentNotFoundError(str(document_id))
        return doc

    async def download_document(
        self, db: AsyncSession, document_id: uuid.UUID,
    ) -> tuple[Document, bytes]:
        """Fetch document metadata and retrieve file bytes from storage."""
        doc = await self.get_document(db, document_id)
        data = await self._storage.get(doc.storage_path)
        await _audit.log_action(
            db, action="document.downloaded", resource_id=str(doc.id),
            tenant_id=str(doc.tenant_id), user_id="unknown",
        )
        return doc, data

    async def list_documents(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: Optional[uuid.UUID] = None,
        document_type: Optional[DocumentType] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        """Return a paginated list of documents filtered by optional patient or type."""
        filters = [Document.tenant_id == tenant_id]
        if patient_id:
            filters.append(Document.patient_id == patient_id)
        if document_type:
            filters.append(Document.document_type == document_type)
        stmt = (
            select(Document)
            .where(and_(*filters))
            .order_by(Document.uploaded_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())
        count_stmt = select(func.count(Document.id)).where(and_(*filters))
        total = (await db.execute(count_stmt)).scalar_one()
        return items, total
