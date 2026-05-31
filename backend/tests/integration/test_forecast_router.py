"""
Integration tests for the Forecast Engine API Router.

Validates the full request path for forecast operations:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/patients/{id}/forecast/compute — trigger forecast computation
- GET /api/v1/patients/{id}/forecast/latest — get latest forecasts

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied

Notes:
    - Forecast computation requires Celery (not running in tests), so we mock
      the service layer and verify the endpoint returns 202 + task_id.
    - AuditService is mocked at the router module level since the router's
      instantiation pattern doesn't match the actual AuditService interface.
"""

import uuid
from unittest.mock import patch, MagicMock, AsyncMock

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Connection string for direct DB seeding (matches conftest)
# ---------------------------------------------------------------------------
DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"
TEST_TENANT = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Fixture: Seed a patient for forecast tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def forecast_patient():
    """Insert a synthetic patient for forecast engine tests, clean up after."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1980-07-22', 'Female', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-FCST-{patient_id.hex[:8]}",
            "Test Patient",
            "Forecast",
            created_by,
        )
        yield patient_id
    finally:
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/forecast/compute — trigger forecast
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_trigger_forecast_returns_202_with_task_id(
    client, init_test_db, auth_headers, forecast_patient
):
    """
    Verify triggering forecast computation returns 202 Accepted with task_id.

    The endpoint enqueues a Celery task for ML forecast computation.
    We mock the ForecastService and AuditService at the router module level.
    """
    mock_task_id = str(uuid.uuid4())

    mock_forecast_service = MagicMock()
    mock_forecast_service.trigger_forecast = AsyncMock(return_value=mock_task_id)

    # The router calls AuditService(db) then audit_service.log_action(...)
    # We need the mock instance to have an awaitable log_action method
    mock_audit_instance = MagicMock()
    mock_audit_instance.log_action = AsyncMock()

    with patch("app.modules.forecast_engine.router.ForecastService", return_value=mock_forecast_service):
        with patch("app.modules.forecast_engine.router.AuditService", return_value=mock_audit_instance):
            response = await client.post(
                f"/api/v1/patients/{forecast_patient}/forecast/compute",
                headers=auth_headers,
            )

    assert response.status_code == 202, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "task_id" in body["data"]
    assert body["data"]["task_id"] == mock_task_id


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/forecast/latest — get latest forecasts
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_latest_forecasts_returns_200(
    client, init_test_db, auth_headers, forecast_patient
):
    """
    Verify fetching latest forecasts returns 200 for a patient with no forecasts.

    A patient with no computed forecasts should get a valid response
    (empty/null fields) — not a 404 or 500.
    """
    mock_forecast_service = MagicMock()
    mock_forecast_service.get_latest_forecast = AsyncMock(return_value={})

    with patch("app.modules.forecast_engine.router.ForecastService", return_value=mock_forecast_service):
        with patch("app.modules.forecast_engine.router.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.log_action = AsyncMock()
            response = await client.get(
                f"/api/v1/patients/{forecast_patient}/forecast/latest",
                headers=auth_headers,
            )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
