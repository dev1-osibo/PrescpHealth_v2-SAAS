"""
Documents Module — Pydantic Schemas
=====================================
Request/response schemas for the documents API.
Upload endpoint uses FastAPI UploadFile; metadata is returned as Document.
"""

import uuid
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import DocumentType


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class DocumentUploadMeta(BaseModel):
    """
    Form-field metadata submitted alongside an UploadFile.

    Used by the upload endpoint to pass structured metadata.
    The file itself is received as UploadFile separately.
    """

    patient_id: uuid.UUID
    document_type: DocumentType
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    encounter_id: Optional[uuid.UUID] = None
    doc_metadata: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class DocumentResponse(BaseModel):
    """
    Read schema for a document record.

    NOTE: storage_path and file_name are excluded from the public response
    to avoid leaking internal infrastructure details.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    document_type: DocumentType
    title: str
    description: Optional[str] = None
    file_name: str
    mime_type: str
    file_size_bytes: int
    storage_backend: str
    is_encrypted: bool
    uploaded_by: uuid.UUID
    uploaded_at: datetime
    doc_metadata: Optional[dict[str, Any]] = None
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Wrapper for paginated document lists."""

    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int
