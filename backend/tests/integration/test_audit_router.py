"""
Integration tests for the Audit Log API Router.

Validates the full request path for audit log queries:
    HTTP request → TenantMiddleware → RBAC → router → DB → response

Tests:
- GET /api/v1/audit — list audit logs (requires Clinic_Admin token)
- GET /api/v1/audit/{id} — get single entry (404 for non-existent)

Access Control:
    Audit endpoints require Clinic_Admin or Super_Admin role.
    Doctor/Nurse tokens should be rejected with 403.

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database with migrations applied
"""

import pytest

from tests.conftest import generate_test_jwt, TEST_TENANT_UUID


# ---------------------------------------------------------------------------
# Fixture: Clinic_Admin auth headers (audit requires admin role)
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_auth_headers():
    """Authorization headers with a Clinic_Admin token for audit access."""
    token = generate_test_jwt(role="Clinic_Admin", tenant_id=TEST_TENANT_UUID)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test: GET /api/v1/audit — list audit logs (admin)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_audit_logs_returns_200_for_admin(
    client, init_test_db, admin_auth_headers
):
    """Verify listing audit logs returns 200 for Clinic_Admin role."""
    response = await client.get("/api/v1/audit", headers=admin_auth_headers)

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    # Cursor-based pagination metadata
    assert "has_more" in body["data"]


# ---------------------------------------------------------------------------
# Test: GET /api/v1/audit — forbidden for Doctor role
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_audit_logs_returns_403_for_doctor(
    client, init_test_db, auth_headers
):
    """Verify Doctor role cannot access audit logs (requires Clinic_Admin)."""
    response = await client.get("/api/v1/audit", headers=auth_headers)

    # Doctor role is below Clinic_Admin in hierarchy — should be forbidden
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: GET /api/v1/audit/{id} — 404 for non-existent entry
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_audit_entry_returns_404_for_nonexistent(
    client, init_test_db, admin_auth_headers
):
    """Verify requesting a non-existent audit entry returns 404."""
    # Use a very large ID that won't exist
    response = await client.get(
        "/api/v1/audit/999999999", headers=admin_auth_headers
    )

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
