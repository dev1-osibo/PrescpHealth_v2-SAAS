"""Population analytics cache table: cached_population_metrics.

Revision ID: 0016_population_metrics_tables
Revises: 0015_alert_system_tables
Create Date: 2026-06-01 00:00:00.000000

Creates the cached_population_metrics table used by the Population Analytics
module (Task 16) to store pre-computed, tenant-scoped population metrics with
a configurable TTL.

HIPAA: The table contains only aggregate statistics (no individual PHI) and is
       protected by PostgreSQL Row-Level Security identical to the pattern used
       in migration 0015_alert_system_tables.py.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision identifiers
revision = '0016_population_metrics_tables'
down_revision = '0015_alert_system_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create cached_population_metrics table with RLS and lookup index."""

    # ------------------------------------------------------------------
    # TABLE: cached_population_metrics
    # Pre-computed population metrics with 1-hour TTL.
    # Keyed by (tenant_id, metric_type, disease, time_window).
    # ------------------------------------------------------------------
    op.create_table(
        'cached_population_metrics',

        # Primary key — UUID avoids sequential ID enumeration
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),

        # Tenant isolation — enforced at application layer and DB-level via RLS
        sa.Column(
            'tenant_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment='Tenant UUID for RLS isolation',
        ),

        # Composite cache key columns
        sa.Column(
            'metric_type',
            sa.String(50),
            nullable=False,
            comment="e.g. 'risk_distribution', 'watchlist_count', 'prevalence', 'avg_risk_score'",
        ),
        sa.Column(
            'disease',
            sa.String(50),
            nullable=True,
            comment='Disease filter; NULL means all diseases',
        ),
        sa.Column(
            'time_window',
            sa.String(10),
            nullable=True,
            comment="Rolling window code: '1m', '3m', '6m', '12m'; NULL for point-in-time metrics",
        ),

        # Computed payload — aggregate statistics only; no individual patient data
        sa.Column(
            'value',
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment='Serialised metric result (aggregate only — no PHI)',
        ),

        # Cache lifecycle timestamps
        sa.Column(
            'computed_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='When this metric value was computed (UTC)',
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=False,
            comment='Cache entry is stale after this timestamp (UTC)',
        ),

        # TenantMixin / Base standard timestamps
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

    # Covering index for cache-key lookups —
    # matches the composite key queried by PopulationService._load_cached()
    op.create_index(
        'ix_pop_metric_lookup',
        'cached_population_metrics',
        ['tenant_id', 'metric_type', 'disease', 'time_window'],
    )

    # Also index tenant_id alone (created by TenantMixin in ORM but done explicitly here)
    op.create_index(
        'ix_cached_population_metrics_tenant_id',
        'cached_population_metrics',
        ['tenant_id'],
    )

    # ------------------------------------------------------------------
    # Row-Level Security — same pattern as 0015_alert_system_tables.py
    # ------------------------------------------------------------------
    op.execute('ALTER TABLE cached_population_metrics ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE cached_population_metrics FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON cached_population_metrics
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Drop cached_population_metrics table, its RLS policy, and its indexes."""

    # Drop RLS policy first — must be removed before the table can be dropped
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON cached_population_metrics;"
    )

    # Drop indexes
    op.drop_index('ix_cached_population_metrics_tenant_id', table_name='cached_population_metrics')
    op.drop_index('ix_pop_metric_lookup', table_name='cached_population_metrics')

    # Drop table
    op.drop_table('cached_population_metrics')
