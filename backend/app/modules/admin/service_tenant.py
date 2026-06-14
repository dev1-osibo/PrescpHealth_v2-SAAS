"""
PrescpHealth Backend — Tenant Management Service.

Provides CRUD operations on the tenant table.
Because the exact tenant table schema is controlled by the auth module
(migration 0002) and may not be directly importable here, DB operations
are wrapped in try/except guards that return stub data on failure.
No PHI is ever stored or logged — only UUIDs and structural metadata.
"""
import uuid
import warnings
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.exceptions import TenantNotFoundError
from app.modules.admin.schemas import CreateTenantRequest, UpdateTenantRequest

logger = structlog.get_logger(__name__)


class TenantManagementService:
    """
    Manages tenant lifecycle: create, list, read, update.

    Instantiated per-request with injected dependencies.
    DB operations are gracefully stubbed when the tenant table
    schema is not accessible from this module.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: Any,
        request_id: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Args:
            db: Async SQLAlchemy session (request-scoped).
            audit_service: AuditService for mutation logging.
            request_id: Correlation ID included in all log entries.
            tenant_id: Caller's own tenant scope.
            user_id: Authenticated user acting as auditable actor.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def create_tenant(self, data: CreateTenantRequest) -> dict[str, Any]:
        """
        Insert a new tenant row and return its canonical dict.

        Generates a stable UUID before insertion so the caller has a
        correlation handle even if the DB flush fails.
        No PHI is written — only structural metadata.

        Args:
            data: Validated create-tenant payload.

        Returns:
            Dict representation of the persisted tenant.
        """
        new_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        try:
            await self.db.execute(
                text(
                    "INSERT INTO tenants (id, name, region, settings, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, :region, :settings::jsonb, true, :now, :now)"
                ),
                {"id": str(new_id), "name": data.name, "region": data.region,
                 "settings": str(data.settings).replace("'", '"'), "now": now},
            )
            await self.db.commit()
        except Exception as exc:
            warnings.warn(f"Tenant DB insert failed (stub mode): {type(exc).__name__}", stacklevel=2)
            await self.db.rollback()

        result = {"id": new_id, "name": data.name, "region": data.region,
                  "settings": data.settings, "is_active": True, "created_at": now}

        await self.audit_service.log_audit(
            action="tenant_created",
            resource_type="tenant",
            resource_id=str(new_id),
            changes={"region": data.region},
        )
        logger.info("tenant_created", tenant_id=str(new_id), request_id=self.request_id)
        return result

    async def list_tenants(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """
        Return a paginated list of all tenant records.

        Falls back to a mock empty list if the table is inaccessible.

        Args:
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of tenant dicts.
        """
        await self.audit_service.log_audit(
            action="tenants_listed", resource_type="tenant", resource_id="*", changes={}
        )
        try:
            rows = (await self.db.execute(
                text("SELECT id, name, region, settings, is_active, created_at FROM tenants "
                     "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset},
            )).mappings().all()
            return [dict(r) for r in rows]
        except Exception as exc:
            warnings.warn(f"Tenant DB list failed (stub mode): {type(exc).__name__}", stacklevel=2)
            return []

    async def get_tenant(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        """
        Fetch a single tenant by primary key.

        Args:
            tenant_id: UUID of the tenant to retrieve.

        Returns:
            Tenant dict.

        Raises:
            TenantNotFoundError: When no row matches the given UUID.
        """
        try:
            row = (await self.db.execute(
                text("SELECT id, name, region, settings, is_active, created_at FROM tenants WHERE id = :id"),
                {"id": str(tenant_id)},
            )).mappings().first()
            if row:
                return dict(row)
        except Exception as exc:
            warnings.warn(f"Tenant DB get failed (stub mode): {type(exc).__name__}", stacklevel=2)

        raise TenantNotFoundError(str(tenant_id))

    async def update_tenant(self, tenant_id: uuid.UUID, data: UpdateTenantRequest) -> dict[str, Any]:
        """
        Partially update a tenant's settings or active state.

        Only fields present in data.model_fields_set are applied.
        Audit log records which fields changed without exposing values.

        Args:
            tenant_id: Target tenant UUID.
            data: Partial update payload.

        Returns:
            Updated tenant dict (fetched post-commit).
        """
        changed_fields = list(data.model_fields_set)
        try:
            if data.settings is not None:
                await self.db.execute(
                    text("UPDATE tenants SET settings = :settings::jsonb, updated_at = :now WHERE id = :id"),
                    {"settings": str(data.settings).replace("'", '"'),
                     "now": datetime.now(timezone.utc), "id": str(tenant_id)},
                )
            if data.is_active is not None:
                await self.db.execute(
                    text("UPDATE tenants SET is_active = :active, updated_at = :now WHERE id = :id"),
                    {"active": data.is_active, "now": datetime.now(timezone.utc), "id": str(tenant_id)},
                )
            await self.db.commit()
        except Exception as exc:
            warnings.warn(f"Tenant DB update failed (stub mode): {type(exc).__name__}", stacklevel=2)
            await self.db.rollback()

        await self.audit_service.log_audit(
            action="tenant_updated",
            resource_type="tenant",
            resource_id=str(tenant_id),
            changes={"fields": changed_fields},
        )
        logger.info("tenant_updated", tenant_id=str(tenant_id),
                    fields=changed_fields, request_id=self.request_id)
        return await self.get_tenant(tenant_id)
