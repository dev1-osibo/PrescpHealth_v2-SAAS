"""
PrescpHealth Backend — Code Catalog Exceptions.

Custom exceptions for clinical code validation failures.
These are raised when a code doesn't exist in the catalog or is inactive.

HIPAA Note:
    Code catalog data is NOT PHI — ICD-10, ATC, LOINC, and SNOMED codes
    are publicly available classification systems. It is safe to include
    catalog_type and code values in error messages and logs.
"""

from app.core.exceptions import ValidationError


class InvalidCodeError(ValidationError):
    """
    Raised when a clinical code doesn't exist or is inactive in the catalog.

    This error is safe to expose to the client because code catalog data
    is public reference data (ICD-10, ATC, LOINC, SNOMED), not PHI.

    Examples:
        - Code "X99.9" doesn't exist in ICD-10 catalog
        - Code "E11.9" exists but is_active=False (deprecated/retired)
    """

    def __init__(self, catalog_type: str, code: str, reason: str = "not_found") -> None:
        """
        Initialize with catalog context for debugging.

        Args:
            catalog_type: The classification system (icd10, atc, loinc, snomed).
            code: The code that failed validation.
            reason: Why validation failed ("not_found" or "inactive").
        """
        super().__init__(
            message=f"Invalid {catalog_type.upper()} code: {code}",
            details={
                "catalog_type": catalog_type,
                "code": code,
                "reason": reason,
            },
        )
