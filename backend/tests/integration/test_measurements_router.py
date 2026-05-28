"""
Integration tests for the Measurement API Router.

Validates the full request path for clinical measurement management:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/patients/{id}/measurements — save measurement
- GET /api/v1/patients/{id}/measurements — list history
- GET /api/v1/patients/{id}/measurements/latest — latest per type

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
"""

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Connection string for direct DB seeding (matches conftest)
# ---------------------------------------------------------------------------
DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"
TEST_TENANT = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Fixture: Seed a patient for measurement tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def measurement_patient():
    """Insert a synthetic patient for measurement endpoints."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1980-07-12', 'Female', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-MEAS-{patient_id.hex[:8]}",
            "Test Patient",
            "Measurement",
            created_by,
        )
        yield patient_id
    finally:
        await conn.execute(
            "DELETE FROM measurements WHERE patient_id = $1", patient_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/measurements — save measurement
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_measurement_returns_201(
    client, init_test_db, auth_headers, measurement_patient
):
    """Verify saving a measurement returns 201 with standard envelope."""
    payload = {
        "measurement_type": "systolic_bp",
        "value": 120.0,
        "unit": "mmHg",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
    }

    response = await client.post(
        f"/api/v1/patients/{measurement_patient}/measurements",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["measurement_type"] == "systolic_bp"
    assert body["data"]["value"] == 120.0
    assert body["data"]["patient_id"] == str(measurement_patient)


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/measurements — list history
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_measurements_returns_200(
    client, init_test_db, auth_headers, measurement_patient
):
    """Verify listing measurement history returns 200 with pagination."""
    response = await client.get(
        f"/api/v1/patients/{measurement_patient}/measurements",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    assert "has_more" in body["data"]


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/measurements/latest — latest per type
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_latest_measurements_returns_200(
    client, init_test_db, auth_headers, measurement_patient
):
    """Verify latest measurements endpoint returns 200 (empty is valid)."""
    response = await client.get(
        f"/api/v1/patients/{measurement_patient}/measurements/latest",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
