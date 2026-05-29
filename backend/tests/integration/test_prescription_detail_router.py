"""
Integration tests for Prescription Detail API operations.

Validates service-layer detail operations for prescriptions:
- PUT /api/v1/prescriptions/{id}/status — discontinue prescription
- POST /api/v1/prescriptions/{id}/refill — process refill
- GET /api/v1/prescriptions/{id} — get with dispensing history

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
    - ATC code seeded in code_catalogs for validation
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
# Fixture: Seed patient + active prescription with refills
# ---------------------------------------------------------------------------
@pytest.fixture
async def prescription_detail_data():
    """Insert patient and active prescription for status/refill tests."""
    patient_id = uuid.uuid4()
    prescription_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        # Seed patient
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1970-03-15', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-RXD-{patient_id.hex[:8]}",
            "Test Patient",
            "RxDetail",
            created_by,
        )
        # Ensure ATC code exists
        await conn.execute(
            """
            INSERT INTO code_catalogs (catalog_type, code, display_name_en, is_active)
            VALUES ('atc', 'C09AA01', 'Captopril', true)
            ON CONFLICT (catalog_type, code) DO NOTHING
            """,
        )
        # Seed active prescription with refills_allowed > 0
        await conn.execute(
            """
            INSERT INTO prescriptions (id, tenant_id, patient_id, drug_name,
                atc_code, dosage, frequency, route, status,
                refills_allowed, refills_remaining, prescribed_by, duration_days)
            VALUES ($1, $2, $3, 'Captopril', 'C09AA01', '25mg', 'twice daily',
                'oral', 'active', 3, 3, $4, 90)
            ON CONFLICT DO NOTHING
            """,
            prescription_id,
            uuid.UUID(TEST_TENANT),
            patient_id,
            created_by,
        )
        yield {
            "patient_id": patient_id,
            "prescription_id": prescription_id,
        }
    finally:
        await conn.execute(
            "DELETE FROM dispensings WHERE prescription_id = $1", prescription_id
        )
        await conn.execute(
            "DELETE FROM prescriptions WHERE id = $1", prescription_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: PUT /api/v1/prescriptions/{id}/status — discontinue
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_discontinue_prescription(
    client, init_test_db, auth_headers, prescription_detail_data
):
    """Verify discontinuing a prescription returns 200 with action confirmed."""
    rx_id = prescription_detail_data["prescription_id"]
    payload = {
        "action": "discontinue",
        "reason": "Patient developed adverse reaction during integration test",
    }

    response = await client.put(
        f"/api/v1/prescriptions/{rx_id}/status",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["action"] == "discontinue"


# ---------------------------------------------------------------------------
# Test: POST /api/v1/prescriptions/{id}/refill — process refill
# Note: This test is skipped due to a pre-existing model/migration mismatch
# where the Dispensing model references 'updated_at' but the dispensings
# table only has 'created_at'. The refill service code path works but
# the ORM INSERT fails on the missing column.
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_refill(
    client, init_test_db, auth_headers, prescription_detail_data
):
    """Verify processing a refill returns 201 when refills remain."""
    rx_id = prescription_detail_data["prescription_id"]
    payload = {
        "dispensed_quantity": "30 tablets",
    }

    response = await client.post(
        f"/api/v1/prescriptions/{rx_id}/refill",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "id" in body["data"]


# ---------------------------------------------------------------------------
# Test: GET /api/v1/prescriptions/{id} — get with dispensing history
# Note: Also affected by the dispensings.updated_at model mismatch when
# the ORM tries to SELECT updated_at from dispensings.
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_prescription_with_dispensings(
    client, init_test_db, auth_headers, prescription_detail_data
):
    """Verify getting a prescription includes dispensing history array."""
    rx_id = prescription_detail_data["prescription_id"]

    response = await client.get(
        f"/api/v1/prescriptions/{rx_id}",
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == str(rx_id)
    assert body["data"]["drug_name"] == "Captopril"
    # dispensings key should exist (may be empty list)
    assert "dispensings" in body["data"]
    assert isinstance(body["data"]["dispensings"], list)
