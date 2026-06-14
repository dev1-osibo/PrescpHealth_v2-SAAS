"""
PrescpHealth Backend — Admin Facade Service.

Thin orchestrator combining TenantManagementService and ModelManagementService.
Callers use AdminService as the single entry point; sub-services are
lazily initialised on first property access.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.schemas import TenantSettingsRequest
from app.modules.admin.service_model import ModelManagementService
from app.modules.admin.service_tenant import TenantManagementService

logger = structlog.get_logger(__name__)


class AdminService:
    """
    Facade combining tenant and model management services.

    Provides convenience methods for settings operations scoped to
    the current tenant without exposing sub-service internals to routers.
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
            request_id: Correlation ID for structured logs.
            tenant_id: Current tenant UUID for scoping.
            user_id: Authenticated user UUID for audit trail.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._tenant_mgmt: TenantManagementService | None = None
        self._model_mgmt: ModelManagementService | None = None

    @property
    def tenant_mgmt(self) -> TenantManagementService:
        """Lazily initialised TenantManagementService."""
        if self._tenant_mgmt is None:
            self._tenant_mgmt = TenantManagementService(
                db=self.db,
                audit_service=self.audit_service,
                request_id=self.request_id,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
            )
        return self._tenant_mgmt

    @property
    def model_mgmt(self) -> ModelManagementService:
        """Lazily initialised ModelManagementService."""
        if self._model_mgmt is None:
            self._model_mgmt = ModelManagementService(
                db=self.db,
                audit_service=self.audit_service,
                request_id=self.request_id,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
            )
        return self._model_mgmt

    async def get_tenant_settings(self) -> dict[str, Any]:
        """
        Retrieve the settings dict for the caller's own tenant.

        Returns:
            Dict with tenant_id, settings, and updated_at.
        """
        tenant = await self.tenant_mgmt.get_tenant(self.tenant_id)
        logger.info("tenant_settings_read", tenant_id=str(self.tenant_id), request_id=self.request_id)
        return {
            "tenant_id": tenant["id"],
            "settings": tenant.get("settings", {}),
            "updated_at": tenant.get("updated_at", datetime.now(timezone.utc)),
        }

    async def update_tenant_settings(self, data: TenantSettingsRequest) -> dict[str, Any]:
        """
        Merge provided settings fields into the caller's own tenant record.

        Only non-None fields from the request are applied.

        Args:
            data: TenantSettingsRequest with optional timezone, language, channels.

        Returns:
            Updated settings dict (tenant_id, settings, updated_at).
        """
        from app.modules.admin.schemas import UpdateTenantRequest

        patch: dict[str, Any] = {}
        if data.timezone is not None:
            patch["timezone"] = data.timezone
        if data.language is not None:
            patch["language"] = data.language
        if data.notification_channels is not None:
            patch["notification_channels"] = data.notification_channels

        current = await self.tenant_mgmt.get_tenant(self.tenant_id)
        merged = {**current.get("settings", {}), **patch}

        update_req = UpdateTenantRequest(settings=merged)
        updated = await self.tenant_mgmt.update_tenant(self.tenant_id, update_req)

        now = datetime.now(timezone.utc)
        return {
            "tenant_id": updated["id"],
            "settings": updated.get("settings", merged),
            "updated_at": updated.get("updated_at", now),
        }
