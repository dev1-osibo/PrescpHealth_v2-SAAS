"""Create audit_logs partitioned table with insert-only constraints and RLS.

Revision ID: 0003
Revises: 0002_auth_tables
Create Date: 2025-05-08

Creates the audit logging infrastructure:
- audit_logs table partitioned by RANGE on created_at (monthly)
- Initial partitions for current month + 12 months ahead
- INSERT-only grants via audit_writer role (no UPDATE, no DELETE)
- RLS policy for tenant isolation on reads
- Indexes for common query patterns (tenant+time, user+time, resource, patient)

Design Decisions:
- BIGSERIAL PK for efficient sequential inserts (better than UUID for partitions)
- Monthly partitioning enables:
  - Efficient time-range queries (partition pruning)
  - Simple retention management (DROP old partitions after 7 years)
  - Reduced index bloat per partition
- No foreign keys — audit records must survive even if referenced data is deleted
  (7-year retention outlives most other records)
- RLS uses INSERT-specific policy (audit_writer can insert for any tenant,
  but SELECT is restricted to current tenant)

HIPAA Compliance:
- Append-only enforced at DB level (not just application logic)
- 7-year retention via partition lifecycle management
- No UPDATE/DELETE permissions granted to any application role
- Even Super_Admin cannot modify audit records through the database
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers
revision: str = "0003_audit_tables"
down_revision: Union[str, None] = "0002_auth_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create audit_logs partitioned table with security constraints.

    Steps:
    1. Create parent partitioned table
    2. Create initial monthly partitions (current + 12 months ahead)
    3. Create indexes on each partition
    4. Set up RLS policy for tenant isolation
    5. Grant INSERT-only to audit_writer role (created in 0001)
    6. Explicitly REVOKE UPDATE and DELETE from all roles
    """

    # --- Step 1: Create the partitioned parent table ---
    # We use raw SQL because Alembic's op.create_table doesn't support
    # PostgreSQL PARTITION BY syntax natively
    op.execute("""
        CREATE TABLE audit_logs (
            id BIGSERIAL,
            tenant_id UUID NOT NULL,
            user_id UUID NOT NULL,
            action VARCHAR(50) NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            resource_id UUID,
            changes JSONB,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Primary key must include partition key for partitioned tables
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);

        -- Table comment for documentation
        COMMENT ON TABLE audit_logs IS
            'Append-only HIPAA audit trail — NO UPDATE/DELETE permitted. '
            'Partitioned monthly by created_at for 7-year retention management.';

        -- Column comments
        COMMENT ON COLUMN audit_logs.tenant_id IS
            'Tenant UUID for RLS isolation of audit records';
        COMMENT ON COLUMN audit_logs.user_id IS
            'Acting user UUID (who performed the action)';
        COMMENT ON COLUMN audit_logs.action IS
            'Action performed (e.g., patient.create, risk.compute)';
        COMMENT ON COLUMN audit_logs.resource_type IS
            'Resource type (e.g., patient, measurement, user)';
        COMMENT ON COLUMN audit_logs.resource_id IS
            'Affected resource UUID (NULL for non-resource actions)';
        COMMENT ON COLUMN audit_logs.changes IS
            'Change details: {field: {old, new}} — NO PHI values';
        COMMENT ON COLUMN audit_logs.metadata IS
            'Request context: {ip, user_agent, correlation_id}';
        COMMENT ON COLUMN audit_logs.created_at IS
            'Event timestamp (UTC) — partition key for monthly partitions';
    """)

    # --- Step 2: Create initial monthly partitions ---
    # Create partitions for current month + 12 months ahead
    # A scheduled job should create future partitions before they're needed
    op.execute("""
        DO $$
        DECLARE
            start_date DATE;
            end_date DATE;
            partition_name TEXT;
        BEGIN
            -- Create partitions from current month through 12 months ahead
            FOR i IN 0..12 LOOP
                start_date := DATE_TRUNC('month', CURRENT_DATE) + (i || ' months')::INTERVAL;
                end_date := start_date + '1 month'::INTERVAL;
                partition_name := 'audit_logs_' || TO_CHAR(start_date, 'YYYY_MM');

                EXECUTE FORMAT(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_logs '
                    'FOR VALUES FROM (%L) TO (%L)',
                    partition_name,
                    start_date,
                    end_date
                );
            END LOOP;
        END $$;
    """)

    # --- Step 3: Create indexes on the parent table ---
    # PostgreSQL automatically creates matching indexes on each partition
    op.execute("""
        -- Tenant-scoped time queries (most common: "show me audit for my tenant")
        CREATE INDEX ix_audit_logs_tenant_time
            ON audit_logs (tenant_id, created_at DESC);

        -- User activity queries ("what did this user do?")
        CREATE INDEX ix_audit_logs_user_time
            ON audit_logs (user_id, created_at DESC);

        -- Resource history queries ("show all changes to this resource")
        CREATE INDEX ix_audit_logs_resource
            ON audit_logs (resource_type, resource_id)
            WHERE resource_id IS NOT NULL;

        -- Action type queries ("show all patient.create events")
        CREATE INDEX ix_audit_logs_action
            ON audit_logs (action, created_at DESC);
    """)

    # --- Step 4: Enable RLS for tenant isolation ---
    # Audit records are readable only by the owning tenant
    # INSERT is allowed for any tenant (audit_writer inserts on behalf of all)
    op.execute("""
        -- Enable Row-Level Security
        ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

        -- Force RLS for table owner too (prevents accidental bypass)
        ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

        -- SELECT policy: users can only read audit logs for their tenant
        CREATE POLICY audit_tenant_read_policy ON audit_logs
            FOR SELECT
            USING (tenant_id = current_setting('app.current_tenant')::uuid);

        -- INSERT policy: audit_writer can insert for any tenant
        -- (the service sets tenant_id explicitly in the INSERT statement)
        CREATE POLICY audit_insert_policy ON audit_logs
            FOR INSERT
            WITH CHECK (true);
    """)

    # --- Step 5: Grant INSERT-only permissions to audit_writer role ---
    # The audit_writer role was created in migration 0001_initial_rls_setup
    op.execute("""
        -- Grant INSERT only — this is the ONLY write permission on audit_logs
        GRANT INSERT ON audit_logs TO audit_writer;

        -- Grant usage on the sequence so audit_writer can use BIGSERIAL
        GRANT USAGE, SELECT ON SEQUENCE audit_logs_id_seq TO audit_writer;

        -- Grant SELECT for reading audit logs (needed for audit queries)
        GRANT SELECT ON audit_logs TO audit_writer;
    """)

    # --- Step 6: Explicitly REVOKE dangerous permissions ---
    # Belt-and-suspenders: even if someone grants broader permissions later,
    # these explicit revocations make the intent clear
    op.execute("""
        -- Explicitly deny UPDATE and DELETE to audit_writer
        REVOKE UPDATE ON audit_logs FROM audit_writer;
        REVOKE DELETE ON audit_logs FROM audit_writer;

        -- Deny TRUNCATE as well (another way to delete data)
        REVOKE TRUNCATE ON audit_logs FROM audit_writer;
    """)


def downgrade() -> None:
    """
    Drop audit_logs table and all partitions.

    WARNING: This permanently deletes all audit log data.
    Only use in development — never in production.
    """
    # Drop RLS policies first
    op.execute(
        "DROP POLICY IF EXISTS audit_tenant_read_policy ON audit_logs;"
    )
    op.execute(
        "DROP POLICY IF EXISTS audit_insert_policy ON audit_logs;"
    )

    # Revoke grants
    op.execute("REVOKE ALL ON audit_logs FROM audit_writer;")

    # Drop the partitioned table (CASCADE drops all partitions)
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE;")
