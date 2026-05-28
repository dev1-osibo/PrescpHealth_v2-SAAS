"""
Integration tests for the Patient API Router.

Validates the full request path for patient CRUD operations:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/patients — create patient (Doctor token)
- GET /api/v1/patients — list patients (Doctor token)
- GET /api/v1/patients/{id} — get single patient (Doctor token)

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
# Fixture: Seed a patient directly in DB for read tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def seeded_patient():
    """Insert a synthetic patient for GET tests, clean up after."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1990-01-01', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-TEST-{patient_id.hex[:8]}",
            "Test Patient",
            "Seeded",
            created_by,
        )
        yield patient_id
    finally:
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients — create patient
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_patient_returns_201(client, init_test_db, auth_headers):
    """Verify creating a patient returns 201 with standard envelope."""
    unique_mrn = f"MRN-INT-{uuid.uuid4().hex[:8]}"
    payload = {
        "medical_record_number": unique_mrn,
        "first_name": "Test Patient",
        "last_name": "Integration",
        "date_of_birth": "1985-06-15",
        "gender": "Female",
    }

    response = await client.post(
        "/api/v1/patients", json=payload, headers=auth_headers
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert body["data"]["first_name"] == "Test Patient"
    assert body["data"]["medical_record_number"] == unique_mrn

    # Cleanup: remove the created patient
    patient_id = body["data"]["id"]
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            "DELETE FROM patients WHERE id = $1", uuid.UUID(patient_id)
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients — list patients
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_patients_returns_200(client, init_test_db, auth_headers):
    """Verify listing patients returns 200 with paginated envelope."""
    response = await client.get("/api/v1/patients", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    # Paginated response has items, cursor, has_more
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id} — get single patient
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_patient_by_id_returns_200(
    client, init_test_db, auth_headers, seeded_patient
):
    """Verify fetching a specific patient by UUID returns 200."""
    response = await client.get(
        f"/api/v1/patients/{seeded_patient}", headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == str(seeded_patient)
    assert body["data"]["first_name"] == "Test Patient"
