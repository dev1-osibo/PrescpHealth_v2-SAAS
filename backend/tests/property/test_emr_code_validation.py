"""
Property Test: Code Catalog Validation.

Property 1 from design.md:
    "For any string submitted as an ICD-10/ATC/LOINC code, the system
    accepts it iff it exists in code_catalogs with is_active=True."

This proves that the code catalog validation system maintains correct invariants:
1. Any code that exists in the catalog and is_active=True passes validation
2. Any random string not in the catalog raises InvalidCodeError with reason="not_found"
3. Any code that exists but is_active=False raises InvalidCodeError with reason="inactive"

Why this matters (Patient Safety + Data Integrity):
    - Invalid codes would corrupt clinical records and break FHIR interoperability
    - Inactive codes represent deprecated/retired classifications that should not
      be used for new clinical entries
    - Validation ensures all diagnoses, prescriptions, and lab orders use
      standardized, current clinical terminology

**Validates: Requirements 1.3, 2.2, 3.2, 4.6**
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.exceptions import InvalidCodeError
from app.modules.code_catalogs.service import CodeCatalogService


# ---------------------------------------------------------------------------
# Known valid codes from seed data (representative subset per catalog type)
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


# ---------------------------------------------------------------------------
# Strategies: Generate catalog types and code strings
# ---------------------------------------------------------------------------
catalog_type_strategy = st.sampled_from([
    CatalogType.ICD10, CatalogType.ATC, CatalogType.LOINC,
])

# Strategy for generating random invalid code strings
# These should NOT match any real clinical code format
invalid_code_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=20,
).filter(
    # Filter out strings that happen to match known valid codes
    lambda s: s not in VALID_ICD10_CODES
    and s not in VALID_ATC_CODES
    and s not in VALID_LOINC_CODES
)


# ---------------------------------------------------------------------------
# Helper: Create a mock DB session that simulates code catalog lookups
# ---------------------------------------------------------------------------
def _make_mock_db(code_exists: bool, is_active: bool = True):
    """
    Create a mock AsyncSession that simulates code catalog queries.

    The mock returns:
    - None (scalar_one_or_none) if code_exists=False -> code not found
    - is_active value if code_exists=True -> code found, check active status

    Args:
        code_exists: Whether the code exists in the catalog.
        is_active: Whether the code is active (only relevant if exists).

    Returns:
        AsyncMock configured to simulate the DB query behavior.
    """
    mock_db = AsyncMock()
    mock_result = MagicMock()

    if not code_exists:
        # Code not found in catalog
        mock_result.scalar_one_or_none.return_value = None
    else:
        # Code found — return is_active flag
        mock_result.scalar_one_or_none.return_value = is_active

    mock_db.execute.return_value = mock_result
    return mock_db


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------
class TestCodeCatalogValidation:
    """
    Property-based tests proving code catalog validation invariants.

    The core invariants tested:
    1. Valid active codes always pass validation (return True)
    2. Non-existent codes always raise InvalidCodeError with reason="not_found"
    3. Inactive codes always raise InvalidCodeError with reason="inactive"
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_property_valid_active_code_passes_validation(self, data):
        """
        Property: For any code that exists in the catalog with is_active=True,
        validate_code returns True.

        This ensures the validation gate never rejects legitimate clinical
        codes that are currently active in the classification system.

        **Validates: Requirements 1.3, 2.2, 3.2, 4.6**
        """
        # Draw a random catalog type
        catalog_type = data.draw(catalog_type_strategy)
        # Draw a valid code for that catalog type
        valid_codes = ALL_VALID_CODES[catalog_type]
        code = data.draw(st.sampled_from(valid_codes))

        # Mock DB to return is_active=True (code exists and is active)
        mock_db = _make_mock_db(code_exists=True, is_active=True)

        service = CodeCatalogService()
        result = await service.validate_code(mock_db, catalog_type, code)

        # INVARIANT: Valid active codes must pass validation
        assert result is True, (
            f"validate_code returned {result} for {catalog_type.value} code "
            f"'{code}' which exists and is active. Expected True."
        )

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_property_invalid_code_raises_not_found(self, data):
        """
        Property: For any string that does not exist in the code catalog,
        validate_code raises InvalidCodeError with reason="not_found".

        Random strings that don't match any known clinical code must be
        rejected to prevent garbage data from entering clinical records.

        **Validates: Requirements 1.3, 2.2, 3.2, 4.6**
        """
        catalog_type = data.draw(catalog_type_strategy)
        invalid_code = data.draw(invalid_code_strategy)

        # Mock DB to return None (code not found)
        mock_db = _make_mock_db(code_exists=False)

        service = CodeCatalogService()

        # INVARIANT: Non-existent codes must raise InvalidCodeError
        with pytest.raises(InvalidCodeError) as exc_info:
            await service.validate_code(mock_db, catalog_type, invalid_code)

        # Verify the error reason is "not_found"
        assert exc_info.value.details["reason"] == "not_found", (
            f"Expected reason='not_found' for non-existent code '{invalid_code}', "
            f"got reason='{exc_info.value.details['reason']}'"
        )

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_property_inactive_code_raises_inactive(self, data):
        """
        Property: For any code that exists in the catalog but has
        is_active=False, validate_code raises InvalidCodeError with
        reason="inactive".

        Inactive codes represent deprecated or retired classifications
        that should not be used for new clinical entries. They remain
        in the catalog for historical reference but cannot be assigned
        to new encounters, prescriptions, or lab orders.

        **Validates: Requirements 1.3, 2.2, 3.2, 4.6**
        """
        catalog_type = data.draw(catalog_type_strategy)
        # Use a valid code format but simulate it being inactive
        valid_codes = ALL_VALID_CODES[catalog_type]
        code = data.draw(st.sampled_from(valid_codes))

        # Mock DB to return is_active=False (code exists but inactive)
        mock_db = _make_mock_db(code_exists=True, is_active=False)

        service = CodeCatalogService()

        # INVARIANT: Inactive codes must raise InvalidCodeError
        with pytest.raises(InvalidCodeError) as exc_info:
            await service.validate_code(mock_db, catalog_type, code)

        # Verify the error reason is "inactive"
        assert exc_info.value.details["reason"] == "inactive", (
            f"Expected reason='inactive' for inactive code '{code}', "
            f"got reason='{exc_info.value.details['reason']}'"
        )
