"""
Alembic Migration 0022 — Billing Tables
========================================
Creates the billing tables:
  - invoices
  - invoice_line_items
  - payments
  - insurance_claims

All tables have:
  - UUID primary keys
  - Row Level Security (RLS) tenant isolation
  - Indexed foreign keys

HIPAA NOTE:
  All monetary columns use NUMERIC(10,2) — never FLOAT.
  No PHI is stored in any billing table field that appears in logs.

down_revision: 0021_registration_tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0022_billing_tables"
down_revision = "0021_registration_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create billing tables with RLS and indexes."""

    # ------------------------------------------------------------------
    # Enum types (PostgreSQL native enums for performance)
    # ------------------------------------------------------------------
    invoice_status = postgresql.ENUM(
        "draft", "issued", "paid", "partially_paid", "overdue", "cancelled", "void",
        name="invoicestatus", create_type=True,
    )
    item_type = postgresql.ENUM(
        "consultation", "procedure", "lab_test", "medication", "supply", "other",
        name="itemtype", create_type=True,
    )
    payment_method = postgresql.ENUM(
        "cash", "card", "bank_transfer", "mobile_money", "insurance",
        name="paymentmethod", create_type=True,
    )
    claim_status = postgresql.ENUM(
        "submitted", "pending_review", "approved", "partially_approved",
        "denied", "resubmitted",
        name="claimstatus", create_type=True,
    )

    for enum in (invoice_status, item_type, payment_method, claim_status):
        enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # invoices table
    # ------------------------------------------------------------------
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("encounters.id"), nullable=False),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("status",
                  sa.Enum("draft","issued","paid","partially_paid","overdue",
                          "cancelled","void", name="invoicestatus"),
                  nullable=False, server_default="draft"),
        # NUMERIC(10,2) — never FLOAT for money
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # Unique invoice number per tenant
        sa.UniqueConstraint("tenant_id", "invoice_number",
                            name="uq_invoice_number_per_tenant"),
    )
    op.create_index("ix_invoices_tenant", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_patient", "invoices", ["tenant_id", "patient_id"])
    op.create_index("ix_invoices_encounter", "invoices", ["encounter_id"])

    op.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE invoices FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON invoices
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # invoice_line_items table
    # ------------------------------------------------------------------
    op.create_table(
        "invoice_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("item_type",
                  sa.Enum("consultation","procedure","lab_test","medication","supply","other",
                          name="itemtype"),
                  nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_line_items_invoice", "invoice_line_items", ["invoice_id"])

    op.execute("ALTER TABLE invoice_line_items ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE invoice_line_items FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON invoice_line_items
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # payments table
    # ------------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_method",
                  sa.Enum("cash","card","bank_transfer","mobile_money","insurance",
                          name="paymentmethod"),
                  nullable=False),
        sa.Column("reference_number", sa.String(128), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])
    op.create_index("ix_payments_tenant", "payments", ["tenant_id"])

    op.execute("ALTER TABLE payments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE payments FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON payments
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # insurance_claims table
    # ------------------------------------------------------------------
    op.create_table(
        "insurance_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("insurance_provider", sa.String(255), nullable=False),
        sa.Column("policy_number", sa.String(128), nullable=False),
        sa.Column("claim_number", sa.String(128), nullable=True),
        sa.Column("status",
                  sa.Enum("submitted","pending_review","approved","partially_approved",
                          "denied","resubmitted", name="claimstatus"),
                  nullable=False, server_default="submitted"),
        sa.Column("submitted_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("approved_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("denial_reason", sa.Text, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_claims_invoice", "insurance_claims", ["invoice_id"])
    op.create_index("ix_claims_patient", "insurance_claims", ["tenant_id", "patient_id"])

    op.execute("ALTER TABLE insurance_claims ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE insurance_claims FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON insurance_claims
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop all billing tables and associated enum types."""

    # Drop policies and tables in reverse FK dependency order
    for table in ("insurance_claims", "payments", "invoice_line_items", "invoices"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")

    op.drop_index("ix_claims_patient", table_name="insurance_claims")
    op.drop_index("ix_claims_invoice", table_name="insurance_claims")
    op.drop_table("insurance_claims")

    op.drop_index("ix_payments_tenant", table_name="payments")
    op.drop_index("ix_payments_invoice", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_line_items_invoice", table_name="invoice_line_items")
    op.drop_table("invoice_line_items")

    op.drop_index("ix_invoices_encounter", table_name="invoices")
    op.drop_index("ix_invoices_patient", table_name="invoices")
    op.drop_index("ix_invoices_tenant", table_name="invoices")
    op.drop_table("invoices")

    # Drop enum types last
    op.execute("DROP TYPE IF EXISTS claimstatus;")
    op.execute("DROP TYPE IF EXISTS paymentmethod;")
    op.execute("DROP TYPE IF EXISTS itemtype;")
    op.execute("DROP TYPE IF EXISTS invoicestatus;")
