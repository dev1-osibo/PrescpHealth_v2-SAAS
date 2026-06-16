"""
PrescpHealth Backend — Integration Sync Engine.

Orchestrates data synchronisation between PrescpHealth and external systems.
Provides:
    - execute_sync() — Main sync orchestration
    - resolve_conflict() — Last-write-wins conflict resolution with audit
    - retry_with_backoff() — Exponential backoff for transient failures

Retry schedule (max_retries=5):
    Attempt 1: immediate
    Attempt 2: 30 seconds
    Attempt 3: 2 minutes
    Attempt 4: 8 minutes
    Attempt 5: 30 minutes
    Attempt 6: 2 hours

PHI:
    No PHI in error messages or log output.
    error_summary stored in SyncLog is metadata only.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.integrations.enums import (
    ConnectorType,
    SyncDirection,
    SyncStatus,
)
from app.modules.integrations.exceptions import ConnectorNotFoundError
from app.modules.integrations.models import ConnectorConfig, SyncLog

logger = structlog.get_logger(__name__)
_audit = AuditService()

# Retry delay schedule in seconds (30s, 2min, 8min, 30min, 2h)
_RETRY_DELAYS = [0, 30, 120, 480, 1800, 7200]

T = TypeVar("T")


async def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = 5,
    connector_id: uuid.UUID | None = None,
) -> Any:
    """
    Execute a callable with exponential backoff on failure.

    Implements the retry schedule defined in the brief:
    Attempts at: 0s, 30s, 2min, 8min, 30min, 2h.

    Args:
        func: Async callable to execute.
        max_retries: Maximum number of retry attempts (default 5).
        connector_id: Connector UUID for log context (non-PHI).

    Returns:
        Result of the successful function call.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    attempts = min(max_retries + 1, len(_RETRY_DELAYS))

    for attempt in range(attempts):
        delay = _RETRY_DELAYS[attempt]
        if delay > 0:
            logger.info(
                "sync_retry_backoff",
                attempt=attempt,
                delay_seconds=delay,
                connector_id=str(connector_id) if connector_id else None,
            )
            await asyncio.sleep(delay)
        try:
            return await func()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "sync_attempt_failed",
                attempt=attempt + 1,
                max_retries=max_retries,
                error_type=type(exc).__name__,
                # Never log exc message — may contain PHI or credentials
                connector_id=str(connector_id) if connector_id else None,
            )

    # All retries exhausted — raise the last exception
    raise last_exc  # type: ignore[misc]


class SyncEngine:
    """
    Sync orchestrator for connector execution.

    Handles the full sync lifecycle:
    1. Load connector config and create a SyncLog entry.
    2. Instantiate the appropriate connector stub.
    3. Execute sync with retry logic.
    4. Update SyncLog with results.
    5. Audit-log the sync completion.
    """

    async def execute_sync(
        self,
        db: AsyncSession,
        connector_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> SyncLog:
        """
        Orchestrate a full sync run for a connector.

        Args:
            db: Async DB session (tenant RLS applied).
            connector_id: ConnectorConfig UUID to sync.
            tenant_id: Tenant context.
            user_id: User or system triggering the sync.

        Returns:
            Completed SyncLog entry.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist or is inactive.
        """
        # Load connector config
        connector = await self._load_connector(db, connector_id)

        # Create sync log entry
        started_at = datetime.now(timezone.utc)
        log = SyncLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            connector_id=connector_id,
            direction=connector.sync_direction,
            status=SyncStatus.STARTED,
            records_processed=0,
            records_succeeded=0,
            records_failed=0,
            started_at=started_at,
        )
        db.add(log)
        await db.flush()

        logger.info(
            "sync_started",
            sync_log_id=str(log.id),
            connector_id=str(connector_id),
            connector_type=connector.connector_type.value,
            direction=connector.sync_direction.value,
        )

        try:
            # Execute sync via the appropriate connector
            result = await self._run_connector(connector)

            # Update log with results
            log.status = SyncStatus.COMPLETED if result["failed"] == 0 else SyncStatus.PARTIAL
            log.records_processed = result["total"]
            log.records_succeeded = result["succeeded"]
            log.records_failed = result["failed"]

        except Exception as exc:
            # Sync failed — record error metadata (no PHI in error_summary)
            log.status = SyncStatus.FAILED
            log.error_summary = f"error_type={type(exc).__name__}"

        finally:
            # Always record completion time and duration
            completed_at = datetime.now(timezone.utc)
            log.completed_at = completed_at
            log.duration_ms = int(
                (completed_at - started_at).total_seconds() * 1000
            )
            # Update last_sync_at on the connector
            connector.last_sync_at = completed_at

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="sync.execute", resource_type="sync_log",
            resource_id=log.id,
            changes={
                "connector_id": str(connector_id),
                "status": log.status.value,
                "records_processed": log.records_processed,
            },
        )

        logger.info(
            "sync_completed",
            sync_log_id=str(log.id),
            connector_id=str(connector_id),
            status=log.status.value,
            duration_ms=log.duration_ms,
        )
        return log

    def resolve_conflict(
        self,
        local: dict[str, Any],
        remote: dict[str, Any],
        connector_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """
        Resolve a data conflict between local and remote records.

        Strategy: last-write-wins based on meta.lastUpdated timestamps.
        If timestamps are equal or missing, local record wins (safer default).

        The conflict resolution decision is logged with metadata only —
        no PHI values are included in the log entry.

        Args:
            local: Local internal record dict.
            remote: Remote external record dict.
            connector_id: For log context.

        Returns:
            Winning record dict.
        """
        local_ts = local.get("meta", {}).get("lastUpdated", "")
        remote_ts = remote.get("meta", {}).get("lastUpdated", "")

        # Remote wins only if its timestamp is strictly newer
        if remote_ts and local_ts and remote_ts > local_ts:
            winner = "remote"
            result = remote
        else:
            winner = "local"
            result = local

        logger.info(
            "conflict_resolved",
            strategy="last_write_wins",
            winner=winner,
            local_ts=local_ts,
            remote_ts=remote_ts,
            connector_id=str(connector_id) if connector_id else None,
        )
        return result

    async def _load_connector(
        self, db: AsyncSession, connector_id: uuid.UUID
    ) -> ConnectorConfig:
        """Load and validate a connector config."""
        result = (
            await db.execute(
                select(ConnectorConfig).where(ConnectorConfig.id == connector_id)
            )
        ).scalar_one_or_none()

        if result is None:
            raise ConnectorNotFoundError(connector_id)
        if not result.is_active:
            raise ConnectorNotFoundError(connector_id)  # Treat inactive as not found

        return result

    async def _run_connector(self, connector: ConnectorConfig) -> dict[str, Any]:
        """
        Dispatch to the appropriate connector stub based on connector_type.

        Returns:
            Dict with {total, succeeded, failed} counts.
        """
        from app.modules.integrations.connectors import (
            DHIS2Connector,
            GenericFHIRConnector,
            OpenMRSConnector,
        )

        # Instantiate connector with config (credentials passed, not logged)
        if connector.connector_type == ConnectorType.OPENMRS:
            impl = OpenMRSConnector(
                connector.id, connector.base_url, connector.credentials
            )
            # STUB: pull patients as example sync operation
            await retry_with_backoff(
                lambda: impl.pull_patients(), connector_id=connector.id
            )
            return {"total": 0, "succeeded": 0, "failed": 0}

        elif connector.connector_type == ConnectorType.DHIS2:
            impl = DHIS2Connector(
                connector.id, connector.base_url, connector.credentials
            )
            # STUB: push empty aggregate data
            await retry_with_backoff(
                lambda: impl.push_aggregate_data("202601", "ORG_STUB", []),
                connector_id=connector.id,
            )
            return {"total": 0, "succeeded": 0, "failed": 0}

        else:
            # Generic FHIR
            impl = GenericFHIRConnector(
                connector.id, connector.base_url, connector.credentials
            )
            await retry_with_backoff(
                lambda: impl.sync_resource("Encounter", "outbound", []),
                connector_id=connector.id,
            )
            return {"total": 0, "succeeded": 0, "failed": 0}
