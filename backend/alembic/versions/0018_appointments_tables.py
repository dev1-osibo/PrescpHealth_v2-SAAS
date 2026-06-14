"""
Alembic Migration 0018 — Appointments Tables
==============================================
Creates the `appointments` and `waitlist` tables with:
  - UUID primary keys
  - Row Level Security (RLS) tenant isolation
  - Composite indexes for common query patterns

down_revision: 0017_background_tasks_table
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0018_appointments_tables"
down_revision = "0017_background_tasks_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create appointments and waitlist tables with RLS and indexes."""

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    appointmenttype = postgresql.ENUM(
        "consultation", "follow_up", "procedure", "screening", "urgent",
        name="appointmenttype", create_type=True,
    )
    appointmentstatus = postgresql.ENUM(
        "scheduled", "confirmed", "checked_in", "in_progress",
        "completed", "cancelled", "no_show",
        name="appointmentstatus", create_type=True,
    )
    waitliststatus = postgresql.ENUM(
        "waiting", "offered", "booked", "expired", "cancelled",
        name="waitliststatus", create_type=True,
    )
    appointmenttype.create(op.get_bind(), checkfirst=True)
    appointmentstatus.create(op.get_bind(), checkfirst=True)
    waitliststatus.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # appointments table
    # ------------------------------------------------------------------
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("clinician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("appointment_type", sa.Enum("consultation","follow_up","procedure","screening","urgent", name="appointmenttype"), nullable=False),
        sa.Column("status", sa.Enum("scheduled","confirmed","checked_in","in_progress","completed","cancelled","no_show", name="appointmentstatus"), nullable=False, server_default="scheduled"),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("recurrence_rule", postgresql.JSONB, nullable=True),
        sa.Column("parent_appointment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("appointments.id"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_appt_clinician_time", "appointments", ["tenant_id", "clinician_id", "scheduled_start"])
    op.create_index("ix_appt_patient_status", "appointments", ["tenant_id", "patient_id", "status"])
    op.create_index("ix_appt_status_time", "appointments", ["tenant_id", "status", "scheduled_start"])

    op.execute("ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE appointments FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON appointments
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # waitlist table
    # ------------------------------------------------------------------
    op.create_table(
        "waitlist",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("clinician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("appointment_type", sa.Enum("consultation","follow_up","procedure","screening","urgent", name="appointmenttype"), nullable=False),
        sa.Column("preferred_date_start", sa.Date, nullable=False),
        sa.Column("preferred_date_end", sa.Date, nullable=True),
        sa.Column("preferred_time_start", sa.Time, nullable=True),
        sa.Column("preferred_time_end", sa.Time, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Enum("waiting","offered","booked","expired","cancelled", name="waitliststatus"), nullable=False, server_default="waiting"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_waitlist_patient", "waitlist", ["tenant_id", "patient_id"])
    op.create_index("ix_waitlist_status", "waitlist", ["tenant_id", "status"])

    op.execute("ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE waitlist FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON waitlist
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop appointments and waitlist tables and associated types."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON waitlist;")
    op.drop_index("ix_waitlist_status", table_name="waitlist")
    op.drop_index("ix_waitlist_patient", table_name="waitlist")
    op.drop_table("waitlist")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON appointments;")
    op.drop_index("ix_appt_status_time", table_name="appointments")
    op.drop_index("ix_appt_patient_status", table_name="appointments")
    op.drop_index("ix_appt_clinician_time", table_name="appointments")
    op.drop_table("appointments")

    op.execute("DROP TYPE IF EXISTS waitliststatus;")
    op.execute("DROP TYPE IF EXISTS appointmentstatus;")
    op.execute("DROP TYPE IF EXISTS appointmenttype;")
