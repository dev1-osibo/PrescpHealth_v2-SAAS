"""
PrescpHealth Backend — Code Catalog Enums.

Defines the supported clinical code classification systems.
Each catalog type corresponds to an international standard:
- ICD-10: Disease/condition classification (WHO)
- ATC: Drug/medication classification (WHO)
- LOINC: Laboratory test/observation codes (Regenstrief Institute)
- SNOMED: Clinical procedure codes (SNOMED International)

These enums are used as the catalog_type discriminator in the
code_catalogs table to partition codes by classification system.
"""

from enum import Enum


class CatalogType(str, Enum):
    """
    Supported clinical code classification systems.

    Each value corresponds to a well-known international standard
    used in healthcare for coding diagnoses, drugs, lab tests,
    and procedures respectively.
    """

    # International Classification of Diseases, 10th Revision
    # Used for coding diagnoses in encounters
    ICD10 = "icd10"

    # Anatomical Therapeutic Chemical classification
    # Used for coding drugs in prescriptions
    ATC = "atc"

    # Logical Observation Identifiers Names and Codes
    # Used for coding lab tests and clinical observations
    LOINC = "loinc"

    # Systematized Nomenclature of Medicine — Clinical Terms
    # Used for coding procedures performed during encounters
    SNOMED = "snomed"
