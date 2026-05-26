"""
PrescpHealth Backend — Code Catalog API Router.

Read-only endpoints for clinical code reference data:
- GET /api/v1/codes/{catalog_type}/validate/{code} — validate a code exists
- GET /api/v1/codes/{catalog_type}/search — fuzzy search by display name
- GET /api/v1/codes/{catalog_type}/hierarchy — hierarchical browsing
- GET /api/v1/codes/{catalog_type}/{code} — lookup single code display name

Access Control:
    NO RBAC restriction — code catalogs are public reference data.
    Any authenticated user (or even unauthenticated, depending on gateway
    config) can query codes. This is intentional because:
    - ICD-10, ATC, LOINC, SNOMED are publicly available standards
    - Code lookup is needed by all clinical roles during data entry
    - No PHI is exposed through these endpoints

Performance:
    - validate: Sub-5ms via unique constraint indexed lookup
    - lookup: Sub-5ms via same indexed lookup
    - search: <100ms via GIN trigram index on display_name_en
    - hierarchy: <20ms via indexed parent_code lookup

Per API design steering rule:
    - All responses use the standard envelope format
    - No cursor pagination needed (results are bounded by limit param)
    - Timestamps in ISO-8601 UTC

Requirements Satisfied:
    - 1.3: ICD-10 code validation for encounters
    - 2.2: ATC code validation for prescriptions
    - 3.2: LOINC code validation for lab orders
    - 4.6: FHIR R4 value sets for coded fields
    - 15.4: Locale-specific display names for clinical terminology
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory
from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.exceptions import InvalidCodeError
from app.modules.code_catalogs.service import CodeCatalogService

# ---------------------------------------------------------------------------
# Module logger — safe to log code catalog data (NOT PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition — read-only, no RBAC restriction
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/api/v1/codes",
    tags=["code-catalogs"],
)

# ---------------------------------------------------------------------------
# Shared service instance (stateless, safe to reuse)
# ---------------------------------------------------------------------------
_service = CodeCatalogService()


# ---------------------------------------------------------------------------
# GET /api/v1/codes/{catalog_type}/validate/{code}
# ---------------------------------------------------------------------------
@router.get(
    "/{catalog_type}/validate/{code}",
    response_model=None,
    summary="Validate a clinical code",
    description="Check whether a clinical code exists and is active in the "
    "specified catalog. Returns {valid: true} if the code is valid, or "
    "{valid: false} with reason if not. Used by encounters, prescriptions, "
    "and lab orders to validate codes before saving clinical records.",
)
async def validate_code(
    request: Request,
    catalog_type: CatalogType,
    code: str,
) -> JSONResponse:
    """
    Validate that a clinical code exists and is active.

    Uses the unique constraint index on (catalog_type, code) for
    sub-5ms lookup. Returns a boolean result rather than raising
    an error, so the UI can show inline validation feedback.

    Args:
        catalog_type: Classification system (icd10, atc, loinc, snomed).
        code: The code string to validate (e.g., "E11.9", "N02BE01").

    Returns:
        JSONResponse with {valid: bool, code, catalog_type} in envelope.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    factory = get_session_factory()
    async with factory() as db:
        try:
            await _service.validate_code(db, catalog_type, code)
            is_valid = True
        except InvalidCodeError:
            # Code doesn't exist or is inactive — not an error for this endpoint
            is_valid = False

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "valid": is_valid,
                "code": code,
                "catalog_type": catalog_type.value,
            },
            "meta": {"request_id": request_id},
        },
    )


# ---------------------------------------------------------------------------
# GET /api/v1/codes/{catalog_type}/search
# ---------------------------------------------------------------------------
@router.get(
    "/{catalog_type}/search",
    response_model=None,
    summary="Search codes by display name",
    description="Fuzzy search for clinical codes by display name using "
    "PostgreSQL trigram similarity. Powers the autocomplete UI where "
    "clinicians type partial code names (e.g., 'diabet' matches "
    "'Diabetes mellitus type 2'). Results ordered by similarity score.",
)
async def search_codes(
    request: Request,
    catalog_type: CatalogType,
    q: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description="Search query (partial name, e.g., 'diabet', 'metform')",
    ),
    locale: str = Query(
        "en",
        description="Language for display names: en, fr, or pt",
        pattern="^(en|fr|pt)$",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum results to return (default 20, max 100)",
    ),
) -> JSONResponse:
    """
    Fuzzy search codes by display name using trigram similarity.

    Uses the GIN trigram index on display_name_en for fast matching.
    Results are limited to prevent large payloads over low-bandwidth
    connections (Africa-specific performance consideration).

    Args:
        catalog_type: Classification system to search within.
        q: Search string (partial name).
        locale: Language for display names in results (en, fr, pt).
        limit: Maximum results to return.

    Returns:
        JSONResponse with list of matching codes in envelope.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    factory = get_session_factory()
    async with factory() as db:
        results = await _service.search_codes(
            db,
            catalog_type=catalog_type,
            query=q,
            locale=locale,
            limit=limit,
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "items": results,
            },
            "meta": {"request_id": request_id},
        },
    )


# ---------------------------------------------------------------------------
# GET /api/v1/codes/{catalog_type}/hierarchy
# ---------------------------------------------------------------------------
@router.get(
    "/{catalog_type}/hierarchy",
    response_model=None,
    summary="Browse codes hierarchically",
    description="Get child codes for hierarchical browsing. Supports ICD-10 "
    "chapter → block → code navigation where clinicians can drill down "
    "from broad categories to specific codes. Pass parent=None (omit) "
    "for top-level codes.",
)
async def get_code_hierarchy(
    request: Request,
    catalog_type: CatalogType,
    parent: Optional[str] = Query(
        None,
        description="Parent code to get children for (omit for top-level codes)",
    ),
) -> JSONResponse:
    """
    Get child codes for hierarchical navigation.

    Enables tree-based browsing of classification systems. Clinicians
    can start at the top level (chapters) and drill down to specific
    codes. Useful for ICD-10 where the hierarchy is:
    Chapter → Block → Category → Code.

    Args:
        catalog_type: Classification system to browse.
        parent: Parent code to get children for (None = top-level).

    Returns:
        JSONResponse with list of child codes in envelope.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    factory = get_session_factory()
    async with factory() as db:
        results = await _service.get_code_hierarchy(
            db,
            catalog_type=catalog_type,
            parent_code=parent,
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "items": results,
            },
            "meta": {"request_id": request_id},
        },
    )


# ---------------------------------------------------------------------------
# GET /api/v1/codes/{catalog_type}/{code}
# ---------------------------------------------------------------------------
@router.get(
    "/{catalog_type}/{code}",
    response_model=None,
    summary="Lookup a single code",
    description="Look up a code's display name in the requested locale. "
    "Falls back to English if the requested locale translation is not "
    "available. Returns 404 if the code doesn't exist in the catalog.",
)
async def lookup_code(
    request: Request,
    catalog_type: CatalogType,
    code: str,
    locale: str = Query(
        "en",
        description="Language for display name: en, fr, or pt",
        pattern="^(en|fr|pt)$",
    ),
) -> JSONResponse:
    """
    Look up a single code's display name in the requested locale.

    Supports multilingual display for francophone and lusophone
    African clinicians. Falls back to English if the requested
    locale translation is NULL (not yet translated).

    Args:
        catalog_type: Classification system (icd10, atc, loinc, snomed).
        code: The code string to look up.
        locale: Language code (en, fr, pt). Defaults to English.

    Returns:
        JSONResponse with {code, display_name, catalog_type} in envelope.
        404 if code doesn't exist.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    factory = get_session_factory()
    async with factory() as db:
        try:
            result = await _service.lookup_code(
                db,
                catalog_type=catalog_type,
                code=code,
                locale=locale,
            )
        except InvalidCodeError:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Code '{code}' not found in {catalog_type.value} catalog",
                        "details": [],
                        "request_id": request_id,
                    },
                },
            )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": result,
            "meta": {"request_id": request_id},
        },
    )
