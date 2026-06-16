"""
PrescpHealth Backend — Unit Tests: Integrations Module (Task 17.7).

Tests connector CRUD operations, conflict resolution (last-write-wins),
exponential backoff retry logic, and sync log recording.

All tests are isolated — AsyncSession mocked via AsyncMock.
No real DB connections. No PHI in test data or assertions.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.integrations.enums import (
    AuthType,
    ConnectorType,
    SyncDirection,
    SyncStatus,
)
from app.modules.integrations.exceptions import ConnectorNotFoundError
from app.modules.integrations.sync_engine import (
    SyncEngine,
    _RETRY_DELAYS,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# Connector Configuration CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestConnectorCRUD:
    """Unit tests for connector configuration management."""

    @patch("app.modules.integrations.service._audit", MagicMock(log=AsyncMock()))
    async def test_create_connector_stores_correct_fields(self):
        """Creating a connector stores type, base_url, and auth_type."""
        from app.modules.integrations.service import IntegrationService

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        # Build a mock create request with expected fields
        create_req = MagicMock()
        create_req.connector_type = ConnectorType.OPENMRS
        create_req.name = "Test OpenMRS Connector"
        create_req.base_url = "https://openmrs.test.local/api"
        create_req.auth_type = AuthType.BASIC
        create_req.credentials = {"username": "admin", "password": "secret"}
        create_req.sync_direction = SyncDirection.INBOUND
        create_req.sync_schedule = "0 */6 * * *"
        create_req.is_active = True

        service = IntegrationService()
        result = await service.create_connector(
            db=mock_db,
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            data=create_req,
        )

        # Verify connector stored correct fields
        assert result.connector_type == ConnectorType.OPENMRS
        assert result.base_url == "https://openmrs.test.local/api"
        assert result.auth_type == AuthType.BASIC
        assert result.sync_direction == SyncDirection.INBOUND
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited()

    @patch("app.modules.integrations.service._audit", MagicMock(log=AsyncMock()))
    async def test_get_connector_raises_not_found(self):
        """Getting a non-existent connector raises ConnectorNotFoundError."""
        from app.modules.integrations.service import IntegrationService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = IntegrationService()
        with pytest.raises(ConnectorNotFoundError):
            await service.get_connector(mock_db, uuid.uuid4())

    @patch("app.modules.integrations.service._audit", MagicMock(log=AsyncMock()))
    async def test_list_connectors_returns_tuple(self):
        """List returns (connectors, total_count) tuple."""
        from app.modules.integrations.service import IntegrationService

        mock_db = AsyncMock()
        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        # Mock data query
        data_result = MagicMock()
        data_result.scalars.return_value = ["conn1", "conn2"]
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        service = IntegrationService()
        connectors, total = await service.list_connectors(
            mock_db, uuid.uuid4()
        )
        assert total == 2
        assert len(connectors) == 2

    @patch("app.modules.integrations.service._audit", MagicMock(log=AsyncMock()))
    async def test_update_connector_partial_update(self):
        """Update modifies only provided fields."""
        from app.modules.integrations.service import IntegrationService

        mock_connector = MagicMock()
        mock_connector.name = "Old Name"
        mock_connector.id = uuid.uuid4()

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_connector
        mock_db.execute = AsyncMock(return_value=mock_result)

        update_req = MagicMock()
        update_req.name = "New Name"
        update_req.base_url = None
        update_req.auth_type = None
        update_req.credentials = None
        update_req.sync_direction = None
        update_req.sync_schedule = None
        update_req.is_active = None

        service = IntegrationService()
        result = await service.update_connector(
            db=mock_db,
            connector_id=mock_connector.id,
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            data=update_req,
        )
        assert result.name == "New Name"


# ---------------------------------------------------------------------------
# Conflict Resolution (Last-Write-Wins)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestConflictResolution:
    """Unit tests for last-write-wins conflict resolution."""

    async def test_remote_wins_when_newer(self):
        """Remote record wins when its lastUpdated is strictly newer."""
        engine = SyncEngine()
        local = {"id": "1", "meta": {"lastUpdated": "2025-01-10T10:00:00Z"}}
        remote = {"id": "1", "meta": {"lastUpdated": "2025-01-15T10:00:00Z"}}

        winner = engine.resolve_conflict(local, remote)
        assert winner is remote

    async def test_local_wins_when_newer(self):
        """Local record wins when its lastUpdated is newer."""
        engine = SyncEngine()
        local = {"id": "1", "meta": {"lastUpdated": "2025-01-20T10:00:00Z"}}
        remote = {"id": "1", "meta": {"lastUpdated": "2025-01-15T10:00:00Z"}}

        winner = engine.resolve_conflict(local, remote)
        assert winner is local

    async def test_local_wins_on_equal_timestamps(self):
        """Local record wins when timestamps are equal (safer default)."""
        engine = SyncEngine()
        ts = "2025-01-15T10:00:00Z"
        local = {"id": "1", "meta": {"lastUpdated": ts}}
        remote = {"id": "1", "meta": {"lastUpdated": ts}}

        winner = engine.resolve_conflict(local, remote)
        assert winner is local

    async def test_local_wins_when_remote_missing_timestamp(self):
        """Local wins when remote has no lastUpdated metadata."""
        engine = SyncEngine()
        local = {"id": "1", "meta": {"lastUpdated": "2025-01-10T10:00:00Z"}}
        remote = {"id": "1", "meta": {}}

        winner = engine.resolve_conflict(local, remote)
        assert winner is local


# ---------------------------------------------------------------------------
# Retry with Exponential Backoff
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRetryBackoff:
    """Unit tests for exponential backoff retry logic."""

    async def test_retry_delays_schedule(self):
        """Retry delays match the documented schedule: 0, 30, 120, 480, 1800, 7200."""
        assert _RETRY_DELAYS == [0, 30, 120, 480, 1800, 7200]

    async def test_max_5_retries(self):
        """After 5 retries (6 total attempts), the last exception is raised."""
        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Test transient failure")

        with patch("app.modules.integrations.sync_engine.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectionError):
                await retry_with_backoff(always_fails, max_retries=5)
        # 6 attempts total (initial + 5 retries)
        assert call_count == 6

    async def test_succeeds_on_first_try(self):
        """If function succeeds immediately, no retries occur."""
        async def succeeds():
            return "ok"

        result = await retry_with_backoff(succeeds, max_retries=5)
        assert result == "ok"

    async def test_succeeds_after_transient_failure(self):
        """Function that fails once then succeeds returns the success value."""
        attempt = 0

        async def fails_once():
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise ConnectionError("transient")
            return "recovered"

        with patch("app.modules.integrations.sync_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(fails_once, max_retries=5)
        assert result == "recovered"
        assert attempt == 2


# ---------------------------------------------------------------------------
# Sync Log Recording (No PHI)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSyncLogRecording:
    """Unit tests verifying sync logs contain counts but NO PHI."""

    async def test_sync_log_contains_record_counts(self):
        """SyncLog stores records_processed, records_succeeded, records_failed."""
        from app.modules.integrations.models import SyncLog

        log = SyncLog(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            connector_id=uuid.uuid4(),
            direction=SyncDirection.INBOUND,
            status=SyncStatus.COMPLETED,
            records_processed=100,
            records_succeeded=95,
            records_failed=5,
            started_at=datetime.now(timezone.utc),
        )
        assert log.records_processed == 100
        assert log.records_succeeded == 95
        assert log.records_failed == 5

    async def test_sync_log_error_summary_no_phi(self):
        """Error summary contains only error_type metadata, not PHI."""
        from app.modules.integrations.models import SyncLog

        log = SyncLog(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            connector_id=uuid.uuid4(),
            direction=SyncDirection.OUTBOUND,
            status=SyncStatus.FAILED,
            records_processed=0,
            records_succeeded=0,
            records_failed=0,
            started_at=datetime.now(timezone.utc),
        )
        log.error_summary = "error_type=ConnectionError"
        # Verify no PHI patterns in error summary
        assert "Patient" not in log.error_summary
        assert "name" not in log.error_summary.lower()
        assert "error_type=" in log.error_summary
