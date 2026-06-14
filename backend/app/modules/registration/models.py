"""
Registration Module — SQLAlchemy Models
=========================================
Defines Consent and IdentityVerification ORM models.
Both tables are tenant-isolated via RLS (see migration 0021).
TenantMixin provides: tenant_id, created_at.

IMPORTANT PHI NOTICE:
  - digital_signature: NEVER log — base64 encoded biometric/signature data
  - document_number on IdentityVerification: NEVER log — government ID number
"""

import uuid
from datetime import datetime, date
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin
from .enums import ConsentType, VerificationType


class Consent(TenantMixin, Base):
    """
    Records a patient's consent grant or denial for a specific purpose.

    Consents may be revoked (soft-delete via revoked_at).
    Expired consents (expires_at < now()) are treated as inactive.
    """

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False, index=True
    )
    consent_type: Mapped[str] = mapped_column(
        sa.Enum(ConsentType, name="consenttype"), nullable=False
    )
    version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    is_granted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # digital_signature: base64-encoded — PHI, NEVER log
    digital_signature: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    witness_name: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    captured_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revocation_reason: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    consent_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, name="metadata"
    )


class IdentityVerification(TenantMixin, Base):
    """
    Records the verification of a patient's identity during registration.

    document_number is stored for audit trail but MUST NEVER appear in logs.
    """

    __tablename__ = "identity_verifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False, index=True
    )
    verification_type: Mapped[str] = mapped_column(
        sa.Enum(VerificationType, name="verificationtype"), nullable=False
    )
    # document_number: PHI — NEVER log this field
    document_number: Mapped[Optional[str]] = mapped_column(
        sa.String(100), nullable=True
    )
    issuing_authority: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True
    )
    expiry_date: Mapped[Optional[date]] = mapped_column(sa.Date, nullable=True)
    is_verified: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
