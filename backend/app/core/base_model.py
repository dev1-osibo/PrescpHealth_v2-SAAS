"""
PrescpHealth Backend — Base SQLAlchemy Models and Tenant Mixin.

Provides the declarative base class and mixins used by all database models.
Every tenant-scoped table uses TenantMixin which adds:
- tenant_id column (UUID, NOT NULL, indexed)
- RLS policy helper for migrations
- Timestamp columns (created_at, updated_at)

Architecture:
    All models inherit from Base (declarative base).
    Tenant-scoped models also inherit from TenantMixin.
    The TenantMixin ensures every row is tagged with a tenant_id,
    and provides a helper to generate the RLS policy SQL for migrations.

Example:
    class Patient(TenantMixin, Base):
        __tablename__ = "patients"
        id = mapped_column(UUID, primary_key=True)
        full_name = mapped_column(String(255), nullable=False)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    """
    Declarative base for all SQLAlchemy models.

    All models in the application inherit from this class.
    It provides the metadata registry and common type mappings.
    """
    pass


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at columns.

    These columns are automatically managed:
    - created_at: Set once when the row is inserted (server-side default)
    - updated_at: Updated on every modification (server-side onupdate)

    All timestamps are stored in UTC (timezone-aware) per i18n steering rule.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="Row creation timestamp (UTC)",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last modification timestamp (UTC)",
    )


class TenantMixin(TimestampMixin):
    """
    Mixin for tenant-scoped tables with Row-Level Security.

    Adds a tenant_id column that:
    - Is a UUID (matches tenant table PK)
    - Is NOT NULL (every row must belong to a tenant)
    - Is indexed (RLS policy filters on this column every query)
    - Is used by PostgreSQL RLS policies to enforce data isolation

    RLS Policy Pattern:
        The RLS policy on each table checks:
        tenant_id = current_setting('app.current_tenant')::uuid

        This is set per-session by TenantMiddleware before any query runs.
        Even if application code forgets to filter by tenant_id, the database
        will enforce isolation automatically.

    Usage:
        class Patient(TenantMixin, Base):
            __tablename__ = "patients"
            ...
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Tenant UUID for RLS isolation — every query is filtered by this",
    )

    @classmethod
    def rls_policy_sql(cls) -> str:
        """
        Generate the SQL to create an RLS policy for this table.

        Returns the SQL statements needed to:
        1. Enable RLS on the table
        2. Create a policy that restricts all operations to the current tenant
        3. Force RLS even for table owners (prevents accidental bypass)

        This is used in Alembic migrations when creating tenant-scoped tables.

        Returns:
            str: SQL statements to enable RLS on this table.
        """
        table_name = cls.__tablename__
        return f"""
-- Enable Row-Level Security on {table_name}
ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;

-- Force RLS for table owner too (prevents bypass)
ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;

-- Policy: users can only see/modify rows matching their tenant
CREATE POLICY tenant_isolation_policy ON {table_name}
    USING (tenant_id = current_setting('app.current_tenant')::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
"""


class SoftDeleteMixin:
    """
    Mixin for soft-deletable records (HIPAA: never hard-delete patient data).

    Instead of DELETE, we set is_deleted=True and record when/who deleted it.
    Queries should filter out soft-deleted records by default.
    Data retention: minimum 7 years per HIPAA policy.
    """

    is_deleted: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="Soft delete flag — True means logically deleted but retained for HIPAA",
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="When the record was soft-deleted (NULL if active)",
    )
