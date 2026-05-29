"""
Unit tests for app.modules.code_catalogs.seed.

Tests:
- Helper functions return non-empty lists of dicts with required keys
- seed_code_catalogs() executes via mocked session and emits INSERT
"""

from unittest.mock import AsyncMock

import pytest

from app.modules.code_catalogs import seed


# ---------------------------------------------------------------------------
# Helper extractors
# ---------------------------------------------------------------------------
def test_get_icd10_codes_returns_non_empty_list():
    """ICD-10 seed list is non-empty."""
    codes = seed._get_icd10_codes()
    assert isinstance(codes, list)
    assert len(codes) > 0


def test_get_icd10_codes_have_required_keys():
    """Each ICD-10 code dict has the required fields."""
    codes = seed._get_icd10_codes()
    for c in codes:
        assert "catalog_type" in c
        assert "code" in c
        assert "display_name_en" in c


def test_get_atc_codes_returns_non_empty_list():
    """ATC seed list is non-empty."""
    codes = seed._get_atc_codes()
    assert isinstance(codes, list)
    assert len(codes) > 0


def test_get_atc_codes_have_required_keys():
    codes = seed._get_atc_codes()
    for c in codes:
        assert "catalog_type" in c
        assert "code" in c
        assert "display_name_en" in c


def test_get_loinc_codes_returns_non_empty_list():
    """LOINC seed list is non-empty."""
    codes = seed._get_loinc_codes()
    assert isinstance(codes, list)
    assert len(codes) > 0


def test_get_loinc_codes_have_required_keys():
    codes = seed._get_loinc_codes()
    for c in codes:
        assert "catalog_type" in c
        assert "code" in c


def test_get_snomed_codes_returns_non_empty_list():
    """SNOMED seed list is non-empty."""
    codes = seed._get_snomed_codes()
    assert isinstance(codes, list)
    assert len(codes) > 0


def test_get_snomed_codes_have_required_keys():
    codes = seed._get_snomed_codes()
    for c in codes:
        assert "catalog_type" in c
        assert "code" in c


def test_no_duplicate_codes_within_catalog_type():
    """Each (catalog_type, code) tuple appears at most once across all seeds."""
    all_codes = (
        seed._get_icd10_codes()
        + seed._get_atc_codes()
        + seed._get_loinc_codes()
        + seed._get_snomed_codes()
    )
    seen = set()
    for c in all_codes:
        key = (c["catalog_type"], c["code"])
        assert key not in seen, f"Duplicate seed: {key}"
        seen.add(key)


# ---------------------------------------------------------------------------
# seed_code_catalogs orchestration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_seed_code_catalogs_executes_insert_and_flush():
    """seed_code_catalogs calls db.execute (INSERT) and db.flush."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.flush = AsyncMock()

    await seed.seed_code_catalogs(mock_db)

    mock_db.execute.assert_called_once()
    mock_db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_seed_code_catalogs_uses_on_conflict_do_nothing():
    """The INSERT statement uses ON CONFLICT for idempotency."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.flush = AsyncMock()

    await seed.seed_code_catalogs(mock_db)

    # Inspect the statement passed to execute
    args, _ = mock_db.execute.call_args
    stmt = args[0]
    # The compiled SQL should contain ON CONFLICT for idempotency
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "ON CONFLICT" in compiled.upper()
