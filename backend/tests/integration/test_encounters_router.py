"""
Integration tests for the Encounter API Router.

Validates the full request path for encounter lifecycle:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/encounters — create encounter (Doctor token, needs patient)
- GET /api/v1/encounters — list encounters (Doctor token)
- GET /api/v1/patients/{id}/encounters — patient encounter history

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
"""

import uuid

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Connection string for direct DB seeding (matches conftest)
# ---------------------------------------------------------------------------
DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"
TEST_TENANT = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Fixture: Seed a patient for encounter tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def encounter_patient():
    """Insert a synthetic patient needed for encounter creation."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1988-05-20', 'Female', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-ENC-{patient_id.hex[:8]}",
            "Test Patient",
            "Encounter",
            created_by,
        )
        yield patient_id
    finally:
        # Clean up encounters first (FK), then patient
        await conn.execute(
            "DELETE FROM encounters WHERE patient_id = $1", patient_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/encounters — create encounter
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_encounter_returns_201(
    client, init_test_db, auth_headers, encounter_patient
):
    """Verify creating an encounter returns 201 with standard envelope."""
    payload = {
        "patient_id": str(encounter_patient),
        "reason_for_visit": "Routine checkup for integration test",
        "encounter_class": "ambulatory",
    }

    response = await client.post(
        "/api/v1/encounters", json=payload, headers=auth_headers
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["patient_id"] == str(encounter_patient)
    assert body["data"]["status"] in ("in_progress", "planned")
    assert "meta" in body


# ---------------------------------------------------------------------------
# Test: GET /api/v1/encounters — list encounters
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_encounters_returns_200(client, init_test_db, auth_headers):
    """Verify listing encounters returns 200 with paginated envelope."""
    response = await client.get("/api/v1/encounters", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    assert "total" in body["data"]


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/encounters — patient history
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_patient_encounters_returns_200(
    client, init_test_db, auth_headers, encounter_patient
):
    """Verify patient encounter history returns 200 (empty list is valid)."""
    response = await client.get(
        f"/api/v1/patients/{encounter_patient}/encounters",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
