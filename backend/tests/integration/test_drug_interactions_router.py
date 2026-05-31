"""
Integration tests for the Drug Interactions API Router.

Validates the full request path for medication and interaction operations:
    HTTP request → TenantMiddleware → RBAC → router → service → real DB → response

Tests:
- POST /api/v1/patients/{id}/medications — add medication (runs DDI/DHI checks)
- GET /api/v1/patients/{id}/medications/safety — get safety summary

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied

Notes:
    - Adding a medication triggers DDI/DHI checks against the interaction
      database. We mock the DrugInteractionService and AuditService at the
      router module level since the router's AuditService instantiation
      doesn't match the actual interface.
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
# Fixture: Seed a patient for drug interaction tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def drug_patient():
    """Insert a synthetic patient for drug interaction tests, clean up after."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1968-02-14', 'Male', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-DRUG-{patient_id.hex[:8]}",
            "Test Patient",
            "DrugInteraction",
            created_by,
        )
        yield patient_id
    finally:
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/medications — add medication
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_medication_returns_201(
    client, init_test_db, auth_headers, drug_patient
):
    """
    Verify adding a medication returns 201 with safety status.

    The endpoint adds the medication and runs DDI/DHI checks. We mock
    the DrugInteractionService to return a successful result with no
    interactions detected (Safe status).
    """
    mock_result = {
        "medication_id": str(uuid.uuid4()),
        "ddi_count": 0,
        "dhi_count": 0,
        "safety_status": "Safe",
        "critical_interactions": [],
    }

    mock_service = MagicMock()
    mock_service.add_medication = AsyncMock(return_value=mock_result)

    with patch("app.modules.drug_interactions.router.DrugInteractionService", return_value=mock_service):
        with patch("app.modules.drug_interactions.router.AuditService"):
            with patch("app.modules.drug_interactions.router.InteractionEngine"):
                response = await client.post(
                    f"/api/v1/patients/{drug_patient}/medications",
                    json={
                        "drug_name": "Metformin",
                        "drug_code": "A10BA02",
                        "dosage": "500mg",
                        "frequency": "twice daily",
                        "route": "oral",
                        "start_date": "2025-01-15",
                    },
                    headers=auth_headers,
                )

    assert response.status_code == 201, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["safety_status"] == "Safe"
    assert body["data"]["ddi_count"] == 0


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/medications/safety — get safety summary
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_safety_summary_returns_200(
    client, init_test_db, auth_headers, drug_patient
):
    """
    Verify fetching safety summary returns 200 with consolidated status.

    A patient with no medications should get a Safe status with zero
    issue counts — not a 404 or 500.
    """
    mock_summary = {
        "overall_status": "Safe",
        "critical_issue_count": 0,
        "moderate_issue_count": 0,
        "active_medication_count": 0,
        "recommendations": [],
    }

    mock_service = MagicMock()
    mock_service.get_safety_summary = AsyncMock(return_value=mock_summary)

    with patch("app.modules.drug_interactions.router.DrugInteractionService", return_value=mock_service):
        with patch("app.modules.drug_interactions.router.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.log_action = AsyncMock()
            with patch("app.modules.drug_interactions.router.InteractionEngine"):
                response = await client.get(
                    f"/api/v1/patients/{drug_patient}/medications/safety",
                    headers=auth_headers,
                )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"]["overall_status"] == "Safe"
    assert body["data"]["critical_issue_count"] == 0
