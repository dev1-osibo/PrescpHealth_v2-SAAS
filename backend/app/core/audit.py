"""
PrescpHealth Backend — Audit Log SQLAlchemy Model (Core).

Defines the AuditLog model for HIPAA-compliant audit trail:
- Append-only table (no UPDATE/DELETE at database level)
- Monthly partitioning for performance and 7-year retention
- RLS policy for tenant isolation
- Captures: who, what, when, from where, which tenant, which resource

This model lives in core/ because audit logging is cross-cutting infrastructure
used by every module in the system — not specific to any single domain.

Design Decisions:
- Uses BIGSERIAL PK (not UUID) for efficient sequential inserts and partitioning
- No updated_at column — audit records are immutable once written
- No soft delete — audit records are never deleted through the application
- changes column stores {field: {old, new}} for update operations
- metadata column stores IP address, user agent, correlation_id
- No foreign keys — audit records must survive even if referenced data is
  deleted (7-year retention outlives most other records)

HIPAA Notes:
- NEVER store PHI in this table (no patient names, measurements, diagnoses)
- Only store opaque UUIDs as resource identifiers
- The 'changes' field should contain field names and non-PHI values only
- IP addresses are stored for security audit (breach investigation)

Table Partitioning:
- Partitioned by RANGE on created_at (monthly partitions)
- Enables efficient queries on recent data
- Allows dropping old partitions for retention management (7-year policy)
- A scheduled job creates future partitions before they're needed

Requirements Satisfied:
- 18.4: Audit_Log entry for every CUD operation on Patient data
- 18.5: Append-only; no role can delete or modify entries via API
- 20.3: Retain Audit_Log entries for minimum 7 years
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base


class AuditLog(Base):
    """
    Append-only audit log entry for HIPAA compliance.

    Records every create, update, and delete operation on patient data,
    plus authentication events, role changes, and system actions.

    This model maps to a partitioned table (monthly by created_at).
    The actual partitioning is set up in the Alembic migration (0003).

    Security:
    - Table uses audit_writer role (INSERT only, no UPDATE/DELETE)
    - RLS policy restricts reads to current tenant
    - No ORM update/delete methods should ever be called on this model

    Indexes (defined in migration):
    - (tenant_id, created_at DESC) — tenant-scoped time queries
    - (user_id, created_at DESC) — user activity queries
    - (resource_type, resource_id) — resource history queries
    - (action, created_at DESC) — action type queries

    Usage:
        from app.core.audit import AuditLog

        audit_entry = AuditLog(
            tenant_id=tenant_id,
            user_id=current_user.id,
            action="patient.create",
            resource_type="patient",
            resource_id=new_patient.id,
            changes=None,
            request_metadata={"ip": request.client.host, "correlation_id": corr_id},
        )
        session.add(audit_entry)
        await session.commit()
    """

    __tablename__ = "audit_logs"

    # -------------------------------------------------------------------------
    # Primary key — BIGSERIAL for efficient sequential inserts
    # Using BigInteger instead of UUID for partition-friendly sequential ordering.
    # PostgreSQL requires the partition key in the PK for partitioned tables,
    # so the actual PK is (id, created_at) — defined in the migration.
    # -------------------------------------------------------------------------
    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
        comment="Auto-incrementing audit entry ID (partition-friendly)",
    )

    # -------------------------------------------------------------------------
    # Tenant context — required for RLS isolation
    # Even system-level events have a tenant context (or a system sentinel UUID)
    # -------------------------------------------------------------------------
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Tenant UUID for RLS isolation of audit records",
    )

    # -------------------------------------------------------------------------
    # Who performed the action
    # -------------------------------------------------------------------------
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Acting user UUID (who performed the action)",
    )

    # -------------------------------------------------------------------------
    # What action was performed (dot-notation: resource.verb)
    # Examples: 'patient.create', 'measurement.update', 'auth.login'
    # -------------------------------------------------------------------------
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Action performed (e.g., 'patient.create', 'risk.compute')",
    )

    # -------------------------------------------------------------------------
    # Which type of resource was affected
    # -------------------------------------------------------------------------
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Resource type (e.g., 'patient', 'measurement', 'user')",
    )

    # -------------------------------------------------------------------------
    # Which specific resource was affected (nullable for list/search actions)
    # -------------------------------------------------------------------------
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Affected resource UUID (NULL for non-resource actions)",
    )

    # -------------------------------------------------------------------------
    # What changed — for update operations, stores {field: {old, new}}
    # MUST NOT contain PHI values — only field names and non-PHI data
    # -------------------------------------------------------------------------
    changes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Change details: {field: {old, new}} — NO PHI values",
    )

    # -------------------------------------------------------------------------
    # Additional context — IP address, user agent, correlation_id
    # Used for security investigations and breach response
    # NOTE: Python attribute is 'request_metadata' because 'metadata' is
    # reserved by SQLAlchemy's DeclarativeBase. The DB column is still 'metadata'.
    # -------------------------------------------------------------------------
    request_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Request context: {ip, user_agent, correlation_id}",
    )

    # -------------------------------------------------------------------------
    # When the action occurred — partition key
    # Server-side default ensures consistent timestamps even if app doesn't set it
    # -------------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="Event timestamp (UTC) — partition key for monthly partitions",
    )

    # NOTE: No updated_at column — audit records are IMMUTABLE
    # NOTE: No foreign keys — audit log must survive even if referenced records
    #       are deleted (7-year retention outlives most other data)

    __table_args__ = (
        {"comment": "Append-only HIPAA audit trail — NO UPDATE/DELETE permitted"},
    )

    def __repr__(self) -> str:
        """String representation for debugging (no PHI)."""
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"resource_type={self.resource_type!r} "
            f"tenant_id={self.tenant_id}>"
        )
