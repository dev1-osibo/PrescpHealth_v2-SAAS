"""Create patients and patient_versions tables with RLS and indexes.

Revision ID: 0004
Revises: 0003_audit_tables
Create Date: 2025-05-08

Creates the patient profile management tables:
- patients: Core patient records with demographics, medical history, status
- patient_versions: Immutable version history for all profile changes

Both tables have:
- RLS policies for tenant isolation
- Comprehensive indexes for common query patterns
- Soft delete support (deleted_at column on patients)

Design Decisions:
- medical_record_number is unique per tenant (not globally)
- JSONB for flexible structured data (allergies, conditions, medications)
- Separate version table (not SCD Type 2) for cleaner queries and snapshots
- Partial index on deleted_at IS NULL for efficient active-patient queries
- Composite indexes ordered by selectivity (tenant_id first for RLS)

HIPAA Compliance:
- Soft delete only — deleted_at marks logical deletion, data retained 7+ years
- PHI fields documented in column comments for encryption awareness
- RLS enforces tenant isolation at database level
- Version history provides complete audit trail of all changes
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers
revision: str = "0004_patient_tables"
down_revision: Union[str, None] = "0003_audit_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create patients and patient_versions tables with RLS policies.

    Steps:
    1. Create patients table with all columns and constraints
    2. Create patient_versions table
    3. Enable RLS on both tables
    4. Create indexes for common query patterns
    """

    # --- Step 1: Create patients table ---
    op.create_table(
        "patients",
        # Primary key — immutable UUID
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable patient identifier (UUID, assigned at creation)",
        ),
        # Tenant isolation
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),
        # Clinic-assigned identifier
        sa.Column(
            "medical_record_number",
            sa.String(100),
            nullable=False,
            comment="Clinic-assigned MRN — unique per tenant",
        ),
        # Demographics — PHI
        sa.Column(
            "first_name",
            sa.String(255),
            nullable=False,
            comment="PHI: Patient first name (encrypted at rest)",
        ),
        sa.Column(
            "last_name",
            sa.String(255),
            nullable=False,
            comment="PHI: Patient last name (encrypted at rest)",
        ),
        sa.Column(
            "date_of_birth",
            sa.Date,
            nullable=False,
            comment="PHI: Patient date of birth",
        ),
        sa.Column(
            "gender",
            sa.String(20),
            nullable=False,
            comment="Patient gender (Male, Female, Other, Prefer_Not_To_Say)",
        ),
        # Contact — PHI (optional)
        sa.Column(
            "phone_number",
            sa.String(50),
            nullable=True,
            comment="PHI: Patient phone number (encrypted at rest)",
        ),
        sa.Column(
            "email",
            sa.String(255),
            nullable=True,
            comment="PHI: Patient email address (encrypted at rest)",
        ),
        sa.Column(
            "address",
            JSONB,
            nullable=True,
            comment="PHI: Structured address {street, city, state, country, postal_code}",
        ),
        sa.Column(
            "emergency_contact",
            JSONB,
            nullable=True,
            comment="Emergency contact {name, phone, relationship}",
        ),
        # Medical information
        sa.Column(
            "blood_type",
            sa.String(10),
            nullable=True,
            comment="Blood type (e.g., A+, O-, AB+)",
        ),
        sa.Column(
            "allergies",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="List of allergy strings",
        ),
        sa.Column(
            "chronic_conditions",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="List of ICD-10 coded conditions [{code, display_name}]",
        ),
        sa.Column(
            "current_medications",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Active medications [{name, dosage, frequency, start_date}]",
        ),
        sa.Column(
            "insurance_info",
            JSONB,
            nullable=True,
            comment="Insurance details {provider, policy_number, group_number}",
        ),
        # Clinical notes — PHI
        sa.Column(
            "notes",
            sa.Text,
            nullable=True,
            comment="PHI: Free-text clinician notes (encrypted at rest)",
        ),
        # Status
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="Active",
            comment="Patient lifecycle status (Active, Inactive, Deceased, Transferred)",
        ),
        # Ownership
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of the user who created this patient record",
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
        # Soft delete
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete timestamp (NULL = active, set = logically deleted)",
        ),
        # Constraints
        sa.UniqueConstraint(
            "tenant_id",
            "medical_record_number",
            name="uq_patient_tenant_mrn",
        ),
    )

    # --- Step 2: Create patient_versions table ---
    op.create_table(
        "patient_versions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Version record identifier",
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            comment="Patient this version belongs to",
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),
        sa.Column(
            "version_number",
            sa.Integer,
            nullable=False,
            comment="Sequential version number per patient (1, 2, 3, ...)",
        ),
        sa.Column(
            "changed_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of the user who made this change",
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Timestamp when this change was made (UTC)",
        ),
        sa.Column(
            "change_type",
            sa.String(20),
            nullable=False,
            comment="Type of change: create, update, soft_delete, restore",
        ),
        sa.Column(
            "changes",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Change diff: {field_name: {old: value, new: value}}",
        ),
        sa.Column(
            "snapshot",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Full patient state at this version (point-in-time recovery)",
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
    )

    # --- Step 3: Enable RLS on both tables ---
    op.execute("""
        -- RLS on patients table
        ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
        ALTER TABLE patients FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON patients
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);

        -- RLS on patient_versions table
        ALTER TABLE patient_versions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE patient_versions FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON patient_versions
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # --- Step 4: Create indexes for common query patterns ---
    op.execute("""
        -- Index: Search patients by last name within a tenant
        -- Supports partial name search (LIKE 'Smith%') efficiently
        CREATE INDEX ix_patients_tenant_last_name
            ON patients (tenant_id, last_name);

        -- Index: Lookup by medical record number within a tenant
        -- Covered by unique constraint but explicit for clarity
        CREATE INDEX ix_patients_tenant_mrn
            ON patients (tenant_id, medical_record_number);

        -- Index: Filter patients by status within a tenant
        -- Common query: "show me all active patients"
        CREATE INDEX ix_patients_tenant_status
            ON patients (tenant_id, status);

        -- Index: Sort patients by creation date within a tenant (newest first)
        -- Used for "recently added patients" views
        CREATE INDEX ix_patients_tenant_created_at
            ON patients (tenant_id, created_at DESC);

        -- Partial index: Active patients only (deleted_at IS NULL)
        -- Most queries filter out soft-deleted records, this makes it fast
        CREATE INDEX ix_patients_active
            ON patients (tenant_id, id)
            WHERE deleted_at IS NULL;

        -- Index: Version history lookup by patient (ordered by version)
        CREATE INDEX ix_patient_versions_patient_version
            ON patient_versions (patient_id, version_number DESC);
    """)


def downgrade() -> None:
    """
    Drop patients and patient_versions tables.

    WARNING: This permanently deletes all patient data.
    Only use in development — never in production.
    """
    # Drop RLS policies
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON patient_versions;"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON patients;"
    )

    # Disable RLS
    op.execute("ALTER TABLE patient_versions DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE patients DISABLE ROW LEVEL SECURITY;")

    # Drop tables (patient_versions first due to FK dependency)
    op.drop_table("patient_versions")
    op.drop_table("patients")
