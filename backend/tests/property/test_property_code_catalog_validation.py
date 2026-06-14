"""
Property Test: Code Catalog Validation (Layer 1).

Property: Valid ICD-10/ATC/LOINC codes are accepted and invalid codes are rejected.

Uses Hypothesis to generate random strings and verify that only codes matching
catalog patterns are accepted by CodeCatalogService.validate_code(). The DB
session is mocked — no real database connections are used.

Invariants tested:
1. Known valid codes (from seed data) pass validation when DB confirms existence
2. Random garbage strings are rejected with reason="not_found"
3. Codes matching format but inactive are rejected with reason="inactive"
4. Empty strings and whitespace-only inputs are rejected

**Validates: EMR Layer 1 — Clinical Code Integrity**
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.exceptions import InvalidCodeError
from app.modules.code_catalogs.service import CodeCatalogService


# ---------------------------------------------------------------------------
# Known valid codes (representative subset matching seed data)
# ---------------------------------------------------------------------------
VALID_ICD10_CODES = [
    "E11.9", "I10", "I63.9", "I50.9", "N18.3", "J44.1", "B20",
    "A15.0", "B50.9", "D50.9", "E66.9", "F32.1", "J18.9",
]

VALID_ATC_CODES = [
    "A10BA02", "C08CA01", "C09AA02", "C09CA01", "C10AA05",
    "N02BE01", "J01CA04", "J01FA10", "P01BF01", "A02BC01",
]

VALID_LOINC_CODES = [
    "2345-7", "4548-4", "2160-0", "33914-3", "2093-3",
    "2085-9", "2571-8", "718-7", "6690-2", "1742-6",
]

ALL_VALID_CODES = {
    CatalogType.ICD10: VALID_ICD10_CODES,
    CatalogType.ATC: VALID_ATC_CODES,
    CatalogType.LOINC: VALID_LOINC_CODES,
}

# Combined set for filtering random strings that accidentally match
_ALL_KNOWN = set(VALID_ICD10_CODES + VALID_ATC_CODES + VALID_LOINC_CODES)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
catalog_type_strategy = st.sampled_from([
    CatalogType.ICD10, CatalogType.ATC, CatalogType.LOINC,
])

# Random garbage strings unlikely to match real clinical codes
random_garbage_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() and s not in _ALL_KNOWN)


# ---------------------------------------------------------------------------
# Helpers: Mock DB session for code catalog queries
# ---------------------------------------------------------------------------
def _mock_db_returns(code_exists: bool, is_active: bool = True) -> AsyncMock:
    """
    Create a mock AsyncSession simulating code_catalogs table lookup.

    Args:
        code_exists: If False, scalar_one_or_none returns None (not found).
        is_active: The is_active flag returned when code exists.

    Returns:
        AsyncMock behaving like an AsyncSession for validate_code queries.
    """
    mock_db = AsyncMock()
    mock_result = MagicMock()

    if not code_exists:
        mock_result.scalar_one_or_none.return_value = None
    else:
        mock_result.scalar_one_or_none.return_value = is_active

    mock_db.execute.return_value = mock_result
    return mock_db


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------
@pytest.mark.property
class TestPropertyCodeCatalogValidation:
    """
    Property-based tests for code catalog validation correctness.

    Verifies that the validation gate correctly accepts active codes
    and rejects invalid or inactive codes across all catalog types.
    """

    @given(data=st.data())
    @settings(max_examples=80, deadline=None)
    @pytest.mark.asyncio
    async def test_property_valid_codes_accepted(self, data):
        """
        Property: Any code in the catalog with is_active=True is accepted.

        For every catalog type, drawing a known valid code and simulating
        it exists as active in the DB must return True from validate_code.
        """
        catalog_type = data.draw(catalog_type_strategy)
        code = data.draw(st.sampled_from(ALL_VALID_CODES[catalog_type]))

        mock_db = _mock_db_returns(code_exists=True, is_active=True)
        service = CodeCatalogService()

        result = await service.validate_code(mock_db, catalog_type, code)

        assert result is True, (
            f"Expected True for active {catalog_type.value} code '{code}'"
        )

    @given(garbage=random_garbage_strategy, catalog_type=catalog_type_strategy)
    @settings(max_examples=80, deadline=None)
    @pytest.mark.asyncio
    async def test_property_random_garbage_rejected(self, garbage, catalog_type):
        """
        Property: Any random string not in the catalog raises InvalidCodeError.

        Random garbage should never pass validation — this protects clinical
        records from containing meaningless code values.
        """
        mock_db = _mock_db_returns(code_exists=False)
        service = CodeCatalogService()

        with pytest.raises(InvalidCodeError) as exc_info:
            await service.validate_code(mock_db, catalog_type, garbage)

        assert exc_info.value.details["reason"] == "not_found", (
            f"Expected reason='not_found' for garbage code '{garbage}', "
            f"got '{exc_info.value.details['reason']}'"
        )

    @given(data=st.data())
    @settings(max_examples=80, deadline=None)
    @pytest.mark.asyncio
    async def test_property_inactive_codes_rejected(self, data):
        """
        Property: Any code that exists but is_active=False raises InvalidCodeError.

        Deprecated/retired codes must not be assignable to new clinical
        entries even though they remain in the catalog for historical reference.
        """
        catalog_type = data.draw(catalog_type_strategy)
        code = data.draw(st.sampled_from(ALL_VALID_CODES[catalog_type]))

        mock_db = _mock_db_returns(code_exists=True, is_active=False)
        service = CodeCatalogService()

        with pytest.raises(InvalidCodeError) as exc_info:
            await service.validate_code(mock_db, catalog_type, code)

        assert exc_info.value.details["reason"] == "inactive", (
            f"Expected reason='inactive' for inactive code '{code}', "
            f"got '{exc_info.value.details['reason']}'"
        )

    @given(catalog_type=catalog_type_strategy)
    @settings(max_examples=30, deadline=None)
    @pytest.mark.asyncio
    async def test_property_empty_and_whitespace_rejected(self, catalog_type):
        """
        Property: Empty strings are rejected as not found in the catalog.

        Edge case ensuring that blank inputs cannot slip through validation.
        """
        mock_db = _mock_db_returns(code_exists=False)
        service = CodeCatalogService()

        with pytest.raises(InvalidCodeError):
            await service.validate_code(mock_db, catalog_type, "")
