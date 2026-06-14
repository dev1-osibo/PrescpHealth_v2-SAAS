"""
Alembic Migration 0020 — Documents Table
==========================================
Creates the `documents` table with:
  - UUID primary key
  - Immutable schema (no updated_at)
  - Row Level Security (RLS) tenant isolation
  - Composite indexes for patient and document type queries

down_revision: 0019_referrals_table
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0020_documents_table"
down_revision = "0019_referrals_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the documents table with RLS and indexes."""

    # ------------------------------------------------------------------
    # Enum type
    # ------------------------------------------------------------------
    documenttype = postgresql.ENUM(
        "lab_report", "radiology", "discharge_summary", "consent_form",
        "referral_letter", "clinical_note", "imaging", "other",
        name="documenttype", create_type=True,
    )
    documenttype.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # documents table (immutable — no updated_at)
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id"), nullable=True),
        sa.Column(
            "document_type",
            sa.Enum(
                "lab_report","radiology","discharge_summary","consent_form",
                "referral_letter","clinical_note","imaging","other",
                name="documenttype",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("storage_backend", sa.String(50), nullable=False, server_default="local"),
        sa.Column("is_encrypted", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        # NOTE: No updated_at — documents are immutable after upload
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    op.create_index("ix_doc_patient", "documents", ["tenant_id", "patient_id"])
    op.create_index("ix_doc_type", "documents", ["tenant_id", "document_type"])

    # ------------------------------------------------------------------
    # Row Level Security
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON documents
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop the documents table and associated enum type."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON documents;")
    op.drop_index("ix_doc_type", table_name="documents")
    op.drop_index("ix_doc_patient", table_name="documents")
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS documenttype;")
