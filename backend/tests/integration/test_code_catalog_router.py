"""
Integration test for the Code Catalog Router via FastAPI TestClient.

Proves the full request path works end-to-end:
    HTTP request → FastAPI app → middleware → router → service → real DB → response

This test validates the integration harness itself:
- App starts correctly with test settings
- Database engine initializes and connects to prescphealth_test
- The code_catalogs router handles requests
- Responses follow the standard envelope format

Prerequisites:
    - PostgreSQL running at localhost:5432
    - prescphealth_test database exists with migrations applied
    - pg_trgm extension enabled (for search endpoint)

Run with:
    python -m pytest backend/tests/integration/test_code_catalog_router.py -v --tb=short
"""

import asyncpg
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Connection string for direct DB seeding (matches conftest TEST_DATABASE_URL)
# ---------------------------------------------------------------------------
DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"

# Test code we'll seed and validate against
TEST_ICD10_CODE = "E11.9"
TEST_ICD10_DISPLAY = "Type 2 diabetes mellitus without complications"


# ---------------------------------------------------------------------------
# Fixture: Seed a known ICD-10 code into the test database
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def seed_icd10_code():
    """
    Ensure E11.9 exists in code_catalogs for the validate endpoint test.

    Uses INSERT ... ON CONFLICT DO NOTHING for idempotency — safe to run
    multiple times without creating duplicates. Cleans up after the test
    to avoid polluting other tests.
    """
    conn = await asyncpg.connect(DSN)
    try:
        # Idempotent insert — won't fail if code already exists from migrations/seeds
        await conn.execute(
            """
            INSERT INTO code_catalogs (catalog_type, code, display_name_en, is_active)
            VALUES ('icd10', $1, $2, true)
            ON CONFLICT (catalog_type, code) DO NOTHING
            """,
            TEST_ICD10_CODE,
            TEST_ICD10_DISPLAY,
        )
        yield
    finally:
        # Cleanup: remove the test code if WE inserted it (not if it was pre-existing)
        # Using a safe approach: only delete if display_name matches our exact test string
        await conn.execute(
            """
            DELETE FROM code_catalogs
            WHERE catalog_type = 'icd10'
              AND code = $1
              AND display_name_en = $2
            """,
            TEST_ICD10_CODE,
            TEST_ICD10_DISPLAY,
        )
        await conn.close()


# ---------------------------------------------------------------------------
# Test: Validate a known ICD-10 code returns valid=true
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_validate_known_icd10_code_returns_valid(
    client, init_test_db, seed_icd10_code
):
    """
    Prove the full integration path works: app → router → DB → response.

    Calls GET /api/v1/codes/icd10/validate/E11.9 and verifies:
    1. HTTP 200 status code
    2. Response is JSON with standard envelope (success, data, meta)
    3. data.valid is True (code exists in the database)
    4. data.code matches what we requested
    5. data.catalog_type is "icd10"

    This single test proves:
    - FastAPI app starts with test settings
    - Database engine connects to prescphealth_test
    - The code_catalogs router is registered and handles the request
    - The service layer queries the real database successfully
    - The response envelope format is correct
    """
    response = await client.get("/api/v1/codes/icd10/validate/E11.9")

    # --- Status code check ---
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. Body: {response.text}"
    )

    # --- Parse JSON response ---
    body = response.json()

    # --- Standard envelope structure ---
    assert "success" in body, "Response missing 'success' field"
    assert body["success"] is True, f"Expected success=True, got {body['success']}"
    assert "data" in body, "Response missing 'data' field"
    assert "meta" in body, "Response missing 'meta' field"

    # --- Data payload correctness ---
    data = body["data"]
    assert data["valid"] is True, (
        f"Expected valid=True for E11.9, got {data['valid']}. "
        "Is the code_catalogs table seeded?"
    )
    assert data["code"] == "E11.9"
    assert data["catalog_type"] == "icd10"

    # --- Meta contains request_id for correlation ---
    assert "request_id" in body["meta"], "Meta missing request_id"


# ---------------------------------------------------------------------------
# Test: Validate a non-existent code returns valid=false
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_validate_nonexistent_code_returns_invalid(client, init_test_db):
    """
    Verify that a code not in the database returns valid=false (not an error).

    The validate endpoint is designed to return a boolean result rather than
    raising a 404, so the UI can show inline validation feedback without
    error handling.
    """
    # Z99.99 is not a real ICD-10 code and won't be in our test DB
    response = await client.get("/api/v1/codes/icd10/validate/Z99.99")

    assert response.status_code == 200
    body = response.json()

    assert body["success"] is True
    assert body["data"]["valid"] is False
    assert body["data"]["code"] == "Z99.99"
    assert body["data"]["catalog_type"] == "icd10"


# ---------------------------------------------------------------------------
# Test: Health check still works (proves app started correctly)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_check_returns_healthy(client):
    """
    Verify the app's built-in health check works through the test client.

    This is the simplest possible integration test — if this fails,
    the app didn't start at all and nothing else will work.
    """
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["environment"] == "testing"
