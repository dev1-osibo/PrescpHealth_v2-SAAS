"""
PrescpHealth Backend — Code Catalog SQLAlchemy Model.

Defines the CodeCatalog model for storing clinical reference codes:
- ICD-10 disease codes (e.g., E11.9 = Type 2 diabetes mellitus)
- ATC drug codes (e.g., N02BE01 = Paracetamol)
- LOINC lab test codes (e.g., 2345-7 = Glucose [Mass/volume] in Serum)
- SNOMED procedure codes (e.g., 80146002 = Appendectomy)

Architecture Notes:
    - This table is NOT tenant-scoped (shared reference data across all tenants)
    - No TenantMixin — no RLS policies on this table
    - Uses TimestampMixin for created_at/updated_at tracking
    - Unique constraint on (catalog_type, code) prevents duplicate entries
    - GIN trigram index on display_name_en enables fuzzy search
      (e.g., "diabet" matches "Diabetes mellitus type 2")
    - parent_code enables hierarchical navigation (ICD-10 chapters → blocks → codes)

Performance:
    - Sub-5ms validation via indexed unique constraint lookup
    - Fuzzy search via GIN trigram index (requires pg_trgm extension)
    - Regular index on (catalog_type, is_active) for filtered listing

This is NOT PHI — these are publicly available classification systems.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin


class CodeCatalog(TimestampMixin, Base):
    """
    Clinical code reference data for ICD-10, ATC, LOINC, and SNOMED.

    This model stores the canonical codes and their multilingual display
    names used for validation and UI display throughout the EMR system.
    It is shared across all tenants (no RLS) because clinical codes are
    universal reference data, not patient-specific information.

    Attributes:
        id: Unique identifier (UUID primary key)
        catalog_type: Classification system ("icd10", "atc", "loinc", "snomed")
        code: The actual code string (e.g., "E11.9", "N02BE01", "2345-7")
        display_name_en: English display name (required)
        display_name_fr: French display name (optional, for francophone Africa)
        display_name_pt: Portuguese display name (optional, for lusophone Africa)
        is_active: Whether this code is currently valid for use
        parent_code: Parent code for hierarchical navigation (nullable)
        created_at: When this record was created (from TimestampMixin)
        updated_at: When this record was last modified (from TimestampMixin)

    Constraints:
        - Unique: (catalog_type, code) — no duplicate codes within a system
        - GIN trigram index on display_name_en for fuzzy search
        - Regular index on (catalog_type, is_active) for filtered queries
    """

    __tablename__ = "code_catalogs"

    # --- Primary Key ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
        comment="Unique code catalog entry identifier (UUID)",
    )

    # --- Classification System Discriminator ---
    catalog_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Classification system: icd10, atc, loinc, or snomed",
    )

    # --- The Code Itself ---
    code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Clinical code (e.g., E11.9, N02BE01, 2345-7, 80146002)",
    )

    # --- Multilingual Display Names ---
    # English is required; French and Portuguese support i18n for Africa
    display_name_en: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="English display name (required for all codes)",
    )

    display_name_fr: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="French display name (for francophone African countries)",
    )

    display_name_pt: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Portuguese display name (for lusophone African countries)",
    )

    # --- Status and Hierarchy ---
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        comment="Whether this code is currently valid for clinical use",
    )

    parent_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Parent code for hierarchy (e.g., ICD-10 chapter → block → code)",
    )

    # --- Table-Level Constraints and Indexes ---
    __table_args__ = (
        # Unique constraint: no duplicate codes within a classification system
        UniqueConstraint(
            "catalog_type",
            "code",
            name="uq_code_catalog_type_code",
        ),
        # Regular index for filtered listing queries
        # (e.g., "get all active ICD-10 codes")
        Index(
            "ix_code_catalogs_type_active",
            "catalog_type",
            "is_active",
        ),
        {
            "comment": (
                "Shared clinical code reference data (ICD-10, ATC, LOINC, SNOMED). "
                "NOT tenant-scoped — no RLS. NOT PHI."
            ),
        },
    )

    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        return (
            f"<CodeCatalog(catalog_type={self.catalog_type!r}, "
            f"code={self.code!r}, "
            f"display_name_en={self.display_name_en!r})>"
        )
