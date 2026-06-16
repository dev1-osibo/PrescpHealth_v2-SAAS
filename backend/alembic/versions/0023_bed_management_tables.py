"""
Alembic Migration 0023 — Bed Management Tables
===============================================
Creates:
  - wards
  - beds
  - admissions
  - nursing_notes

All tables have UUID PKs, RLS tenant isolation, and relevant indexes.

HIPAA NOTE:
  admissions.reason, admissions.notes, and nursing_notes.content are PHI.
  They are stored encrypted-at-rest but never appear in application logs.

down_revision: 0022_billing_tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0023_bed_management_tables"
down_revision = "0022_billing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create bed management tables with RLS and indexes."""

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    bed_status = postgresql.ENUM(
        "available", "occupied", "maintenance", "reserved",
        name="bedstatus", create_type=True,
    )
    bed_type = postgresql.ENUM(
        "standard", "icu", "isolation", "pediatric", "maternity",
        name="bedtype", create_type=True,
    )
    admission_status = postgresql.ENUM(
        "active", "discharged", "transferred",
        name="admissionstatus", create_type=True,
    )
    discharge_type = postgresql.ENUM(
        "routine", "against_medical_advice", "transfer", "deceased",
        name="dischargetype", create_type=True,
    )
    note_type = postgresql.ENUM(
        "assessment", "intervention", "evaluation", "handoff", "general",
        name="notetype", create_type=True,
    )

    for enum in (bed_status, bed_type, admission_status, discharge_type, note_type):
        enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # wards table
    # ------------------------------------------------------------------
    op.create_table(
        "wards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("floor", sa.Integer, nullable=True),
        sa.Column("specialty", sa.String(128), nullable=True),
        sa.Column("total_beds", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wards_tenant", "wards", ["tenant_id"])

    op.execute("ALTER TABLE wards ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE wards FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON wards
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # beds table
    # ------------------------------------------------------------------
    op.create_table(
        "beds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ward_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("wards.id"), nullable=False),
        sa.Column("bed_number", sa.String(32), nullable=False),
        sa.Column("status",
                  sa.Enum("available","occupied","maintenance","reserved", name="bedstatus"),
                  nullable=False, server_default="available"),
        sa.Column("bed_type",
                  sa.Enum("standard","icu","isolation","pediatric","maternity", name="bedtype"),
                  nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # Unique bed number within a ward per tenant
        sa.UniqueConstraint("tenant_id", "ward_id", "bed_number", name="uq_bed_per_ward"),
    )
    op.create_index("ix_beds_ward", "beds", ["ward_id"])
    op.create_index("ix_beds_tenant", "beds", ["tenant_id"])
    op.create_index("ix_beds_status", "beds", ["tenant_id", "status"])

    op.execute("ALTER TABLE beds ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE beds FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON beds
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # admissions table
    # ------------------------------------------------------------------
    op.create_table(
        "admissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("bed_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("beds.id"), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("encounters.id"), nullable=True),
        sa.Column("admitting_doctor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discharged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discharge_type",
                  sa.Enum("routine","against_medical_advice","transfer","deceased",
                          name="dischargetype"),
                  nullable=True),
        # JSONB discharge plan — PHI, not logged
        sa.Column("discharge_plan", postgresql.JSONB, nullable=True),
        sa.Column("status",
                  sa.Enum("active","discharged","transferred", name="admissionstatus"),
                  nullable=False, server_default="active"),
        # reason and notes: PHI — stored, never logged
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admissions_tenant", "admissions", ["tenant_id"])
    op.create_index("ix_admissions_patient", "admissions", ["tenant_id", "patient_id"])
    op.create_index("ix_admissions_bed", "admissions", ["bed_id"])

    op.execute("ALTER TABLE admissions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE admissions FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON admissions
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # nursing_notes table
    # ------------------------------------------------------------------
    op.create_table(
        "nursing_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("admissions.id"), nullable=False),
        sa.Column("nurse_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        # content is PHI — stored, never logged
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("note_type",
                  sa.Enum("assessment","intervention","evaluation","handoff","general",
                          name="notetype"),
                  nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_nursing_notes_admission", "nursing_notes", ["admission_id"])
    op.create_index("ix_nursing_notes_tenant", "nursing_notes", ["tenant_id"])

    op.execute("ALTER TABLE nursing_notes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE nursing_notes FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON nursing_notes
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop bed management tables and enum types."""
    for table in ("nursing_notes", "admissions", "beds", "wards"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")

    op.drop_index("ix_nursing_notes_tenant", table_name="nursing_notes")
    op.drop_index("ix_nursing_notes_admission", table_name="nursing_notes")
    op.drop_table("nursing_notes")

    op.drop_index("ix_admissions_bed", table_name="admissions")
    op.drop_index("ix_admissions_patient", table_name="admissions")
    op.drop_index("ix_admissions_tenant", table_name="admissions")
    op.drop_table("admissions")

    op.drop_index("ix_beds_status", table_name="beds")
    op.drop_index("ix_beds_tenant", table_name="beds")
    op.drop_index("ix_beds_ward", table_name="beds")
    op.drop_table("beds")

    op.drop_index("ix_wards_tenant", table_name="wards")
    op.drop_table("wards")

    op.execute("DROP TYPE IF EXISTS notetype;")
    op.execute("DROP TYPE IF EXISTS dischargetype;")
    op.execute("DROP TYPE IF EXISTS admissionstatus;")
    op.execute("DROP TYPE IF EXISTS bedtype;")
    op.execute("DROP TYPE IF EXISTS bedstatus;")
