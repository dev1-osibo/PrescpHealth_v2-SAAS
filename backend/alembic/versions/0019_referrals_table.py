"""
Alembic Migration 0019 — Referrals Table
==========================================
Creates the `referrals` table with:
  - UUID primary key
  - Row Level Security (RLS) tenant isolation
  - Composite indexes for patient, status, and clinician queries

down_revision: 0018_appointments_tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0019_referrals_table"
down_revision = "0018_appointments_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the referrals table with RLS and indexes."""

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    referralurgency = postgresql.ENUM(
        "routine", "urgent", "emergent",
        name="referralurgency", create_type=True,
    )
    referralstatus = postgresql.ENUM(
        "pending", "accepted", "scheduled", "in_progress",
        "completed", "cancelled", "declined",
        name="referralstatus", create_type=True,
    )
    referralurgency.create(op.get_bind(), checkfirst=True)
    referralstatus.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # referrals table
    # ------------------------------------------------------------------
    op.create_table(
        "referrals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id"), nullable=True),
        sa.Column("referring_clinician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("receiving_clinician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("specialty", sa.String(100), nullable=False),
        sa.Column(
            "urgency",
            sa.Enum("routine", "urgent", "emergent", name="referralurgency"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending","accepted","scheduled","in_progress","completed","cancelled","declined", name="referralstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("clinical_summary", sa.Text, nullable=True),
        sa.Column("referral_letter", postgresql.JSONB, nullable=True),
        sa.Column("specialist_findings", sa.Text, nullable=True),
        sa.Column("specialist_recommendations", sa.Text, nullable=True),
        sa.Column("scheduled_date", sa.Date, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    op.create_index("ix_referral_patient", "referrals", ["tenant_id", "patient_id"])
    op.create_index("ix_referral_status", "referrals", ["tenant_id", "status"])
    op.create_index("ix_referral_clinician", "referrals", ["tenant_id", "referring_clinician_id"])

    # ------------------------------------------------------------------
    # Row Level Security
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE referrals FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON referrals
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop the referrals table and associated enum types."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON referrals;")
    op.drop_index("ix_referral_clinician", table_name="referrals")
    op.drop_index("ix_referral_status", table_name="referrals")
    op.drop_index("ix_referral_patient", table_name="referrals")
    op.drop_table("referrals")
    op.execute("DROP TYPE IF EXISTS referralstatus;")
    op.execute("DROP TYPE IF EXISTS referralurgency;")
