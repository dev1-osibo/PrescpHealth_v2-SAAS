"""
Integration tests for the Lab Order API Router.

Validates the full request path for lab order lifecycle:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/lab-orders — create lab order (Doctor token, needs patient)
- GET /api/v1/lab-orders — list lab orders (Doctor token)
- POST /api/v1/lab-orders/{id}/results — record result (Doctor token)

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
    - LOINC code in code_catalogs for validation
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
# Fixture: Seed patient + LOINC code for lab order tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def lab_patient():
    """Insert a synthetic patient and LOINC code for lab order creation."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1992-03-25', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-LAB-{patient_id.hex[:8]}",
            "Test Patient",
            "LabOrder",
            created_by,
        )
        # Ensure LOINC code exists for validation
        await conn.execute(
            """
            INSERT INTO code_catalogs (catalog_type, code, display_name_en, is_active)
            VALUES ('loinc', '2345-7', 'Glucose [Mass/volume] in Serum or Plasma', true)
            ON CONFLICT (catalog_type, code) DO NOTHING
            """,
        )
        yield patient_id
    finally:
        await conn.execute(
            "DELETE FROM lab_results WHERE lab_order_id IN "
            "(SELECT id FROM lab_orders WHERE patient_id = $1)",
            patient_id,
        )
        await conn.execute(
            "DELETE FROM lab_orders WHERE patient_id = $1", patient_id
        )
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/lab-orders — create lab order
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_lab_order_returns_201(
    client, init_test_db, auth_headers, lab_patient
):
    """Verify creating a lab order returns 201 with standard envelope."""
    payload = {
        "patient_id": str(lab_patient),
        "test_name": "Fasting Glucose",
        "loinc_code": "2345-7",
        "priority": "routine",
        "clinical_indication": "Diabetes screening for integration test",
    }

    response = await client.post(
        "/api/v1/lab-orders", json=payload, headers=auth_headers
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["test_name"] == "Fasting Glucose"
    assert body["data"]["patient_id"] == str(lab_patient)
    assert body["data"]["loinc_code"] == "2345-7"


# ---------------------------------------------------------------------------
# Test: GET /api/v1/lab-orders — list lab orders
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_lab_orders_returns_200(client, init_test_db, auth_headers):
    """Verify listing lab orders returns 200 with paginated envelope."""
    response = await client.get("/api/v1/lab-orders", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    assert "total" in body["data"]


# ---------------------------------------------------------------------------
# Test: POST /api/v1/lab-orders/{id}/results — record result
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_record_lab_result_returns_201(
    client, init_test_db, auth_headers, lab_patient
):
    """Verify recording a lab result returns 201 after creating an order."""
    # First create a lab order
    order_payload = {
        "patient_id": str(lab_patient),
        "test_name": "Fasting Glucose Result Test",
        "loinc_code": "2345-7",
        "priority": "routine",
    }
    order_resp = await client.post(
        "/api/v1/lab-orders", json=order_payload, headers=auth_headers
    )
    assert order_resp.status_code == 201
    order_id = order_resp.json()["data"]["id"]

    # Now record a result for that order
    result_payload = {
        "value": "95",
        "numeric_value": 95.0,
        "unit": "mg/dL",
        "reference_range_low": 70.0,
        "reference_range_high": 100.0,
        "resulted_at": datetime.now(timezone.utc).isoformat(),
    }

    response = await client.post(
        f"/api/v1/lab-orders/{order_id}/results",
        json=result_payload,
        headers=auth_headers,
    )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "id" in body["data"]
    # Normal value within reference range should not be abnormal
    assert body["data"]["is_abnormal"] is False
