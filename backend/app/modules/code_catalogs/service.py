"""
PrescpHealth Backend — Code Catalog Service.

Provides validation, lookup, and search operations for clinical reference codes.
This service is the single entry point for all code catalog interactions:
- Validate codes before saving encounters, prescriptions, and lab orders
- Lookup display names in the clinician's preferred locale
- Fuzzy search for code selection UI (autocomplete)
- Hierarchical browsing for ICD-10 chapter navigation

Performance:
    - validate_code: Sub-5ms via unique constraint indexed lookup
    - lookup_code: Sub-5ms via same indexed lookup
    - search_codes: <100ms via GIN trigram index on display_name_en
    - get_code_hierarchy: <20ms via indexed parent_code lookup

HIPAA Note:
    This module handles ONLY public reference data (ICD-10, ATC, LOINC, SNOMED).
    It is NOT PHI. Code names and values are safe to log and include in errors.

Usage:
    from app.modules.code_catalogs.service import CodeCatalogService

    service = CodeCatalogService()
    is_valid = await service.validate_code(db, CatalogType.ICD10, "E11.9")
    result = await service.lookup_code(db, CatalogType.ATC, "N02BE01", locale="fr")
"""

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.exceptions import InvalidCodeError
from app.modules.code_catalogs.models import CodeCatalog

# ---------------------------------------------------------------------------
# Module logger — safe to log code catalog data (NOT PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Supported locales for display name resolution
_LOCALE_COLUMN_MAP = {
    "en": "display_name_en",
    "fr": "display_name_fr",
    "pt": "display_name_pt",
}


class CodeCatalogService:
    """
    Service layer for clinical code catalog operations.

    All methods accept an AsyncSession and operate on the shared
    (non-tenant-scoped) code_catalogs table. No RLS applies here
    because clinical codes are universal reference data.
    """

    async def validate_code(
        self,
        db: AsyncSession,
        catalog_type: CatalogType,
        code: str,
    ) -> bool:
        """
        Validate that a clinical code exists and is active.

        Uses the unique constraint index on (catalog_type, code) for
        sub-5ms lookup performance. Raises InvalidCodeError if the code
        doesn't exist or is inactive (deprecated/retired).

        Args:
            db: Async database session.
            catalog_type: Classification system (icd10, atc, loinc, snomed).
            code: The code string to validate (e.g., "E11.9", "N02BE01").

        Returns:
            True if the code exists and is_active=True.

        Raises:
            InvalidCodeError: If code doesn't exist or is inactive.
        """
        # Query uses the unique constraint index for O(1) lookup
        stmt = select(CodeCatalog.is_active).where(
            CodeCatalog.catalog_type == catalog_type.value,
            CodeCatalog.code == code,
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()

        # Code doesn't exist in the catalog
        if row is None:
            logger.warning(
                "code_validation_failed",
                catalog_type=catalog_type.value,
                code=code,
                reason="not_found",
            )
            raise InvalidCodeError(
                catalog_type=catalog_type.value,
                code=code,
                reason="not_found",
            )

        # Code exists but is inactive (deprecated/retired)
        if not row:
            logger.warning(
                "code_validation_failed",
                catalog_type=catalog_type.value,
                code=code,
                reason="inactive",
            )
            raise InvalidCodeError(
                catalog_type=catalog_type.value,
                code=code,
                reason="inactive",
            )

        return True

    async def lookup_code(
        self,
        db: AsyncSession,
        catalog_type: CatalogType,
        code: str,
        locale: str = "en",
    ) -> dict:
        """
        Look up a code's display name in the requested locale.

        Falls back to English if the requested locale translation is NULL.
        This supports the multilingual UI for francophone and lusophone
        African clinicians.

        Args:
            db: Async database session.
            catalog_type: Classification system (icd10, atc, loinc, snomed).
            code: The code string to look up.
            locale: Language code ("en", "fr", "pt"). Defaults to English.

        Returns:
            Dict with {code, display_name, catalog_type}.

        Raises:
            InvalidCodeError: If code doesn't exist in the catalog.
        """
        stmt = select(CodeCatalog).where(
            CodeCatalog.catalog_type == catalog_type.value,
            CodeCatalog.code == code,
        )
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()

        if entry is None:
            raise InvalidCodeError(
                catalog_type=catalog_type.value,
                code=code,
                reason="not_found",
            )

        # Resolve display name with locale fallback to English
        display_name = self._resolve_display_name(entry, locale)

        return {
            "code": entry.code,
            "display_name": display_name,
            "catalog_type": entry.catalog_type,
        }

    async def search_codes(
        self,
        db: AsyncSession,
        catalog_type: CatalogType,
        query: str,
        locale: str = "en",
        limit: int = 20,
    ) -> list[dict]:
        """
        Fuzzy search codes by display name using PostgreSQL trigram similarity.

        Uses the GIN trigram index on display_name_en for fast fuzzy matching.
        This powers the autocomplete UI where clinicians type partial code names
        (e.g., "diabet" matches "Diabetes mellitus type 2").

        Args:
            db: Async database session.
            catalog_type: Classification system to search within.
            query: Search string (partial name, e.g., "diabet", "metform").
            locale: Language for display names in results. Defaults to English.
            limit: Maximum results to return (default 20, prevents large payloads).

        Returns:
            List of dicts [{code, display_name, catalog_type}, ...] ordered by
            similarity score (best matches first).
        """
        # Use PostgreSQL similarity() function from pg_trgm extension
        # This requires the GIN trigram index on display_name_en
        similarity_expr = func.similarity(CodeCatalog.display_name_en, query)

        stmt = (
            select(CodeCatalog)
            .where(
                CodeCatalog.catalog_type == catalog_type.value,
                CodeCatalog.is_active.is_(True),
                # Trigram similarity threshold (default 0.3 in pg_trgm)
                similarity_expr > 0.1,
            )
            .order_by(similarity_expr.desc())
            .limit(limit)
        )

        result = await db.execute(stmt)
        entries = result.scalars().all()

        return [
            {
                "code": entry.code,
                "display_name": self._resolve_display_name(entry, locale),
                "catalog_type": entry.catalog_type,
            }
            for entry in entries
        ]

    async def get_code_hierarchy(
        self,
        db: AsyncSession,
        catalog_type: CatalogType,
        parent_code: str | None = None,
    ) -> list[dict]:
        """
        Get child codes for hierarchical browsing.

        Supports ICD-10 chapter → block → code navigation where clinicians
        can drill down from broad categories to specific codes.

        Args:
            db: Async database session.
            catalog_type: Classification system to browse.
            parent_code: Parent code to get children for. None = top-level codes.

        Returns:
            List of dicts [{code, display_name, catalog_type, parent_code}, ...]
            sorted alphabetically by code.
        """
        # Get direct children of the specified parent
        stmt = (
            select(CodeCatalog)
            .where(
                CodeCatalog.catalog_type == catalog_type.value,
                CodeCatalog.is_active.is_(True),
                CodeCatalog.parent_code == parent_code,
            )
            .order_by(CodeCatalog.code)
        )

        result = await db.execute(stmt)
        entries = result.scalars().all()

        return [
            {
                "code": entry.code,
                "display_name": entry.display_name_en,
                "catalog_type": entry.catalog_type,
                "parent_code": entry.parent_code,
            }
            for entry in entries
        ]

    def _resolve_display_name(self, entry: CodeCatalog, locale: str) -> str:
        """
        Resolve display name with locale fallback to English.

        If the requested locale's translation is NULL (not yet translated),
        falls back to English which is always populated (required field).

        Args:
            entry: The CodeCatalog model instance.
            locale: Requested locale ("en", "fr", "pt").

        Returns:
            Display name string in the best available locale.
        """
        # Try requested locale first
        if locale == "fr" and entry.display_name_fr:
            return entry.display_name_fr
        if locale == "pt" and entry.display_name_pt:
            return entry.display_name_pt

        # Fallback to English (always populated — required field)
        return entry.display_name_en
