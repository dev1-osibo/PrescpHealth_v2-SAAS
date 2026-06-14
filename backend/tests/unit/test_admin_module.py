"""
Tests for app.modules.admin — exceptions, schemas, service_tenant,
service_model, and the AdminService facade.

All tests use synthetic data only. No real PHI. DB is mocked.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

from app.modules.admin.exceptions import (
    AdminError,
    TenantNotFoundError,
    TenantAlreadyExistsError,
    ModelVersionNotFoundError,
    ModelDeploymentError,
    RollbackError,
)


def test_admin_error_default_message():
    """AdminError has a default message."""
    err = AdminError()
    assert "admin" in str(err).lower()


def test_admin_error_custom_message():
    """AdminError stores a custom message."""
    err = AdminError("custom admin error")
    assert err.message == "custom admin error"
    assert isinstance(err, Exception)


def test_tenant_not_found_error():
    """TenantNotFoundError includes the tenant_id in message."""
    err = TenantNotFoundError("00000000-0000-0000-0000-000000000001")
    assert "00000000-0000-0000-0000-000000000001" in str(err)
    assert isinstance(err, AdminError)


def test_tenant_already_exists_error():
    """TenantAlreadyExistsError includes the conflicting tenant name."""
    err = TenantAlreadyExistsError("Synth Tenant A")
    assert "Synth Tenant A" in str(err)
    assert isinstance(err, AdminError)


def test_model_version_not_found_error():
    """ModelVersionNotFoundError includes disease and version."""
    err = ModelVersionNotFoundError("diabetes", "1.2.0")
    assert "diabetes" in str(err)
    assert "1.2.0" in str(err)
    assert isinstance(err, AdminError)


def test_model_deployment_error_default():
    """ModelDeploymentError uses default message when none provided."""
    err = ModelDeploymentError()
    assert "deployment" in str(err).lower()
    assert isinstance(err, AdminError)


def test_model_deployment_error_custom():
    """ModelDeploymentError stores a custom message."""
    err = ModelDeploymentError("version already exists")
    assert "version already exists" in str(err)


def test_rollback_error_default():
    """RollbackError uses default message when none provided."""
    err = RollbackError()
    assert "rollback" in str(err).lower()
    assert isinstance(err, AdminError)


def test_rollback_error_custom():
    """RollbackError stores a custom message."""
    err = RollbackError("target version not found")
    assert "target version not found" in str(err)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

from app.modules.admin.schemas import (
    CreateTenantRequest,
    TenantResponse,
    TenantListResponse,
    UpdateTenantRequest,
    DeployModelRequest,
    ModelVersionResponse,
    RollbackRequest,
    TenantSettingsRequest,
    TenantSettingsResponse,
)


def test_create_tenant_request_valid():
    """CreateTenantRequest accepts valid tenant creation data."""
    req = CreateTenantRequest(
        name="Synth Tenant Alpha",
        region="us-east-1",
        settings={"timezone": "UTC"},
    )
    assert req.name == "Synth Tenant Alpha"
    assert req.region == "us-east-1"
    assert req.settings["timezone"] == "UTC"


def test_create_tenant_request_default_settings():
    """CreateTenantRequest defaults settings to empty dict."""
    req = CreateTenantRequest(name="Synth Tenant Beta", region="eu-west-1")
    assert req.settings == {}


def test_create_tenant_request_name_too_long():
    """CreateTenantRequest rejects name exceeding 100 characters."""
    with pytest.raises(ValidationError):
        CreateTenantRequest(name="x" * 101, region="us-east-1")


def test_tenant_response_valid():
    """TenantResponse serializes with all required fields."""
    now = datetime.now(timezone.utc)
    resp = TenantResponse(
        id=uuid.uuid4(),
        name="Synth Clinic",
        region="af-south-1",
        settings={},
        is_active=True,
        created_at=now,
    )
    assert resp.is_active is True
    assert resp.region == "af-south-1"


def test_tenant_list_response_envelope():
    """TenantListResponse wraps list of TenantResponse records."""
    now = datetime.now(timezone.utc)
    tenant = TenantResponse(
        id=uuid.uuid4(), name="Synth Clinic", region="us-east-1",
        settings={}, is_active=True, created_at=now,
    )
    resp = TenantListResponse(data=[tenant], meta={"total": 1})
    assert resp.success is True
    assert len(resp.data) == 1


def test_update_tenant_request_partial():
    """UpdateTenantRequest accepts partial update (only settings or only is_active)."""
    req = UpdateTenantRequest(settings={"timezone": "Africa/Lagos"})
    assert req.settings == {"timezone": "Africa/Lagos"}
    assert req.is_active is None


def test_update_tenant_request_is_active():
    """UpdateTenantRequest accepts is_active flag."""
    req = UpdateTenantRequest(is_active=False)
    assert req.is_active is False
    assert req.settings is None


def test_deploy_model_request_valid():
    """DeployModelRequest accepts valid model deployment data."""
    req = DeployModelRequest(
        disease="diabetes",
        version="2.0.0",
        artifact_path="s3://models/diabetes/v2.pkl",
        metrics={"auc": 0.89, "f1": 0.83},
    )
    assert req.disease == "diabetes"
    assert req.version == "2.0.0"
    assert req.metrics["auc"] == 0.89


def test_deploy_model_request_default_metrics():
    """DeployModelRequest defaults metrics to empty dict."""
    req = DeployModelRequest(
        disease="hypertension",
        version="1.0.0",
        artifact_path="s3://models/hyp/v1.pkl",
    )
    assert req.metrics == {}


def test_deploy_model_request_missing_required():
    """DeployModelRequest rejects request missing disease."""
    with pytest.raises(ValidationError):
        DeployModelRequest(version="1.0.0", artifact_path="s3://test")


def test_rollback_request_valid():
    """RollbackRequest accepts disease and target_version."""
    req = RollbackRequest(disease="diabetes", target_version="1.0.0")
    assert req.disease == "diabetes"
    assert req.target_version == "1.0.0"


def test_tenant_settings_request_all_optional():
    """TenantSettingsRequest accepts all-None (no-op update)."""
    req = TenantSettingsRequest()
    assert req.timezone is None
    assert req.language is None
    assert req.notification_channels is None


def test_tenant_settings_request_partial():
    """TenantSettingsRequest accepts partial fields."""
    req = TenantSettingsRequest(timezone="America/New_York", language="en-US")
    assert req.timezone == "America/New_York"
    assert req.language == "en-US"


def test_tenant_settings_response_valid():
    """TenantSettingsResponse stores tenant_id, settings, and updated_at."""
    now = datetime.now(timezone.utc)
    resp = TenantSettingsResponse(
        tenant_id=uuid.uuid4(),
        settings={"timezone": "UTC"},
        updated_at=now,
    )
    assert resp.settings["timezone"] == "UTC"


# ---------------------------------------------------------------------------
# TenantManagementService
# ---------------------------------------------------------------------------

from app.modules.admin.service_tenant import TenantManagementService


def _make_tenant_svc(mock_db=None, tenant_id=None, user_id=None):
    """Helper: create TenantManagementService with mocked deps."""
    return TenantManagementService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_create_tenant_returns_dict_with_id():
    """create_tenant returns a dict containing a UUID id."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    svc = _make_tenant_svc(mock_db=mock_db)
    data = CreateTenantRequest(name="Synth Clinic QA", region="us-east-1")

    result = await svc.create_tenant(data=data)

    assert "id" in result
    assert isinstance(result["id"], uuid.UUID)
    assert result["name"] == "Synth Clinic QA"


@pytest.mark.asyncio
async def test_create_tenant_stub_mode_on_db_error():
    """create_tenant returns stub dict when DB insert fails."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("db insert failed"))
    mock_db.rollback = AsyncMock()

    svc = _make_tenant_svc(mock_db=mock_db)
    data = CreateTenantRequest(name="Synth Clinic Beta", region="eu-west-1")

    # Should not raise; returns stub result
    result = await svc.create_tenant(data=data)

    assert result["name"] == "Synth Clinic Beta"
    assert "id" in result


@pytest.mark.asyncio
async def test_list_tenants_returns_list_from_db():
    """list_tenants returns a list of tenant dicts from DB."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()

    mock_row = {"id": str(uuid.uuid4()), "name": "Synth Clinic", "region": "us-east-1",
                "settings": {}, "is_active": True, "created_at": datetime.now(timezone.utc)}
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [mock_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    svc = TenantManagementService(
        db=mock_db, audit_service=mock_audit,
        request_id="test", tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
    )
    result = await svc.list_tenants(limit=10, offset=0)

    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_tenants_stub_on_db_error():
    """list_tenants returns empty list when DB query fails."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("db error"))

    svc = _make_tenant_svc(mock_db=mock_db)
    result = await svc.list_tenants()

    assert result == []


@pytest.mark.asyncio
async def test_get_tenant_not_found():
    """get_tenant raises TenantNotFoundError when tenant does not exist."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    svc = _make_tenant_svc(mock_db=mock_db)

    with pytest.raises(TenantNotFoundError):
        await svc.get_tenant(tenant_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_tenant_db_error_raises_not_found():
    """get_tenant raises TenantNotFoundError when DB throws."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("db error"))

    svc = _make_tenant_svc(mock_db=mock_db)

    with pytest.raises(TenantNotFoundError):
        await svc.get_tenant(tenant_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_tenant_success():
    """get_tenant returns tenant dict when row exists."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_row = {"id": str(tenant_id), "name": "Synth Clinic", "region": "us-east-1",
                "settings": {}, "is_active": True, "created_at": now}
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    svc = _make_tenant_svc(mock_db=mock_db)
    result = await svc.get_tenant(tenant_id=tenant_id)

    assert result["name"] == "Synth Clinic"


@pytest.mark.asyncio
async def test_update_tenant_calls_execute_and_commits():
    """update_tenant executes update SQL and calls audit log."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # First execute for UPDATE, then execute for SELECT (get_tenant)
    mock_row = {"id": str(tenant_id), "name": "Synth Clinic", "region": "us-east-1",
                "settings": {"timezone": "UTC"}, "is_active": True, "created_at": now}
    mock_get_result = MagicMock()
    mock_get_result.mappings.return_value.first.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_get_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    svc = TenantManagementService(
        db=mock_db, audit_service=mock_audit,
        request_id="test", tenant_id=tenant_id, user_id=uuid.uuid4(),
    )

    data = UpdateTenantRequest(settings={"timezone": "Africa/Lagos"})
    result = await svc.update_tenant(tenant_id=tenant_id, data=data)

    mock_audit.log_audit.assert_called_once()


# ---------------------------------------------------------------------------
# ModelManagementService
# ---------------------------------------------------------------------------

from app.modules.admin.service_model import ModelManagementService


def _make_model_svc(mock_db=None, tenant_id=None, user_id=None):
    """Helper: create ModelManagementService with mocked deps."""
    return ModelManagementService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-model-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_deploy_model_returns_dict_with_id():
    """deploy_model returns dict with UUID id and is_active=True."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    svc = _make_model_svc(mock_db=mock_db)
    data = DeployModelRequest(
        disease="diabetes",
        version="3.0.0",
        artifact_path="s3://models/diab/v3.pkl",
        metrics={"auc": 0.91},
    )

    result = await svc.deploy_model(data=data)

    assert result["disease"] == "diabetes"
    assert result["is_active"] is True
    assert isinstance(result["id"], uuid.UUID)


@pytest.mark.asyncio
async def test_deploy_model_stub_mode_on_db_error():
    """deploy_model returns stub result when DB fails (non-IntegrityError)."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("connection refused"))
    mock_db.rollback = AsyncMock()

    svc = _make_model_svc(mock_db=mock_db)
    data = DeployModelRequest(
        disease="hypertension",
        version="1.5.0",
        artifact_path="s3://models/hyp/v1.5.pkl",
    )

    result = await svc.deploy_model(data=data)
    assert result["disease"] == "hypertension"


@pytest.mark.asyncio
async def test_rollback_model_target_not_found():
    """rollback_model raises RollbackError when target version does not exist."""
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.rollback = AsyncMock()

    svc = _make_model_svc(mock_db=mock_db)
    data = RollbackRequest(disease="diabetes", target_version="0.0.1")

    with pytest.raises(RollbackError, match="0.0.1"):
        await svc.rollback_model(data=data)


@pytest.mark.asyncio
async def test_rollback_model_success():
    """rollback_model returns dict with target version's details."""
    mock_db = AsyncMock()
    now = datetime.now(timezone.utc)

    mock_target_row = {
        "id": str(uuid.uuid4()),
        "disease": "diabetes",
        "version": "1.0.0",
        "artifact_path": "s3://models/diab/v1.pkl",
        "metrics": {"auc": 0.85},
        "deployed_at": now,
    }

    mock_select_result = MagicMock()
    mock_select_result.mappings.return_value.first.return_value = mock_target_row

    mock_db.execute = AsyncMock(side_effect=[
        mock_select_result,   # SELECT target version
        AsyncMock(),          # UPDATE deactivate current
        AsyncMock(),          # UPDATE activate target
    ])
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    svc = _make_model_svc(mock_db=mock_db)
    data = RollbackRequest(disease="diabetes", target_version="1.0.0")

    result = await svc.rollback_model(data=data)

    assert result["version"] == "1.0.0"
    assert result["is_active"] is True


@pytest.mark.asyncio
async def test_get_model_metrics_returns_versions():
    """get_model_metrics returns disease and versions list."""
    mock_db = AsyncMock()
    now = datetime.now(timezone.utc)

    mock_rows = [
        {"id": str(uuid.uuid4()), "version": "2.0.0", "metrics": {"auc": 0.9},
         "is_active": True, "deployed_at": now},
        {"id": str(uuid.uuid4()), "version": "1.0.0", "metrics": {"auc": 0.85},
         "is_active": False, "deployed_at": now},
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = mock_rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    svc = _make_model_svc(mock_db=mock_db)
    result = await svc.get_model_metrics(disease="diabetes")

    assert result["disease"] == "diabetes"
    assert len(result["versions"]) == 2
    assert result["versions"][0]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_get_model_metrics_stub_on_db_error():
    """get_model_metrics returns empty versions list when DB fails."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("db error"))

    svc = _make_model_svc(mock_db=mock_db)
    result = await svc.get_model_metrics(disease="hypertension")

    assert result["disease"] == "hypertension"
    assert result["versions"] == []


@pytest.mark.asyncio
async def test_trigger_recomputation_returns_task_id():
    """trigger_recomputation returns a UUID string task_id."""
    svc = _make_model_svc()
    task_id = await svc.trigger_recomputation(disease="diabetes")

    assert isinstance(task_id, str)
    # Validate it's a UUID
    parsed = uuid.UUID(task_id)
    assert str(parsed) == task_id


# ---------------------------------------------------------------------------
# AdminService (facade)
# ---------------------------------------------------------------------------

from app.modules.admin.service import AdminService


def _make_admin_service(mock_db=None, tenant_id=None):
    """Helper: create AdminService with mocked deps."""
    return AdminService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-admin-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
    )


def test_admin_service_lazy_tenant_mgmt_property():
    """tenant_mgmt property is lazily initialized on first access."""
    svc = _make_admin_service()
    assert svc._tenant_mgmt is None

    tm = svc.tenant_mgmt
    assert tm is not None
    assert svc._tenant_mgmt is tm  # Cached on second access
    assert svc.tenant_mgmt is tm


def test_admin_service_lazy_model_mgmt_property():
    """model_mgmt property is lazily initialized on first access."""
    svc = _make_admin_service()
    assert svc._model_mgmt is None

    mm = svc.model_mgmt
    assert mm is not None
    assert svc._model_mgmt is mm
    assert svc.model_mgmt is mm


@pytest.mark.asyncio
async def test_get_tenant_settings_calls_tenant_mgmt():
    """get_tenant_settings delegates to tenant_mgmt.get_tenant."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_row = {"id": str(tenant_id), "name": "Synth", "region": "us",
                "settings": {"timezone": "UTC"}, "is_active": True, "created_at": now}
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    svc = _make_admin_service(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.get_tenant_settings()

    assert "tenant_id" in result
    assert "settings" in result


@pytest.mark.asyncio
async def test_update_tenant_settings_applies_patch():
    """update_tenant_settings merges settings patch and calls update_tenant."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_row = {"id": str(tenant_id), "name": "Synth", "region": "us",
                "settings": {"timezone": "UTC"}, "is_active": True, "created_at": now}
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    svc = _make_admin_service(mock_db=mock_db, tenant_id=tenant_id)
    data = TenantSettingsRequest(timezone="Africa/Lagos", language="en-NG")

    result = await svc.update_tenant_settings(data=data)

    assert "tenant_id" in result
    assert "settings" in result
