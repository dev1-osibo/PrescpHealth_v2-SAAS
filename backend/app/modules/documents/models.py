"""
Documents Module — SQLAlchemy Models
======================================
Defines the Document ORM model.
Documents are IMMUTABLE once uploaded — no updated_at column.
Tenant-isolated via RLS (see migration 0020).
TenantMixin provides: tenant_id, created_at.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin
from .enums import DocumentType


class Document(TenantMixin, Base):
    """
    Represents a clinical document stored in the EMR.

    Documents are write-once/immutable. The storage_path points to the
    location in the configured backend (local filesystem or future S3).
    is_encrypted is always True — encryption handled at storage layer.

    NOTE: file_name, storage_path, and title may contain patient context —
    never log these fields. Log only document UUID.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("encounters.id"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(
        sa.Enum(DocumentType, name="documenttype"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    # file_name stores the original client-supplied filename — treat as PHI
    file_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # storage_path is the internal path on the configured backend — treat as sensitive
    storage_path: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, default="local"
    )
    is_encrypted: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    doc_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, name="metadata"
    )
    # NOTE: No updated_at — documents are immutable after upload.
