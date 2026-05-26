"""
PrescpHealth Backend — Code Catalog Pydantic Schemas.

Request/response schemas for the code catalog read-only API.
These schemas structure responses for code validation, lookup,
search, and hierarchical browsing operations.

Schema Design:
- Response schemas structure outgoing data (consistent envelope format)
- No write schemas — code catalogs are seeded from official sources only
- No PHI in any schema field — clinical codes are public reference data

HIPAA Note:
    Code catalog data is NOT PHI. ICD-10, ATC, LOINC, and SNOMED codes
    are publicly available international classification systems. It is
    safe to include code values and display names in responses.

Per API design steering rule:
- All responses use the standard envelope format
- No RBAC restriction (read-only public reference data)

Requirements Satisfied:
- 1.3: ICD-10 code validation for encounters
- 2.2: ATC code validation for prescriptions
- 3.2: LOINC code validation for lab orders
- 4.6: FHIR R4 value sets for coded fields
- 15.4: Locale-specific display names for clinical terminology
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class CodeLookupResponse(BaseModel):
    """
    Single code lookup response.

    Returned when looking up a specific code's display name in the
    clinician's preferred locale. Used by the UI to show human-readable
    names alongside code values (e.g., "E11.9 — Type 2 diabetes mellitus").

    Fields:
        code: The clinical code string (e.g., "E11.9", "N02BE01")
        display_name: Locale-resolved display name (falls back to English)
        catalog_type: Classification system identifier (icd10, atc, loinc, snomed)
    """

    code: str = Field(
        ...,
        description="Clinical code string (e.g., 'E11.9', 'N02BE01', '2345-7')",
        examples=["E11.9", "N02BE01", "2345-7"],
    )
    display_name: str = Field(
        ...,
        description="Human-readable display name in the requested locale",
        examples=["Type 2 diabetes mellitus, without complications"],
    )
    catalog_type: str = Field(
        ...,
        description="Classification system: icd10, atc, loinc, or snomed",
        examples=["icd10", "atc", "loinc", "snomed"],
    )

    model_config = {"from_attributes": True}


class CodeSearchResponse(BaseModel):
    """
    Search results response containing a list of matching codes.

    Returned by the fuzzy search endpoint used for autocomplete UI.
    Results are ordered by trigram similarity score (best matches first).
    Limited to a configurable maximum (default 20) to prevent large payloads
    over low-bandwidth connections.

    Fields:
        items: List of matching codes with display names
    """

    items: list[CodeLookupResponse] = Field(
        ...,
        description="List of codes matching the search query, ordered by relevance",
    )


class CodeHierarchyItem(BaseModel):
    """
    Single item in a hierarchical code listing.

    Extends CodeLookupResponse with parent_code for tree navigation.
    Used for ICD-10 chapter → block → code drill-down in the UI.

    Fields:
        code: The clinical code string
        display_name: Human-readable name (English for hierarchy browsing)
        catalog_type: Classification system identifier
        parent_code: Parent code for tree navigation (None = top-level)
    """

    code: str = Field(
        ...,
        description="Clinical code string",
        examples=["E10-E14"],
    )
    display_name: str = Field(
        ...,
        description="Human-readable display name",
        examples=["Diabetes mellitus"],
    )
    catalog_type: str = Field(
        ...,
        description="Classification system: icd10, atc, loinc, or snomed",
        examples=["icd10"],
    )
    parent_code: str | None = Field(
        None,
        description="Parent code for hierarchical navigation (None = top-level)",
        examples=["E00-E90"],
    )

    model_config = {"from_attributes": True}


class CodeHierarchyResponse(BaseModel):
    """
    Hierarchical code listing response.

    Returns child codes for a given parent, enabling tree-based
    navigation of classification systems (e.g., ICD-10 chapters).

    Fields:
        items: List of child codes under the specified parent
    """

    items: list[CodeHierarchyItem] = Field(
        ...,
        description="List of child codes under the specified parent",
    )


class CodeValidationResponse(BaseModel):
    """
    Code validation result response.

    Returned by the validation endpoint to confirm whether a code
    exists and is active in the specified catalog. Used by other
    modules (encounters, prescriptions, lab orders) to validate
    codes before saving clinical records.

    Fields:
        valid: Whether the code exists and is active
        code: The code that was validated
        catalog_type: The classification system checked
    """

    valid: bool = Field(
        ...,
        description="True if the code exists and is active in the catalog",
    )
    code: str = Field(
        ...,
        description="The code that was validated",
        examples=["E11.9", "N02BE01"],
    )
    catalog_type: str = Field(
        ...,
        description="Classification system that was checked",
        examples=["icd10", "atc", "loinc", "snomed"],
    )
