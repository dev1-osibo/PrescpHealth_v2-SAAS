"""
Integration tests for Encounter Detail API operations.

Validates service-layer detail operations for encounters:
- POST /api/v1/encounters/{id}/soap-notes — add SOAP note
- POST /api/v1/encounters/{id}/diagnoses — record diagnosis
- POST /api/v1/encounters/{id}/discharge — complete encounter

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
    - ICD-10 code seeded in code_catalogs for diagnosis validation
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
# Fixture: Seed patient + encounter + ICD-10 code for detail tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def encounter_detail_data():
    """Insert patient, encounter, and ICD-10 code for detail operations."""
    patient_id = uuid.uuid4()
    encounter_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        # Seed patient
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1985-07-20', 'Female', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-ENCD-{patient_id.hex[:8]}",
            "Test Patient",
            "EncDetail",
            created_by,
        )
        # Seed encounter in 'in_progress' status
        await conn.execute(
            """
            INSERT INTO encounters (id, tenant_id, patient_id, clinician_id,
                reason_for_visit, encounter_class, status, check_in_time)
            VALUES ($1, $2, $3, $4, $5, 'ambulatory', 'in_progress', NOW())
            ON CONFLICT DO NOTHING
            """,
            encounter_id,
            uuid.UUID(TEST_TENANT),
            patient_id,
            created_by,
            "Integration test encounter for SOAP/diagnosis/discharge",
        )
        # Seed ICD-10 code for diagnosis validation
        await conn.execute(
            """
            INSERT INTO code_catalogs (catalog_type, code, display_name_en, is_active)
            VALUES ('icd10', 'E11.9', 'Type 2 diabetes mellitus without complications', true)
            ON CONFLICT (catalog_type, code) DO NOTHING
            """,
        )
        yield {"patient_id": patient_id, "encounter_id": encounter_id}
    finally:
        # Clean up in FK order
        await conn.execute(
            "DELETE FROM diagnoses WHERE encounter_id = $1", encounter_id
        )
        await conn.execute(
            "DELETE FROM soap_notes WHERE encounter_id = $1", encounter_id
        )
        await conn.execute(
            "DELETE FROM encounters WHERE id = $1", encounter_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/encounters/{id}/soap-notes — add SOAP note
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_soap_note_returns_201(
    client, init_test_db, auth_headers, encounter_detail_data
):
    """Verify adding a SOAP note to an encounter returns 201."""
    encounter_id = encounter_detail_data["encounter_id"]
    payload = {
        "subjective": "Patient reports mild headache for 2 days",
        "objective": "BP 120/80, temp 37.0C, alert and oriented",
        "assessment": "Tension headache, likely stress-related",
        "plan": "Recommend rest, hydration, follow up in 1 week",
    }

    response = await client.post(
        f"/api/v1/encounters/{encounter_id}/soap-notes",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "id" in body["data"]


# ---------------------------------------------------------------------------
# Test: POST /api/v1/encounters/{id}/diagnoses — record diagnosis
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_record_diagnosis_returns_201(
    client, init_test_db, auth_headers, encounter_detail_data
):
    """Verify recording a coded diagnosis returns 201."""
    encounter_id = encounter_detail_data["encounter_id"]
    payload = {
        "icd10_code": "E11.9",
        "is_chronic": True,
        "is_primary": True,
    }

    response = await client.post(
        f"/api/v1/encounters/{encounter_id}/diagnoses",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "id" in body["data"]


# ---------------------------------------------------------------------------
# Test: POST /api/v1/encounters/{id}/discharge — complete encounter
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_discharge_encounter_returns_200(
    client, init_test_db, auth_headers, encounter_detail_data
):
    """Verify discharging an encounter returns 200 with completed status."""
    encounter_id = encounter_detail_data["encounter_id"]
    payload = {
        "follow_up_instructions": "Return in 2 weeks for follow-up",
    }

    response = await client.post(
        f"/api/v1/encounters/{encounter_id}/discharge",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "completed"
