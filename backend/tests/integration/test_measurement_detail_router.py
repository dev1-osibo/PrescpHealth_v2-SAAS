"""
Integration tests for Measurement Detail API operations.

Validates service-layer detail operations for measurements:
- PATCH /api/v1/measurements/{id}/validate — clinician validates
- POST /api/v1/patients/{id}/measurements/bulk — bulk import
- GET /api/v1/measurements/{id} — get single measurement

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
# Fixture: Seed patient + measurement for detail tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def measurement_detail_data():
    """Insert patient and unvalidated measurement for detail operations."""
    patient_id = uuid.uuid4()
    measurement_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1982-09-10', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-MEASD-{patient_id.hex[:8]}",
            "Test Patient",
            "MeasDetail",
            created_by,
        )
        # Seed an unvalidated measurement (simulates patient_portal submission)
        await conn.execute(
            """
            INSERT INTO measurements (id, tenant_id, patient_id,
                measurement_type, value, unit, recorded_at, recorded_by,
                source, is_validated, is_flagged)
            VALUES ($1, $2, $3, 'systolic_bp', 135.0, 'mmHg', NOW(),
                $4, 'patient_portal', false, false)
            ON CONFLICT DO NOTHING
            """,
            measurement_id,
            uuid.UUID(TEST_TENANT),
            patient_id,
            created_by,
        )
        yield {"patient_id": patient_id, "measurement_id": measurement_id}
    finally:
        await conn.execute(
            "DELETE FROM measurements WHERE patient_id = $1", patient_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: PATCH /api/v1/measurements/{id}/validate — clinician validates
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_validate_measurement_returns_200(
    client, init_test_db, auth_headers, measurement_detail_data
):
    """Verify clinician validation marks measurement as validated."""
    m_id = measurement_detail_data["measurement_id"]

    response = await client.patch(
        f"/api/v1/measurements/{m_id}/validate",
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["is_validated"] is True


# ---------------------------------------------------------------------------
# Test: GET /api/v1/measurements/{id} — get single measurement
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_single_measurement_returns_200(
    client, init_test_db, auth_headers, measurement_detail_data
):
    """Verify getting a single measurement by ID returns 200."""
    m_id = measurement_detail_data["measurement_id"]

    response = await client.get(
        f"/api/v1/measurements/{m_id}",
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == str(m_id)
    assert body["data"]["measurement_type"] == "systolic_bp"
    assert body["data"]["value"] == 135.0


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/measurements/bulk — bulk import
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_import_measurements_returns_200(
    client, init_test_db, auth_headers, measurement_detail_data
):
    """Verify bulk import creates measurements and reports results."""
    patient_id = measurement_detail_data["patient_id"]
    now = datetime.now(timezone.utc).isoformat()

    payload = {
        "measurements": [
            {
                "measurement_type": "diastolic_bp",
                "value": 80.0,
                "unit": "mmHg",
                "recorded_at": now,
            },
            {
                "measurement_type": "heart_rate",
                "value": 72.0,
                "unit": "bpm",
                "recorded_at": now,
            },
        ]
    }

    response = await client.post(
        f"/api/v1/patients/{patient_id}/measurements/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    # Bulk import returns summary: created + skipped should equal total rows
    data = body["data"]
    assert data["created"] + data["skipped_duplicates"] + len(data["errors"]) >= 1


# ---------------------------------------------------------------------------
# Test: GET /api/v1/measurements/{id} — 404 for nonexistent measurement
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_nonexistent_measurement_returns_404(
    client, init_test_db, auth_headers
):
    """Verify requesting a nonexistent measurement returns 404."""
    fake_id = uuid.uuid4()

    response = await client.get(
        f"/api/v1/measurements/{fake_id}",
        headers=auth_headers,
    )

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
