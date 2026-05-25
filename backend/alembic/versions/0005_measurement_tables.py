"""Create measurements table with RLS, indexes, and idempotency constraint.

Revision ID: 0005
Revises: 0004_patient_tables
Create Date: 2025-05-08

Creates the clinical measurement storage table:
- measurements: Individual clinical data points (vital signs, lab results,
  lifestyle factors) recorded for patients over time.

Design Decisions:
- Float for value (sufficient precision for all clinical measurement types)
- recorded_at is when the measurement was taken, not when it was entered
- source tracks provenance (manual, device, import, patient_portal)
- is_validated gates inclusion in risk computation (Patient_User entries
  must be validated by a clinician before affecting risk scores)
- is_flagged marks deviations from patient baseline (>2σ)
- Idempotency via unique constraint on (patient_id, measurement_type,
  recorded_at, value) — prevents duplicate entries from retries or re-imports

Indexes:
- (patient_id, measurement_type, recorded_at DESC): Time-series queries
  for charting and ML feature extraction
- (tenant_id, patient_id): Tenant-scoped patient lookups
- Partial index on is_validated = FALSE: Pending validation queue
- Partial index on is_flagged = TRUE: Flagged measurements dashboard

HIPAA Compliance:
- RLS enforces tenant isolation at database level
- Measurement values are PHI — encrypted at rest via TDE
- No hard delete — records retained for 7+ years
- Audit trail via MeasurementSaved domain events
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# Revision identifiers
revision: str = "0005_measurement_tables"
down_revision: Union[str, None] = "0004_patient_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create measurements table with RLS policies and indexes.

    Steps:
    1. Create measurements table with all columns and constraints
    2. Enable RLS for tenant isolation
    3. Create indexes for common query patterns
    """

    # --- Step 1: Create measurements table ---
    op.create_table(
        "measurements",
        # Primary key — UUID
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique measurement identifier (UUID)",
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
            comment="Patient this measurement belongs to",
        ),
        # Measurement data — PHI
        sa.Column(
            "measurement_type",
            sa.String(50),
            nullable=False,
            comment="Type key (e.g., systolic_bp, hba1c, bmi)",
        ),
        sa.Column(
            "value",
            sa.Float,
            nullable=False,
            comment="PHI: Numeric measurement value (validated against physiological range)",
        ),
        sa.Column(
            "unit",
            sa.String(20),
            nullable=False,
            comment="Unit of measurement (e.g., mmHg, mg/dL, kg, %)",
        ),
        # Temporal context
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="When the measurement was taken (not when entered into system)",
        ),
        # Provenance
        sa.Column(
            "recorded_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of the user who recorded/submitted this measurement",
        ),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            comment="Data source: manual, device, import, patient_portal",
        ),
        # Validation status
        sa.Column(
            "is_validated",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether a clinician has validated this measurement",
        ),
        sa.Column(
            "validated_by",
            UUID(as_uuid=True),
            nullable=True,
            comment="UUID of the clinician who validated this measurement",
        ),
        sa.Column(
            "validated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when the measurement was validated",
        ),
        # Deviation flagging
        sa.Column(
            "is_flagged",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="True if value deviates >2σ from patient baseline",
        ),
        sa.Column(
            "flag_reason",
            sa.String(500),
            nullable=True,
            comment="Explanation of why this measurement was flagged",
        ),
        # Clinical notes — PHI
        sa.Column(
            "notes",
            sa.Text,
            nullable=True,
            comment="PHI: Optional clinician notes (encrypted at rest)",
        ),
        # Timestamps (from TenantMixin pattern)
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
        # Idempotency constraint: same patient, same type, same time, same value
        # Prevents duplicate entries from retries or bulk import re-runs
        sa.UniqueConstraint(
            "patient_id",
            "measurement_type",
            "recorded_at",
            "value",
            name="uq_measurement_idempotency",
        ),
    )

    # --- Step 2: Enable RLS for tenant isolation ---
    op.execute("""
        -- Enable Row-Level Security on measurements table
        ALTER TABLE measurements ENABLE ROW LEVEL SECURITY;

        -- Force RLS for table owner too (prevents accidental bypass)
        ALTER TABLE measurements FORCE ROW LEVEL SECURITY;

        -- Policy: users can only see/modify measurements for their tenant
        CREATE POLICY tenant_isolation_policy ON measurements
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # --- Step 3: Create indexes for common query patterns ---
    op.execute("""
        -- Index: Time-series queries for charting and ML feature extraction
        -- Most common query: "get all systolic_bp readings for patient X, newest first"
        -- Ordered by recorded_at DESC for efficient "latest N" queries
        CREATE INDEX ix_measurements_patient_type_time
            ON measurements (patient_id, measurement_type, recorded_at DESC);

        -- Index: Tenant-scoped patient lookups
        -- Used when listing all measurements for a patient within a tenant
        CREATE INDEX ix_measurements_tenant_patient
            ON measurements (tenant_id, patient_id);

        -- Partial index: Pending validations (is_validated = FALSE)
        -- Clinicians need a queue of Patient_User submissions awaiting review
        -- Partial index is small because most measurements are validated
        CREATE INDEX ix_measurements_pending_validation
            ON measurements (tenant_id, patient_id, created_at DESC)
            WHERE is_validated = false;

        -- Partial index: Flagged measurements (is_flagged = TRUE)
        -- Dashboard showing measurements that deviated from baseline
        -- Partial index is small because most measurements are not flagged
        CREATE INDEX ix_measurements_flagged
            ON measurements (tenant_id, patient_id, recorded_at DESC)
            WHERE is_flagged = true;
    """)


def downgrade() -> None:
    """
    Drop measurements table and associated RLS policies.

    WARNING: This permanently deletes all measurement data.
    Only use in development — never in production.
    """
    # Drop RLS policy
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON measurements;"
    )

    # Disable RLS
    op.execute("ALTER TABLE measurements DISABLE ROW LEVEL SECURITY;")

    # Drop the table (indexes and constraints dropped automatically)
    op.drop_table("measurements")
