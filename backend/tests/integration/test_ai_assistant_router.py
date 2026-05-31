"""
Integration tests for the AI Assistant API Router.

Validates the full request path for AI clinical assistant operations:
    HTTP request → TenantMiddleware → RBAC → router → service → response

Tests:
- POST /api/v1/patients/{id}/assistant/chat — send clinical message
- GET /api/v1/patients/{id}/assistant/history — get conversation history

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied

Notes:
    - AI assistant requires LLM providers (OpenAI/Claude/Ollama) which are
      not available in tests. We mock the AIAssistantService and AuditService
      at the router module level.
    - The chat endpoint should return 200 with a response or 503 if all
      providers fail.
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
# Fixture: Seed a patient for AI assistant tests
# ---------------------------------------------------------------------------
@pytest.fixture
async def ai_patient():
    """Insert a synthetic patient for AI assistant tests, clean up after."""
    patient_id = uuid.uuid4()
    created_by = uuid.UUID("00000000-0000-0000-0000-000000000099")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """
            INSERT INTO patients (id, tenant_id, medical_record_number,
                first_name, last_name, date_of_birth, gender, status, created_by)
            VALUES ($1, $2, $3, $4, $5, '1992-11-05', 'Female', 'Active', $6)
            ON CONFLICT DO NOTHING
            """,
            patient_id,
            uuid.UUID(TEST_TENANT),
            f"MRN-AI-{patient_id.hex[:8]}",
            "Test Patient",
            "AIAssistant",
            created_by,
        )
        yield patient_id
    finally:
        await conn.execute("DELETE FROM patients WHERE id = $1", patient_id)
        await conn.close()


# ---------------------------------------------------------------------------
# Test: POST /api/v1/patients/{id}/assistant/chat — send message
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_chat_message_returns_200(
    client, init_test_db, auth_headers, ai_patient
):
    """
    Verify sending a clinical message returns 200 with AI response.

    Since LLM providers aren't available in tests, we mock the
    AIAssistantService at the router module level and verify the
    endpoint formats the response correctly.
    """
    mock_response = {
        "conversation_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "response": "Based on the clinical data, consider monitoring BP closely.",
        "tokens_used": 150,
        "model_used": "gpt-4o-mock",
    }

    mock_ai_service = MagicMock()
    mock_ai_service.send_message = AsyncMock(return_value=mock_response)

    # Mock AuditService with awaitable methods
    mock_audit_instance = MagicMock()
    mock_audit_instance.log_action = AsyncMock()

    with patch("app.modules.ai_assistant.router.AIAssistantService", return_value=mock_ai_service):
        with patch("app.modules.ai_assistant.router.AuditService", return_value=mock_audit_instance):
            response = await client.post(
                f"/api/v1/patients/{ai_patient}/assistant/chat",
                json={"message": "What are the risk factors for this patient?"},
                headers=auth_headers,
            )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert body["data"]["model_used"] == "gpt-4o-mock"


# ---------------------------------------------------------------------------
# Test: GET /api/v1/patients/{id}/assistant/history — get history
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_chat_history_returns_200(
    client, init_test_db, auth_headers, ai_patient
):
    """
    Verify fetching conversation history returns 200 with empty list.

    A patient with no prior conversations should get a valid response
    (empty list) — not a 404 or 500.
    """
    mock_ai_service = MagicMock()
    mock_ai_service.get_history = AsyncMock(return_value=[])

    # Mock AuditService with awaitable methods
    mock_audit_instance = MagicMock()
    mock_audit_instance.log_action = AsyncMock()

    with patch("app.modules.ai_assistant.router.AIAssistantService", return_value=mock_ai_service):
        with patch("app.modules.ai_assistant.router.AuditService", return_value=mock_audit_instance):
            response = await client.get(
                f"/api/v1/patients/{ai_patient}/assistant/history",
                headers=auth_headers,
            )

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []
