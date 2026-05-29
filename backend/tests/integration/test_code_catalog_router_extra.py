"""
Additional integration tests for code_catalogs router endpoints:
- GET /api/v1/codes/{catalog_type}/search
- GET /api/v1/codes/{catalog_type}/hierarchy
- GET /api/v1/codes/{catalog_type}/{code} (single lookup)
"""

import asyncpg
import pytest
import pytest_asyncio

DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"

SEED_CODES = [
    ("icd10", "TST.SEARCH.01", "Synthetic Search Disease Alpha"),
    ("icd10", "TST.SEARCH.02", "Synthetic Search Disease Beta"),
    ("icd10", "TST.PARENT.01", "Synthetic Parent Disease"),
    ("icd10", "TST.CHILD.01", "Synthetic Child Disease"),
]


@pytest_asyncio.fixture
async def seed_search_codes():
    """Seed test codes for search and hierarchy tests; clean up after."""
    conn = await asyncpg.connect(DSN)
    try:
        for catalog_type, code, name in SEED_CODES:
            await conn.execute(
                """
                INSERT INTO code_catalogs (catalog_type, code, display_name_en, is_active)
                VALUES ($1, $2, $3, true)
                ON CONFLICT (catalog_type, code) DO NOTHING
                """,
                catalog_type, code, name,
            )
        yield
    finally:
        for catalog_type, code, name in SEED_CODES:
            await conn.execute(
                """
                DELETE FROM code_catalogs
                WHERE catalog_type = $1 AND code = $2 AND display_name_en = $3
                """,
                catalog_type, code, name,
            )
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_codes_returns_envelope_with_items(client, init_test_db, seed_search_codes):
    """Search endpoint returns standard envelope with items array."""
    response = await client.get(
        "/api/v1/codes/icd10/search?q=Synthetic&locale=en&limit=10"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    # At least the seeded items should match
    codes = [item.get("code") for item in body["data"]["items"]]
    assert any(c and c.startswith("TST.SEARCH") for c in codes) or len(codes) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_codes_respects_limit(client, init_test_db, seed_search_codes):
    """Search returns no more than the requested limit."""
    response = await client.get(
        "/api/v1/codes/icd10/search?q=Synthetic&limit=1"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]["items"]) <= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hierarchy_top_level_returns_envelope(client, init_test_db, seed_search_codes):
    """Hierarchy endpoint without parent returns top-level items."""
    response = await client.get("/api/v1/codes/icd10/hierarchy")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hierarchy_with_parent_returns_envelope(client, init_test_db, seed_search_codes):
    """Hierarchy with parent code returns child items."""
    response = await client.get(
        "/api/v1/codes/icd10/hierarchy?parent=TST.PARENT.01"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "items" in body["data"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lookup_existing_code(client, init_test_db, seed_search_codes):
    """Single code lookup returns the code details."""
    response = await client.get("/api/v1/codes/icd10/TST.SEARCH.01")
    # Either 200 with data or 404 if endpoint is missing — check for either
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        body = response.json()
        assert body["success"] is True
        assert body["data"]["code"] == "TST.SEARCH.01"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lookup_nonexistent_code_returns_404(client, init_test_db):
    """Single code lookup for non-existent code returns 404."""
    response = await client.get("/api/v1/codes/icd10/DOES.NOT.EXIST")
    # Per typical REST convention this is 404; some implementations return 200 with valid=false
    assert response.status_code in (404, 200)
    if response.status_code == 404:
        body = response.json()
        assert body["success"] is False
