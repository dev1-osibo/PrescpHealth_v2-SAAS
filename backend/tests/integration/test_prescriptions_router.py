"""
Integration tests for the Prescription API Router.

Validates the full request path for prescription management:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/prescriptions — write prescription (Doctor token)
- GET /api/v1/prescriptions — list prescriptions (Doctor token)
- GET /api/v1/patients/{id}/prescriptions — patient prescription history

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
    - ATC code in code_catalogs for validation
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
# Fixture: Seed patient + ATC code for prescription tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def prescription_patient():
    """Insert a synthetic patient and ATC code for prescription creation."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1975-11-10', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-RX-{patient_id.hex[:8]}",
            "Test Patient",
            "Prescription",
            created_by,
        )
        # Ensure ATC code exists for validation
        await conn.execute(
            """
            INSERT INTO code_catalogs (catalog_type, code, display_name_en, is_active)
            VALUES ('atc', 'A10BA02', 'Metformin', true)
            ON CONFLICT (catalog_type, code) DO NOTHING
            """,
        )
        yield patient_id
    finally:
        await conn.execute(
            "DELETE FROM prescriptions WHERE patient_id = $1", patient_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/prescriptions — write prescription
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_prescription_returns_201(
    client, init_test_db, auth_headers, prescription_patient
):
    """Verify writing a prescription returns 201 with standard envelope."""
    payload = {
        "patient_id": str(prescription_patient),
        "drug_name": "Metformin",
        "atc_code": "A10BA02",
        "dosage": "500mg",
        "frequency": "twice daily",
        "duration_days": 90,
        "route": "oral",
        "refills_allowed": 3,
    }

    response = await client.post(
        "/api/v1/prescriptions", json=payload, headers=auth_headers
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["drug_name"] == "Metformin"
    assert body["data"]["patient_id"] == str(prescription_patient)
    assert body["data"]["status"] in ("active", "Active")


# ---------------------------------------------------------------------------
# Test: GET /api/v1/prescriptions — list prescriptions
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_prescriptions_returns_200(
    client, init_test_db, auth_headers
):
    """Verify listing prescriptions returns 200 with paginated envelope."""
    response = await client.get("/api/v1/prescriptions", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    assert "total" in body["data"]


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/prescriptions — patient history
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_patient_prescriptions_returns_200(
    client, init_test_db, auth_headers, prescription_patient
):
    """Verify patient prescription history returns 200 (empty list valid)."""
    response = await client.get(
        f"/api/v1/patients/{prescription_patient}/prescriptions",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
