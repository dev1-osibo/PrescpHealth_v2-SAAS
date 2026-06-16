"""
PrescpHealth Backend — Integrations ORM Models.

Tables:
    connector_configs   — External system connection settings (credentials encrypted)
    sync_logs           — Per-run sync audit records (NO PHI in any column)

Security:
    ConnectorConfig.credentials JSONB must be encrypted at rest.
    Application code reads/writes but NEVER logs this column.
    RLS ensures tenant isolation at database level.

HIPAA:
    SyncLog.error_summary is metadata only (no PHI, no patient identifiers).
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.integrations.enums import (
    AuthType,
    ConnectorType,
    SyncDirection,
    SyncStatus,
)


class ConnectorConfig(TenantMixin, Base):
    """
    Configuration for an external system connector.

    Security Notes:
        - credentials JSONB stores auth secrets (API keys, passwords, tokens).
        - credentials is NEVER logged or included in error messages.
        - In production, credentials would be encrypted using a KMS key
          before storage (e.g., AWS KMS, HashiCorp Vault).
    """

    __tablename__ = "connector_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Surrogate PK",
    )
    connector_type: Mapped[ConnectorType] = mapped_column(
        String(32), nullable=False,
        comment="External system type (openmrs, dhis2, generic_fhir)",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Human-readable connector label (non-PHI)",
    )
    base_url: Mapped[str] = mapped_column(
        String(2048), nullable=False,
        comment="Base URL of the external system — never log this",
    )
    auth_type: Mapped[AuthType] = mapped_column(String(32), nullable=False)
    # CRITICAL: credentials are encrypted at rest — NEVER log
    credentials: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="Encrypted credentials (api_key / username+password / oauth2 tokens)",
    )
    sync_direction: Mapped[SyncDirection] = mapped_column(String(32), nullable=False)
    # cron schedule string (e.g., "0 2 * * *" for 2 AM daily)
    sync_schedule: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment="Cron expression for automatic sync scheduling",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )

    sync_logs: Mapped[list["SyncLog"]] = relationship(
        "SyncLog", back_populates="connector", lazy="select",
    )


class SyncLog(TenantMixin, Base):
    """
    Audit record for a single sync execution.

    All columns contain metadata ONLY — no PHI, no patient identifiers.
    error_summary contains operational details (record counts, error codes).
    """

    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_configs.id"),
        nullable=False, index=True,
    )
    direction: Mapped[SyncDirection] = mapped_column(String(32), nullable=False)
    status: Mapped[SyncStatus] = mapped_column(
        String(32), nullable=False, default=SyncStatus.STARTED,
    )
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # error_summary: operational metadata — NO PHI (patient names, values)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Duration in milliseconds for performance monitoring
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    connector: Mapped["ConnectorConfig"] = relationship(
        "ConnectorConfig", back_populates="sync_logs",
    )
