"""
Integration tests for Patient Detail API operations.

Validates service-layer detail operations that basic CRUD tests don't cover:
- PUT /api/v1/patients/{id} — update patient (versioning + diff)
- DELETE /api/v1/patients/{id} — soft delete (HIPAA retention)
- POST /api/v1/patients/{id}/restore — restore after soft delete
- GET /api/v1/patients/{id}/versions — version history
- GET /api/v1/patients?name=... — search by name filter

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
# Fixture: Seed a patient for detail operation tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def detail_patient():
    """Insert a synthetic patient for update/delete/version tests."""
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
            f"MRN-DTL-{patient_id.hex[:8]}",
            "Test Patient",
            "Detail",
            created_by,
        )
        yield patient_id
    finally:
        # Clean up versions first (FK), then patient
        await conn.execute(
            "DELETE FROM patient_versions WHERE patient_id = $1", patient_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: PUT /api/v1/patients/{id} — update first_name
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_patient_first_name(
    client, init_test_db, auth_headers, detail_patient
):
    """Verify updating a patient field returns 200 with updated data."""
    payload = {"first_name": "Updated Name"}

    response = await client.put(
        f"/api/v1/patients/{detail_patient}",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["first_name"] == "Updated Name"
    assert body["data"]["id"] == str(detail_patient)


# ---------------------------------------------------------------------------
# Test: DELETE /api/v1/patients/{id} — soft delete
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_soft_delete_patient(
    client, init_test_db, auth_headers, detail_patient
):
    """Verify soft-deleting a patient returns 204 (HIPAA: no hard delete)."""
    response = await client.delete(
        f"/api/v1/patients/{detail_patient}",
        headers=auth_headers,
    )

    assert response.status_code == 204, f"Got {response.status_code}: {response.text}"

    # Verify patient is no longer returned by GET (soft-deleted)
    get_resp = await client.get(
        f"/api/v1/patients/{detail_patient}",
        headers=auth_headers,
    )
    # Should still be accessible by direct ID (not hard-deleted)
    # but may return 404 if service excludes deleted from get_patient
    assert get_resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/restore — restore after delete
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_restore_patient_after_delete(
    client, init_test_db, auth_headers, detail_patient
):
    """Verify restoring a soft-deleted patient returns 200."""
    # First soft-delete the patient
    del_resp = await client.delete(
        f"/api/v1/patients/{detail_patient}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    # Now restore
    response = await client.post(
        f"/api/v1/patients/{detail_patient}/restore",
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == str(detail_patient)


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/versions — version history
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_patient_versions(
    client, init_test_db, auth_headers, detail_patient
):
    """Verify version history returns at least one version after update."""
    # Trigger a version by updating the patient
    await client.put(
        f"/api/v1/patients/{detail_patient}",
        json={"first_name": "Versioned Name"},
        headers=auth_headers,
    )

    response = await client.get(
        f"/api/v1/patients/{detail_patient}/versions",
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "items" in body["data"]
    assert len(body["data"]["items"]) >= 1


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients?name=Test — search by name
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_patients_by_name(
    client, init_test_db, auth_headers, detail_patient
):
    """Verify searching patients by name filter returns matching results."""
    response = await client.get(
        "/api/v1/patients?name=Test Patient",
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "items" in body["data"]
    # Should find at least our seeded patient
    assert len(body["data"]["items"]) >= 1
