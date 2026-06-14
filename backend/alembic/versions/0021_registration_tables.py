"""
Alembic Migration 0021 — Registration Tables
==============================================
Creates the `consents` and `identity_verifications` tables with:
  - UUID primary keys
  - Row Level Security (RLS) tenant isolation
  - Indexes for patient-centric queries

HIPAA NOTE: The document_number column in identity_verifications stores
government ID numbers — it is never logged, only stored for audit trail.

down_revision: 0020_documents_table
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0021_registration_tables"
down_revision = "0020_documents_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create consents and identity_verifications tables with RLS."""

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    consenttype = postgresql.ENUM(
        "treatment", "data_sharing", "research", "hipaa_notice", "telehealth",
        name="consenttype", create_type=True,
    )
    verificationtype = postgresql.ENUM(
        "government_id", "passport", "insurance_card", "biometric", "other",
        name="verificationtype", create_type=True,
    )
    consenttype.create(op.get_bind(), checkfirst=True)
    verificationtype.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # consents table
    # ------------------------------------------------------------------
    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "consent_type",
            sa.Enum("treatment","data_sharing","research","hipaa_notice","telehealth", name="consenttype"),
            nullable=False,
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("is_granted", sa.Boolean, nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # digital_signature: base64 — PHI, NEVER log
        sa.Column("digital_signature", sa.Text, nullable=True),
        sa.Column("witness_name", sa.String(255), nullable=True),
        sa.Column("captured_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_consent_patient", "consents", ["tenant_id", "patient_id"])
    op.create_index("ix_consent_type", "consents", ["tenant_id", "consent_type"])

    op.execute("ALTER TABLE consents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE consents FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON consents
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # identity_verifications table
    # ------------------------------------------------------------------
    op.create_table(
        "identity_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "verification_type",
            sa.Enum("government_id","passport","insurance_card","biometric","other", name="verificationtype"),
            nullable=False,
        ),
        # document_number: PHI — stored for audit trail, NEVER log
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("issuing_authority", sa.String(255), nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_identity_patient", "identity_verifications", ["tenant_id", "patient_id"])

    op.execute("ALTER TABLE identity_verifications ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE identity_verifications FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON identity_verifications
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop registration tables and associated enum types."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON identity_verifications;")
    op.drop_index("ix_identity_patient", table_name="identity_verifications")
    op.drop_table("identity_verifications")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON consents;")
    op.drop_index("ix_consent_type", table_name="consents")
    op.drop_index("ix_consent_patient", table_name="consents")
    op.drop_table("consents")

    op.execute("DROP TYPE IF EXISTS verificationtype;")
    op.execute("DROP TYPE IF EXISTS consenttype;")
