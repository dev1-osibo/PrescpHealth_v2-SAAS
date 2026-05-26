"""Create lab_orders and lab_results tables with RLS and indexes.

Revision ID: 0009
Revises: 0007_encounter_tables
Create Date: 2025-06-01

Creates the laboratory order management tables:
- lab_orders: Clinician requests for laboratory tests with LOINC coding,
  priority levels, and full lifecycle status tracking.
- lab_results: Outcome values from lab processing with reference ranges,
  abnormality flags, and links to the Measurement pipeline.

Design Decisions:
- loinc_code validated at application layer against CodeCatalog before insert
- status column uses string (not PG enum) for easier migration of new states
- priority column uses string for same reason
- fhir_json stores pre-computed FHIR R4 representation for API performance
- encounter_id is nullable — labs can be ordered outside of encounters
- measurement_id on results links to the Measurement record created when
  a result feeds into the risk computation pipeline
- specimen_collected_at is separate from status change timestamp for
  accurate clinical timeline tracking

Indexes:
- (tenant_id, patient_id, status) on lab_orders: Patient lab history filtered by status
- (encounter_id) on lab_orders: Encounter-scoped lab lookups
- (tenant_id, status, priority) on lab_orders: Lab queue dashboard (stat first)
- (lab_order_id) on lab_results: Results for a specific order
- (tenant_id, is_abnormal) on lab_results: Abnormal results dashboard

HIPAA Compliance:
- RLS enforces tenant isolation at database level on both tables
- Lab values are PHI — encrypted at rest via TDE
- No hard delete — records retained for 7+ years
- Audit trail via domain events (LabResultReceived, MeasurementSaved)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers
revision: str = "0009_lab_order_tables"
down_revision: Union[str, None] = "0007_encounter_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create lab_orders and lab_results tables with RLS and indexes.

    Steps:
    1. Create lab_orders table
    2. Enable RLS on lab_orders
    3. Create lab_results table
    4. Enable RLS on lab_results
    5. Create indexes for common query patterns
    """

    # --- Step 1: Create lab_orders table ---
    op.create_table(
        "lab_orders",
        # Primary key
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique lab order identifier (UUID)",
        ),
        # Tenant isolation
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="Tenant UUID for RLS isolation",
        ),
        # Patient reference
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
            comment="Patient this lab order belongs to",
        ),
        # Encounter reference (nullable — labs can be standalone)
        sa.Column(
            "encounter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="SET NULL"),
            nullable=True,
            comment="Originating encounter (NULL if ordered outside a visit)",
        ),
        # Test identification — PHI
        sa.Column(
            "test_name",
            sa.String(255),
            nullable=False,
            comment="PHI: Human-readable lab test name",
        ),
        sa.Column(
            "loinc_code",
            sa.String(20),
            nullable=False,
            comment="LOINC code — validated against CodeCatalog",
        ),
        # Clinical context — PHI
        sa.Column(
            "clinical_indication",
            sa.Text,
            nullable=True,
            comment="PHI: Clinical reason for ordering this test",
        ),
        # Priority and status
        sa.Column(
            "priority",
            sa.String(10),
            nullable=False,
            comment="Processing urgency: routine, urgent, or stat",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'ordered'"),
            comment="Lifecycle: ordered, specimen_collected, in_progress, resulted, cancelled",
        ),
        # Ordering clinician
        sa.Column(
            "ordered_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of the clinician who ordered this test",
        ),
        # Specimen collection timestamp
        sa.Column(
            "specimen_collected_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the specimen was collected from the patient",
        ),
        # FHIR interoperability
        sa.Column(
            "fhir_json",
            JSONB,
            nullable=True,
            comment="FHIR R4 ServiceRequest resource JSON",
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
    )

    # --- Step 2: Enable RLS on lab_orders ---
    op.execute("""
        -- Enable Row-Level Security on lab_orders table
        ALTER TABLE lab_orders ENABLE ROW LEVEL SECURITY;

        -- Force RLS for table owner too (prevents accidental bypass)
        ALTER TABLE lab_orders FORCE ROW LEVEL SECURITY;

        -- Policy: users can only see/modify lab orders for their tenant
        CREATE POLICY tenant_isolation_policy ON lab_orders
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # --- Step 3: Create lab_results table ---
    op.create_table(
        "lab_results",
        # Primary key
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique lab result identifier (UUID)",
        ),
        # Tenant isolation
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="Tenant UUID for RLS isolation",
        ),
        # Parent lab order reference
        sa.Column(
            "lab_order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lab_orders.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent lab order this result belongs to",
        ),
        # Result value — PHI
        sa.Column(
            "value",
            sa.String(100),
            nullable=False,
            comment="PHI: Result value as string",
        ),
        sa.Column(
            "numeric_value",
            sa.Float,
            nullable=True,
            comment="PHI: Parsed numeric value for range comparison",
        ),
        sa.Column(
            "unit",
            sa.String(50),
            nullable=False,
            comment="Unit of measurement (e.g., mg/dL, mmol/L)",
        ),
        # Reference range
        sa.Column(
            "reference_range_low",
            sa.Float,
            nullable=True,
            comment="Lower bound of normal reference range",
        ),
        sa.Column(
            "reference_range_high",
            sa.Float,
            nullable=True,
            comment="Upper bound of normal reference range",
        ),
        # Abnormality flag
        sa.Column(
            "is_abnormal",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="True if value falls outside reference range",
        ),
        # Result metadata
        sa.Column(
            "resulted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="When the result was produced by the lab",
        ),
        sa.Column(
            "resulted_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of the user who entered this result",
        ),
        # Measurement integration
        sa.Column(
            "measurement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("measurements.id", ondelete="SET NULL"),
            nullable=True,
            comment="Linked Measurement record for risk pipeline",
        ),
        # FHIR interoperability
        sa.Column(
            "fhir_json",
            JSONB,
            nullable=True,
            comment="FHIR R4 Observation resource JSON",
        ),
        # Timestamps (only created_at — results are immutable once recorded)
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
    )

    # --- Step 4: Enable RLS on lab_results ---
    op.execute("""
        -- Enable Row-Level Security on lab_results table
        ALTER TABLE lab_results ENABLE ROW LEVEL SECURITY;

        -- Force RLS for table owner too (prevents accidental bypass)
        ALTER TABLE lab_results FORCE ROW LEVEL SECURITY;

        -- Policy: users can only see/modify lab results for their tenant
        CREATE POLICY tenant_isolation_policy ON lab_results
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # --- Step 5: Create indexes for common query patterns ---
    op.execute("""
        -- Index: Patient lab history filtered by status
        -- Most common query: "show all pending/resulted labs for patient X"
        CREATE INDEX ix_lab_orders_tenant_patient_status
            ON lab_orders (tenant_id, patient_id, status);

        -- Index: Encounter-scoped lab lookups
        -- Used when viewing all labs ordered during a specific encounter
        CREATE INDEX ix_lab_orders_encounter
            ON lab_orders (encounter_id)
            WHERE encounter_id IS NOT NULL;

        -- Index: Lab queue dashboard — prioritized by urgency
        -- Lab technicians view: "show all ordered/in_progress labs, stat first"
        CREATE INDEX ix_lab_orders_tenant_status_priority
            ON lab_orders (tenant_id, status, priority);

        -- Index: Results for a specific lab order
        -- Used when viewing the results of a particular test
        CREATE INDEX ix_lab_results_order
            ON lab_results (lab_order_id);

        -- Index: Abnormal results dashboard
        -- Clinicians view: "show all abnormal results for my tenant"
        CREATE INDEX ix_lab_results_tenant_abnormal
            ON lab_results (tenant_id, is_abnormal)
            WHERE is_abnormal = true;
    """)


def downgrade() -> None:
    """
    Drop lab_results and lab_orders tables with their RLS policies.

    WARNING: This permanently deletes all lab order and result data.
    Only use in development — never in production (HIPAA retention).
    """
    # --- Drop lab_results first (depends on lab_orders via FK) ---
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON lab_results;"
    )
    op.execute("ALTER TABLE lab_results DISABLE ROW LEVEL SECURITY;")
    op.drop_table("lab_results")

    # --- Drop lab_orders ---
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON lab_orders;"
    )
    op.execute("ALTER TABLE lab_orders DISABLE ROW LEVEL SECURITY;")
    op.drop_table("lab_orders")
