"""Background tasks table for async job tracking.

Revision ID: 0017_background_tasks_table
Revises: 0016_population_metrics_tables
Create Date: 2026-06-01 00:00:00.000000

Creates the ``background_tasks`` table with full tenant-scoped RLS.
This table tracks the lifecycle and results of all asynchronous
background jobs (Celery tasks, report generation, batch processing).

HIPAA: The table is protected by PostgreSQL Row-Level Security (RLS)
       policies that enforce tenant isolation at the database layer.
       Params and result columns may contain PHI — never log their content.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision identifiers
revision = '0017_background_tasks_table'
down_revision = '0016_population_metrics_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create background_tasks table with index and RLS policy."""

    op.create_table(
        'background_tasks',

        # Primary key — UUID avoids sequential enumeration
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            comment="Unique task identifier (UUID4)",
        ),

        # Tenant isolation — enforced at application layer and RLS at DB layer
        sa.Column(
            'tenant_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),

        # Task classification
        sa.Column(
            'task_type',
            sa.String(50),
            nullable=False,
            comment="Logical task category (e.g. 'risk_score_batch')",
        ),

        # Lifecycle state
        sa.Column(
            'status',
            sa.String(20),
            nullable=False,
            server_default='pending',
            comment="One of: pending, running, completed, failed, retrying",
        ),

        # Input parameters — may contain PHI; never log
        sa.Column(
            'params',
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Task input parameters (may contain PHI — do not log)",
        ),

        # Output payload — may contain PHI; never log
        sa.Column(
            'result',
            postgresql.JSONB,
            nullable=True,
            comment="Task output/result payload (may contain PHI — do not log)",
        ),

        # Error details (must not contain PHI)
        sa.Column(
            'error',
            sa.Text,
            nullable=True,
            comment="Last error message (no PHI)",
        ),

        # Retry tracking
        sa.Column(
            'retry_count',
            sa.Integer,
            nullable=False,
            server_default='0',
            comment="Number of retry attempts so far",
        ),
        sa.Column(
            'max_retries',
            sa.Integer,
            nullable=False,
            server_default='3',
            comment="Maximum allowed retry attempts",
        ),

        # Celery integration
        sa.Column(
            'celery_task_id',
            sa.String(200),
            nullable=True,
            comment="Celery task UUID for broker-level status polling",
        ),

        # Timing
        sa.Column(
            'started_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When task execution began",
        ),
        sa.Column(
            'completed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When task finished (completed or permanently failed)",
        ),

        # Standard TenantMixin timestamps
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
    )

    # Composite index for tenant-scoped status queries and dashboard polling
    op.create_index(
        'ix_bg_task_tenant_status',
        'background_tasks',
        ['tenant_id', 'status', 'created_at'],
    )

    # ------------------------------------------------------------------
    # Row-Level Security — enforce tenant isolation at database layer
    # Even if application code omits a tenant filter, the DB blocks access.
    # ------------------------------------------------------------------
    op.execute('ALTER TABLE background_tasks ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE background_tasks FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON background_tasks
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Drop background_tasks table, index, and RLS policy."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON background_tasks;")
    op.drop_index('ix_bg_task_tenant_status', table_name='background_tasks')
    op.drop_table('background_tasks')
