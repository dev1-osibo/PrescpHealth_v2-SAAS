"""
PrescpHealth Backend — Integrations Service (CRUD Operations).

Handles connector configuration management (create, read, update, list).
Sync execution is delegated to SyncEngine.

PHI / Security:
    - credentials JSONB is accepted in create/update but NEVER returned in responses.
    - ConnectorOut schema explicitly excludes credentials.
    - base_url is stored but not logged (may reveal internal network).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.audit.service import AuditService
from app.modules.integrations.enums import SyncStatus
from app.modules.integrations.exceptions import ConnectorNotFoundError
from app.modules.integrations.models import ConnectorConfig, SyncLog
from app.modules.integrations.schemas import (
    ConnectorCreateRequest,
    ConnectorUpdateRequest,
)

logger = structlog.get_logger(__name__)
_audit = AuditService()


class IntegrationService:
    """CRUD operations for connector configuration management."""

    async def create_connector(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ConnectorCreateRequest,
    ) -> ConnectorConfig:
        """
        Create a new connector configuration.

        Credentials are stored as-is (production would encrypt before storage).

        Args:
            db: Async DB session (tenant RLS applied).
            tenant_id: Tenant owning this connector.
            user_id: Admin creating the connector.
            data: Connector configuration (includes credentials — not logged).

        Returns:
            Newly created ConnectorConfig.
        """
        connector = ConnectorConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            connector_type=data.connector_type,
            name=data.name,
            base_url=data.base_url,  # stored, not logged
            auth_type=data.auth_type,
            credentials=data.credentials,  # stored, NEVER logged
            sync_direction=data.sync_direction,
            sync_schedule=data.sync_schedule,
            is_active=data.is_active,
            created_by=user_id,
        )
        db.add(connector)
        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="connector.create", resource_type="connector_config",
            resource_id=connector.id,
            # Log connector type and name only — no credentials, no base_url
            changes={
                "connector_type": data.connector_type.value,
                "name": data.name,
                "sync_direction": data.sync_direction.value,
            },
        )
        logger.info(
            "connector_created",
            connector_id=str(connector.id),
            connector_type=data.connector_type.value,
            tenant_id=str(tenant_id),
        )
        return connector

    async def get_connector(
        self,
        db: AsyncSession,
        connector_id: uuid.UUID,
    ) -> ConnectorConfig:
        """
        Retrieve a connector by ID.

        Raises:
            ConnectorNotFoundError: If not found or hidden by RLS.
        """
        result = (
            await db.execute(
                select(ConnectorConfig).where(ConnectorConfig.id == connector_id)
            )
        ).scalar_one_or_none()

        if result is None:
            raise ConnectorNotFoundError(connector_id)
        return result

    async def list_connectors(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[ConnectorConfig], int]:
        """
        List connectors for a tenant.

        Returns:
            Tuple of (connector list, total count).
        """
        base = select(ConnectorConfig).where(ConnectorConfig.tenant_id == tenant_id)
        count_base = select(func.count(ConnectorConfig.id)).where(
            ConnectorConfig.tenant_id == tenant_id
        )

        total = (await db.execute(count_base)).scalar() or 0
        connectors = list(
            (await db.execute(
                base.order_by(ConnectorConfig.created_at.desc())
                    .limit(limit).offset(offset)
            )).scalars()
        )
        return connectors, total

    async def update_connector(
        self,
        db: AsyncSession,
        connector_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ConnectorUpdateRequest,
    ) -> ConnectorConfig:
        """
        Update a connector configuration.

        Only provided fields are updated (partial update).
        Credentials are updated if provided — never logged.

        Raises:
            ConnectorNotFoundError: If not found.
        """
        connector = await self.get_connector(db, connector_id)

        updated_fields: list[str] = []
        if data.name is not None:
            connector.name = data.name
            updated_fields.append("name")
        if data.base_url is not None:
            connector.base_url = data.base_url  # Not logged
            updated_fields.append("base_url")
        if data.auth_type is not None:
            connector.auth_type = data.auth_type
            updated_fields.append("auth_type")
        if data.credentials is not None:
            connector.credentials = data.credentials  # NEVER log
            updated_fields.append("credentials")
        if data.sync_direction is not None:
            connector.sync_direction = data.sync_direction
            updated_fields.append("sync_direction")
        if data.sync_schedule is not None:
            connector.sync_schedule = data.sync_schedule
            updated_fields.append("sync_schedule")
        if data.is_active is not None:
            connector.is_active = data.is_active
            updated_fields.append("is_active")

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="connector.update", resource_type="connector_config",
            resource_id=connector.id,
            # Log field names changed, not values (credentials change is sensitive)
            changes={"fields_updated": updated_fields},
        )
        return connector

    async def list_sync_logs(
        self,
        db: AsyncSession,
        connector_id: uuid.UUID,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[SyncLog], int]:
        """
        Retrieve sync history for a connector.

        Returns:
            Tuple of (sync log list, total count).
        """
        base = select(SyncLog).where(SyncLog.connector_id == connector_id)
        count_base = select(func.count(SyncLog.id)).where(
            SyncLog.connector_id == connector_id
        )

        total = (await db.execute(count_base)).scalar() or 0
        logs = list(
            (await db.execute(
                base.order_by(SyncLog.started_at.desc()).limit(limit).offset(offset)
            )).scalars()
        )
        return logs, total
