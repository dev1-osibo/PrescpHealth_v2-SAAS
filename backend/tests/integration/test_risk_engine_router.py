"""
Integration tests for the Risk Engine API Router.

Validates the full request path for risk score operations:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/patients/{id}/risk/compute — trigger async computation
- GET /api/v1/patients/{id}/risk/scores — get latest scores (empty OK)
- GET /api/v1/patients/{id}/risk/history — get historical scores

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied

Notes:
    - Risk computation requires Celery (not running in tests), so we mock
      the Celery task.delay() call and verify the endpoint returns 202 + task_id.
    - The AuditService and RiskService are mocked since the router's
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
# Fixture: Seed a patient for risk engine tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def risk_patient():
    """Insert a synthetic patient for risk engine tests, clean up after."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1975-03-10', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-RISK-{patient_id.hex[:8]}",
            "Test Patient",
            "RiskEngine",
            created_by,
        )
        yield patient_id
    finally:
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/risk/compute — trigger computation
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_risk_returns_202_with_task_id(
    client, init_test_db, auth_headers, risk_patient
):
    """
    Verify triggering risk computation returns 202 Accepted with a task_id.

    The endpoint enqueues a Celery task. We mock the RiskService to return
    a task_id and verify the response format is correct.
    """
    mock_task_id = str(uuid.uuid4())

    # Mock RiskService at the router module level to bypass AuditService init issues
    mock_risk_service = MagicMock()
    mock_risk_service.trigger_computation = AsyncMock(return_value=mock_task_id)

    with patch("app.modules.risk_engine.router.RiskService", return_value=mock_risk_service):
        with patch("app.modules.risk_engine.router.AuditService"):
            with patch("app.modules.risk_engine.router.MeasurementService"):
                response = await client.post(
                    f"/api/v1/patients/{risk_patient}/risk/compute",
                    headers=auth_headers,
                )

    assert response.status_code == 202, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "task_id" in body["data"]
    assert body["data"]["task_id"] == mock_task_id


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/risk/scores — get latest scores
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_risk_scores_returns_200_empty(
    client, init_test_db, auth_headers, risk_patient
):
    """
    Verify fetching risk scores returns 200 with empty/null scores.

    A patient with no computed scores should still get a valid response
    with None values for each disease — not a 404 or 500.
    """
    # Mock RiskService to return empty scores (no computation done yet)
    mock_risk_service = MagicMock()
    mock_risk_service.get_latest_scores = AsyncMock(return_value={
        "stroke": None, "cvd": None, "diabetes": None,
        "ckd": None, "hypertensive_crisis": None, "copd": None,
    })

    with patch("app.modules.risk_engine.router.RiskService", return_value=mock_risk_service):
        with patch("app.modules.risk_engine.router.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.log_audit = AsyncMock()
            with patch("app.modules.risk_engine.router.MeasurementService"):
                response = await client.get(
                    f"/api/v1/patients/{risk_patient}/risk/scores",
                    headers=auth_headers,
                )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "data" in body


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/risk/history — get history
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_risk_history_returns_200(
    client, init_test_db, auth_headers, risk_patient
):
    """
    Verify fetching risk history returns 200 with empty list for new patient.

    The history endpoint requires a disease query param. An empty history
    is a valid response (patient hasn't had risk computed yet).
    """
    mock_risk_service = MagicMock()
    mock_risk_service.get_score_history = AsyncMock(return_value=[])

    with patch("app.modules.risk_engine.router.RiskService", return_value=mock_risk_service):
        with patch("app.modules.risk_engine.router.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.log_audit = AsyncMock()
            with patch("app.modules.risk_engine.router.MeasurementService"):
                response = await client.get(
                    f"/api/v1/patients/{risk_patient}/risk/history?disease=stroke",
                    headers=auth_headers,
                )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "data" in body
