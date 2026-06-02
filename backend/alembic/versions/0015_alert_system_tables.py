"""Alert system tables: alerts, alert_thresholds, escalation_records.

Revision ID: 0015_alert_system_tables
Revises: 0014_drug_interaction_tables
Create Date: 2026-06-01 00:00:00.000000

Creates three tenant-scoped tables for the alert and notification system:
- alerts: Clinical alert lifecycle records
- alert_thresholds: Configurable threshold rules (per-patient or tenant-wide)
- escalation_records: Immutable escalation audit trail

HIPAA: All tables are protected by PostgreSQL Row-Level Security (RLS)
       policies that enforce tenant isolation at the database layer.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision identifiers
revision = '0015_alert_system_tables'
down_revision = '0014_drug_interaction_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create alerts, alert_thresholds, and escalation_records tables with RLS."""

    # ------------------------------------------------------------------
    # TABLE: alerts
    # Stores clinical alert records with full lifecycle tracking.
    # ------------------------------------------------------------------
    op.create_table(
        'alerts',
        # Primary key — UUID avoids sequential enumeration attacks
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),

        # Tenant isolation — enforced at application layer and RLS at DB layer
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Patient reference — all clinical context scoped to this patient
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Alert classification
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),

        # Alert content — contains PHI; never written to logs
        sa.Column('message', sa.Text, nullable=False),

        # Structured clinical context (PHI) — risk scores, measurements, forecast info
        sa.Column('payload', postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),

        # Lifecycle state management
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('acknowledgment_notes', sa.Text, nullable=True),

        # Escalation tracking — 0=initial, 1=doctor, 2=clinic_admin
        sa.Column('escalation_level', sa.Integer, nullable=False, server_default='0'),
        sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),

        # Multi-channel dispatch tracking
        sa.Column(
            'channels_dispatched',
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="e.g. ['in_app', 'email', 'sms']",
        ),
        sa.Column(
            'dispatch_status',
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="e.g. {'email': 'sent', 'sms': 'failed_retry_2'}",
        ),

        # TenantMixin / Base standard timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    # Indexes for alerts table — ordered to match the models.py Index definitions
    op.create_index(
        'ix_alert_tenant_patient_status',
        'alerts',
        ['tenant_id', 'patient_id', 'status'],
    )
    op.create_index(
        'ix_alert_tenant_status_severity',
        'alerts',
        ['tenant_id', 'status', 'severity', sa.text('created_at DESC')],
    )

    # Enable Row-Level Security — enforce tenant isolation at database layer
    op.execute('ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE alerts FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON alerts
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # ------------------------------------------------------------------
    # TABLE: alert_thresholds
    # Per-patient or tenant-wide configurable threshold rules.
    # ------------------------------------------------------------------
    op.create_table(
        'alert_thresholds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),

        # NULL patient_id = tenant-wide default; non-NULL = patient-specific override
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=True),

        # What clinical dimension this threshold monitors
        sa.Column('measurement_type', sa.String(100), nullable=True),
        sa.Column('disease', sa.String(100), nullable=True),

        # Threshold condition: above, below, or enters_stratum
        sa.Column('condition', sa.String(30), nullable=False),
        sa.Column('threshold_value', sa.Float, nullable=True),
        sa.Column('target_stratum', sa.String(30), nullable=True),

        # Severity of alerts generated when this threshold fires
        sa.Column('severity', sa.String(20), nullable=False),

        # Soft-delete flag — deactivated instead of deleted to preserve history
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),

        # Ownership — clinician who configured this threshold
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),

        # Standard timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    op.create_index(
        'ix_threshold_tenant_patient_active',
        'alert_thresholds',
        ['tenant_id', 'patient_id', 'is_active'],
    )

    op.execute('ALTER TABLE alert_thresholds ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE alert_thresholds FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON alert_thresholds
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # ------------------------------------------------------------------
    # TABLE: escalation_records
    # Immutable audit trail of escalation events.
    # Never updated — only INSERT operations allowed after initial creation.
    # ------------------------------------------------------------------
    op.create_table(
        'escalation_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Reference to parent alert — not a FK constraint to allow soft-archiving
        sa.Column('alert_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Escalation transition: from which level to which level
        sa.Column('from_level', sa.Integer, nullable=False),
        sa.Column('to_level', sa.Integer, nullable=False),

        # Timestamp of escalation event — immutable after insert
        sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),

        # Who received the escalation — UUID only; name resolved at query time
        sa.Column('target_user_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Machine-readable reason for escalation
        sa.Column('reason', sa.String(100), nullable=False),

        # Standard timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    op.create_index(
        'ix_escalation_alert_id',
        'escalation_records',
        ['alert_id'],
    )

    op.execute('ALTER TABLE escalation_records ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE escalation_records FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON escalation_records
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Drop alert system tables and their associated RLS policies and indexes."""

    # Drop escalation_records — child of alerts; drop first to respect logical dependency
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON escalation_records;")
    op.drop_index('ix_escalation_alert_id', table_name='escalation_records')
    op.drop_table('escalation_records')

    # Drop alert_thresholds
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON alert_thresholds;")
    op.drop_index('ix_threshold_tenant_patient_active', table_name='alert_thresholds')
    op.drop_table('alert_thresholds')

    # Drop alerts — parent table; drop last
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON alerts;")
    op.drop_index('ix_alert_tenant_status_severity', table_name='alerts')
    op.drop_index('ix_alert_tenant_patient_status', table_name='alerts')
    op.drop_table('alerts')
