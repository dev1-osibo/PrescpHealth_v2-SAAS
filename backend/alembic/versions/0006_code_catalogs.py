"""Create code_catalogs table for ICD-10, ATC, LOINC, SNOMED reference data.

Revision ID: 0006
Revises: 0005_measurement_tables
Create Date: 2025-06-01

Creates the shared clinical code reference table:
- code_catalogs: Stores validated codes from international classification
  systems (ICD-10, ATC, LOINC, SNOMED CT) with multilingual display names.

Design Decisions:
- NOT tenant-scoped: Clinical codes are universal reference data shared
  across all tenants. No RLS policies on this table.
- NOT PHI: Contains publicly available classification data (drug names,
  disease codes, lab test names) — not patient-specific information.
- GIN trigram index on display_name_en enables fuzzy search for clinician
  code selection UI (e.g., typing "diabet" finds "Diabetes mellitus type 2").
- Unique constraint on (catalog_type, code) prevents duplicate entries
  and enables sub-5ms validation via indexed lookup.
- parent_code supports hierarchical navigation (ICD-10 chapters → blocks → codes).
- Multilingual display names (en, fr, pt) support i18n for African deployment.

Indexes:
- Unique: (catalog_type, code) — validation and deduplication
- GIN trigram: display_name_en — fuzzy search (requires pg_trgm extension)
- Regular: (catalog_type, is_active) — filtered listing queries

No RLS:
- This table has NO Row-Level Security because it is shared reference data.
- All tenants read from the same code catalog.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# Revision identifiers
revision: str = "0006_code_catalogs"
down_revision: Union[str, None] = "0005_measurement_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create code_catalogs table with indexes for validation and fuzzy search.

    Steps:
    1. Ensure pg_trgm extension is available (for GIN trigram index)
    2. Create code_catalogs table with all columns and constraints
    3. Create GIN trigram index on display_name_en for fuzzy search
    """

    # --- Step 1: Enable pg_trgm extension for fuzzy search ---
    # pg_trgm provides trigram-based similarity matching, enabling queries like:
    # SELECT * FROM code_catalogs WHERE display_name_en % 'diabet'
    # This finds "Diabetes mellitus type 2" even with partial/misspelled input.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # --- Step 2: Create code_catalogs table ---
    op.create_table(
        "code_catalogs",
        # Primary key — UUID
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique code catalog entry identifier (UUID)",
        ),
        # Classification system discriminator
        sa.Column(
            "catalog_type",
            sa.String(10),
            nullable=False,
            comment="Classification system: icd10, atc, loinc, or snomed",
        ),
        # The clinical code itself
        sa.Column(
            "code",
            sa.String(20),
            nullable=False,
            comment="Clinical code (e.g., E11.9, N02BE01, 2345-7, 80146002)",
        ),
        # Multilingual display names
        sa.Column(
            "display_name_en",
            sa.String(500),
            nullable=False,
            comment="English display name (required for all codes)",
        ),
        sa.Column(
            "display_name_fr",
            sa.String(500),
            nullable=True,
            comment="French display name (for francophone African countries)",
        ),
        sa.Column(
            "display_name_pt",
            sa.String(500),
            nullable=True,
            comment="Portuguese display name (for lusophone African countries)",
        ),
        # Status flag
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether this code is currently valid for clinical use",
        ),
        # Hierarchical parent reference
        sa.Column(
            "parent_code",
            sa.String(20),
            nullable=True,
            comment="Parent code for hierarchy (ICD-10 chapter -> block -> code)",
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Row creation timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Last modification timestamp (UTC)",
        ),
        # Unique constraint: no duplicate codes within a classification system
        sa.UniqueConstraint(
            "catalog_type",
            "code",
            name="uq_code_catalog_type_code",
        ),
    )

    # --- Step 3: Create indexes ---
    op.execute("""
        -- Index: (catalog_type, is_active) for filtered listing queries
        -- Used when displaying all active codes of a given type in the UI
        CREATE INDEX ix_code_catalogs_type_active
            ON code_catalogs (catalog_type, is_active);

        -- GIN trigram index on display_name_en for fuzzy search
        -- Enables similarity-based matching: WHERE display_name_en % 'query'
        -- or: WHERE display_name_en ILIKE '%query%' with trigram acceleration
        -- This powers the clinician code selection autocomplete UI
        CREATE INDEX ix_code_catalogs_display_name_en_trgm
            ON code_catalogs
            USING GIN (display_name_en gin_trgm_ops);
    """)


def downgrade() -> None:
    """
    Drop code_catalogs table and associated indexes.

    WARNING: This permanently deletes all code catalog reference data.
    Only use in development — production should never drop reference data.
    """
    # Drop the table (indexes and constraints dropped automatically)
    op.drop_table("code_catalogs")

    # Note: We do NOT drop the pg_trgm extension because other tables
    # or future migrations may depend on it.
