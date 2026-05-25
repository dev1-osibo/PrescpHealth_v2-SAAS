"""
PrescpHealth Backend — Code Catalogs Module.

This module provides shared reference data for clinical code validation:
- ICD-10 codes (International Classification of Diseases, 10th Revision)
- ATC codes (Anatomical Therapeutic Chemical classification for drugs)
- LOINC codes (Logical Observation Identifiers Names and Codes for lab tests)
- SNOMED CT codes (Systematized Nomenclature of Medicine for procedures)

Key Responsibilities:
- Validate clinical codes against local lookup tables (sub-5ms, no external API)
- Provide fuzzy search on display names for clinician code selection UI
- Support multilingual display names (English, French, Portuguese)
- Maintain hierarchical code relationships via parent_code

Architecture Notes:
    This is NOT tenant-scoped data. Code catalogs are shared reference data
    across all tenants. There is NO RLS on the code_catalogs table.
    This is NOT PHI — it contains drug names, disease codes, and lab test
    names that are publicly available classification systems.

Dependencies:
    - app.core.base_model (Base, TimestampMixin)

Data Flow:
    Clinician enters code → CodeCatalogService.validate_code() →
    Accept if exists and is_active=True, reject otherwise →
    Return display_name in requested locale for UI display
"""

from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.exceptions import InvalidCodeError
from app.modules.code_catalogs.models import CodeCatalog
from app.modules.code_catalogs.service import CodeCatalogService

__all__ = [
    "CatalogType",
    "CodeCatalog",
    "CodeCatalogService",
    "InvalidCodeError",
]
