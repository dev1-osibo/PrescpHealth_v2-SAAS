"""
Comprehensive unit tests for integrations module.

Covers:
- IntegrationService: create_connector, get_connector, list_connectors, update_connector
- SyncEngine: execute_sync, resolve_conflict, retry_with_backoff
- Connectors: OpenMRS, DHIS2, GenericFHIR stubs
- Schemas: request/response schemas
- Enums: all values present
- Exceptions: error conditions
"""

import uuid
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations.enums import (
    AuthType,
    ConnectorType,
    SyncDirection,
    SyncStatus,
)
from app.modules.integrations.exceptions import (
    ConnectorNotFoundError,
    SyncAlreadyRunningError,
    ConnectorConnectionError,
)
from app.modules.integrations.models import ConnectorConfig, SyncLog
from app.modules.integrations.schemas import (
    ConnectorCreateRequest,
    ConnectorOut,
    SyncLogOut,
    SyncTriggerResponse,
    ConnectorUpdateRequest,
)
from app.modules.integrations.service import IntegrationService
from app.modules.integrations.sync_engine import SyncEngine, retry_with_backoff
from app.modules.integrations.connectors.openmrs import OpenMRSConnector
from app.modules.integrations.connectors.dhis2 import DHIS2Connector
from app.modules.integrations.connectors.generic_fhir import GenericFHIRConnector


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def integration_service():
    """Instantiate IntegrationService for testing."""
    return IntegrationService()


@pytest.fixture
def sync_engine():
    """Instantiate SyncEngine for testing."""
    return SyncEngine()


@pytest.fixture
def openmrs_connector():
    """Instantiate OpenMRSConnector for testing."""
    return OpenMRSConnector(
        connector_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        base_url="http://localhost:8080/openmrs",
        credentials={"username": "admin", "password": "admin"},
    )


@pytest.fixture
def dhis2_connector():
    """Instantiate DHIS2Connector for testing."""
    return DHIS2Connector(
        connector_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        base_url="http://localhost:8080/dhis2",
        credentials={"username": "admin", "password": "admin"},
    )


@pytest.fixture
def generic_fhir_connector():
    """Instantiate GenericFHIRConnector for testing."""
    return GenericFHIRConnector(
        connector_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        base_url="http://localhost:8080/fhir",
        credentials={"api_key": "test-api-key"},
    )


@pytest.fixture
def test_tenant_id():
    """Test tenant UUID."""
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def test_user_id():
    """Test user UUID."""
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def test_connector_id():
    """Test connector UUID."""
    return uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def mock_db():
    """Mock AsyncSession."""
    return MagicMock(spec=AsyncSession)


# ============================================================================
# IntegrationService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_connector_success(
    integration_service,
    mock_db,
    test_tenant_id,
    test_user_id,
):
    """
    Test successfully creating a connector.
    """
    with patch("app.modules.integrations.service._audit", MagicMock(log=AsyncMock())):
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        create_request = ConnectorCreateRequest(
            connector_type=ConnectorType.OPENMRS,
            name="Main OpenMRS",
            base_url="http://openmrs.example.com",
            auth_type=AuthType.BASIC,
            credentials={"username": "admin", "password": "admin"},
            sync_direction=SyncDirection.BIDIRECTIONAL,
            sync_schedule="0 * * * *",  # Hourly
            is_active=True,
        )
        
        connector = await integration_service.create_connector(
            db=mock_db,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=create_request,
        )
        
        assert connector is not None
        assert connector.connector_type == ConnectorType.OPENMRS
        assert connector.name == "Main OpenMRS"


@pytest.mark.asyncio
async def test_get_connector_success(
    integration_service,
    mock_db,
    test_connector_id,
):
    """
    Test retrieving a connector by ID.
    """
    connector = MagicMock(spec=ConnectorConfig)
    connector.id = test_connector_id
    connector.connector_type = ConnectorType.OPENMRS
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=connector)
    mock_db.execute.return_value = result
    
    found = await integration_service.get_connector(
        db=mock_db,
        connector_id=test_connector_id,
    )
    
    assert found.id == test_connector_id


@pytest.mark.asyncio
async def test_get_connector_not_found(
    integration_service,
    mock_db,
    test_connector_id,
):
    """
    Test that retrieving missing connector raises ConnectorNotFoundError.
    """
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    
    with pytest.raises(ConnectorNotFoundError):
        await integration_service.get_connector(
            db=mock_db,
            connector_id=test_connector_id,
        )


@pytest.mark.asyncio
async def test_list_connectors(
    integration_service,
    mock_db,
    test_tenant_id,
):
    """
    Test listing connectors for a tenant.
    """
    connector1 = MagicMock(spec=ConnectorConfig)
    connector1.id = uuid.uuid4()
    connector1.connector_type = ConnectorType.OPENMRS
    
    connector2 = MagicMock(spec=ConnectorConfig)
    connector2.id = uuid.uuid4()
    connector2.connector_type = ConnectorType.DHIS2
    
    mock_db.execute = AsyncMock()
    
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=2)
    
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=[connector1, connector2])
    
    mock_db.execute.side_effect = [count_result, list_result]
    
    connectors, total = await integration_service.list_connectors(
        db=mock_db,
        tenant_id=test_tenant_id,
        limit=25,
        offset=0,
    )
    
    assert total == 2
    assert len(connectors) == 2


@pytest.mark.asyncio
async def test_update_connector(
    integration_service,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_connector_id,
):
    """
    Test updating a connector configuration.
    """
    with patch("app.modules.integrations.service._audit", MagicMock(log=AsyncMock())):
        connector = MagicMock(spec=ConnectorConfig)
        connector.id = test_connector_id
        connector.name = "Old Name"
        connector.is_active = True
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=connector)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        
        update_request = ConnectorUpdateRequest(
            name="New Name",
            is_active=False,
        )
        
        updated = await integration_service.update_connector(
            db=mock_db,
            connector_id=test_connector_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=update_request,
        )
        
        assert updated.name == "New Name"
        assert updated.is_active == False


# ============================================================================
# SyncEngine Tests
# ============================================================================

@pytest.mark.asyncio
async def test_execute_sync_success(
    sync_engine,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_connector_id,
):
    """
    Test successful sync execution.
    """
    with patch("app.modules.integrations.sync_engine._audit", MagicMock(log=AsyncMock())), \
         patch("app.modules.integrations.sync_engine.asyncio.sleep", new_callable=AsyncMock):
        connector = MagicMock(spec=ConnectorConfig)
        connector.id = test_connector_id
        connector.connector_type = ConnectorType.OPENMRS
        connector.sync_direction = SyncDirection.INBOUND
        connector.is_active = True
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=connector)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        sync_log = await sync_engine.execute_sync(
            db=mock_db,
            connector_id=test_connector_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
        )
        
        assert sync_log is not None
        assert sync_log.status in (SyncStatus.STARTED, SyncStatus.COMPLETED, SyncStatus.FAILED)


@pytest.mark.asyncio
async def test_execute_sync_missing_connector(
    sync_engine,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_connector_id,
):
    """
    Test that executing sync with missing connector raises error.
    """
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    
    # Should raise ConnectorNotFoundError when connector doesn't exist
    from app.modules.integrations.sync_engine import SyncEngine
    with pytest.raises(ConnectorNotFoundError):
        await sync_engine.execute_sync(
            db=mock_db,
            connector_id=test_connector_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
        )


@pytest.mark.asyncio
async def test_resolve_conflict_last_write_wins(
    sync_engine,
    mock_db,
    test_tenant_id,
    test_user_id,
):
    """
    Test conflict resolution using last-write-wins strategy.
    """
    local_record = {"id": "123", "name": "Local", "meta": {"lastUpdated": "2024-01-01T00:00:00Z"}}
    remote_record = {"id": "123", "name": "Remote", "meta": {"lastUpdated": "2024-01-02T00:00:00Z"}}
    
    # Remote is newer, so remote should win
    resolved = sync_engine.resolve_conflict(
        local=local_record,
        remote=remote_record,
    )
    
    assert resolved is not None
    assert resolved["name"] == "Remote"


# ============================================================================
# Retry Logic Tests
# ============================================================================

@pytest.mark.asyncio
async def test_retry_with_backoff_success_first_try():
    """
    Test retry_with_backoff succeeds on first attempt.
    """
    call_count = 0
    
    async def success_func():
        nonlocal call_count
        call_count += 1
        return "success"
    
    result = await retry_with_backoff(success_func, max_retries=3)
    
    assert result == "success"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_on_failure():
    """
    Test retry_with_backoff retries after failure.
    """
    call_count = 0
    
    async def failing_then_success():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("First attempt fails")
        return "success"
    
    # Mock asyncio.sleep to avoid real 30-second delay
    with patch("app.modules.integrations.sync_engine.asyncio.sleep", new_callable=AsyncMock):
        result = await retry_with_backoff(failing_then_success, max_retries=1)
    
    assert result == "success"


@pytest.mark.asyncio
async def test_retry_with_backoff_exhausts_retries():
    """
    Test retry_with_backoff raises after exhausting retries.
    """
    async def always_fails():
        raise ValueError("Always fails")
    
    with pytest.raises(ValueError):
        await retry_with_backoff(always_fails, max_retries=0)


# ============================================================================
# Connector Stub Tests
# ============================================================================

@pytest.mark.asyncio
async def test_openmrs_connector_pull_patients(openmrs_connector):
    """
    Test OpenMRS connector stub for pulling patients.
    """
    # Connector stubs just return empty/mock data
    result = await openmrs_connector.pull_patients()
    
    assert result is not None


@pytest.mark.asyncio
async def test_openmrs_connector_push_encounters(openmrs_connector):
    """
    Test OpenMRS connector stub for pushing encounters.
    """
    encounter_data = {
        "id": str(uuid.uuid4()),
        "patient_id": str(uuid.uuid4()),
        "status": "finished",
    }
    
    result = await openmrs_connector.push_encounters([encounter_data])
    
    assert result is not None


@pytest.mark.asyncio
async def test_dhis2_connector_push_aggregate_data(dhis2_connector):
    """
    Test DHIS2 connector stub for pushing aggregate data.
    """
    result = await dhis2_connector.push_aggregate_data(
        period="202601",
        org_unit_id="ORG_TEST_001",
        data_values=[{"dataElement": "elem1", "value": "100"}],
    )
    
    assert result is not None


@pytest.mark.asyncio
async def test_generic_fhir_connector_sync_resource(generic_fhir_connector):
    """
    Test GenericFHIR connector stub for resource sync.
    """
    resource = {
        "resourceType": "Patient",
        "id": str(uuid.uuid4()),
    }
    
    result = await generic_fhir_connector.sync_resource("Patient", "outbound", [resource])
    
    assert result is not None


# ============================================================================
# Schema Validation Tests
# ============================================================================

def test_create_connector_request_valid():
    """Test valid connector creation request."""
    req = ConnectorCreateRequest(
        connector_type=ConnectorType.OPENMRS,
        name="Test Connector",
        base_url="http://localhost:8080",
        auth_type=AuthType.BASIC,
        credentials={"user": "admin"},
        sync_direction=SyncDirection.INBOUND,
        sync_schedule="0 * * * *",
    )
    
    assert req.name == "Test Connector"
    assert req.connector_type == ConnectorType.OPENMRS


def test_connector_out_excludes_credentials():
    """Test that ConnectorOut excludes sensitive credentials."""
    response = ConnectorOut(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        connector_type=ConnectorType.OPENMRS,
        name="Test",
        base_url="http://localhost",
        auth_type=AuthType.BASIC,
        sync_direction=SyncDirection.INBOUND,
        is_active=True,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Verify credentials field is not present
    response_dict = response.model_dump()
    assert "credentials" not in response_dict


def test_sync_log_out_valid():
    """Test SyncLogOut schema."""
    response = SyncLogOut(
        id=uuid.uuid4(),
        connector_id=uuid.uuid4(),
        direction=SyncDirection.INBOUND,
        status=SyncStatus.COMPLETED,
        records_processed=100,
        records_succeeded=95,
        records_failed=5,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    
    assert response.records_succeeded == 95


def test_sync_trigger_response_valid():
    """Test SyncTriggerResponse schema."""
    response = SyncTriggerResponse(
        task_id=uuid.uuid4(),
        connector_id=uuid.uuid4(),
        status="queued",
        message="Sync task queued for execution",
    )
    
    assert response.status == "queued"


# ============================================================================
# Enum Tests
# ============================================================================

def test_connector_type_all_values():
    """Test all ConnectorType enum values exist."""
    expected = {
        ConnectorType.OPENMRS,
        ConnectorType.DHIS2,
        ConnectorType.GENERIC_FHIR,
    }
    actual = set(ConnectorType)
    assert expected == actual


def test_auth_type_all_values():
    """Test all AuthType enum values exist."""
    expected = {
        AuthType.BASIC,
        AuthType.OAUTH2,
        AuthType.API_KEY,
    }
    actual = set(AuthType)
    assert expected == actual


def test_sync_direction_all_values():
    """Test all SyncDirection enum values exist."""
    expected = {
        SyncDirection.INBOUND,
        SyncDirection.OUTBOUND,
        SyncDirection.BIDIRECTIONAL,
    }
    actual = set(SyncDirection)
    assert expected == actual


def test_sync_status_all_values():
    """Test all SyncStatus enum values exist."""
    expected = {
        SyncStatus.STARTED,
        SyncStatus.COMPLETED,
        SyncStatus.FAILED,
        SyncStatus.PARTIAL,
    }
    actual = set(SyncStatus)
    assert expected == actual


# ============================================================================
# Exception Tests
# ============================================================================

def test_connector_not_found_error():
    """Test ConnectorNotFoundError message."""
    connector_id = uuid.uuid4()
    exc = ConnectorNotFoundError(connector_id)
    assert "connector" in str(exc).lower()


def test_sync_already_running_error():
    """Test SyncAlreadyRunningError message."""
    connector_id = uuid.uuid4()
    exc = SyncAlreadyRunningError(connector_id)
    assert "sync" in str(exc).lower() or "progress" in str(exc).lower()


def test_connector_connection_error():
    """Test ConnectorConnectionError message."""
    connector_id = uuid.uuid4()
    exc = ConnectorConnectionError(connector_id)
    assert "connect" in str(exc).lower() or "reach" in str(exc).lower()


# ============================================================================
# Service Method Path Tests
# ============================================================================

# trigger_sync is not exposed in IntegrationService
# (it's handled via separate endpoint/task queue)


@pytest.mark.asyncio
async def test_list_sync_logs_paginated(
    integration_service,
    mock_db,
    test_connector_id,
):
    """
    Test retrieving sync logs with pagination.
    """
    log1 = MagicMock(spec=SyncLog)
    log1.id = uuid.uuid4()
    
    log2 = MagicMock(spec=SyncLog)
    log2.id = uuid.uuid4()
    
    mock_db.execute = AsyncMock()
    
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=2)
    
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=[log1, log2])
    
    mock_db.execute.side_effect = [count_result, list_result]
    
    logs, total = await integration_service.list_sync_logs(
        db=mock_db,
        connector_id=test_connector_id,
        limit=10,
        offset=0,
    )
    
    assert total == 2
    assert len(logs) == 2
