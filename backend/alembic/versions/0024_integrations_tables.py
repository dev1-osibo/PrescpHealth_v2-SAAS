"""
Alembic Migration 0024 — Integrations Tables
=============================================
Creates:
  - connector_configs   — External system connection settings
  - sync_logs           — Per-run sync audit records

Security:
  connector_configs.credentials JSONB stores sensitive auth data.
  In production, this column would use pgcrypto or application-level
  encryption before storage. Never SELECT this column for logging.

HIPAA NOTE:
  sync_logs.error_summary contains NO PHI — only operational metadata.
  connector_configs.base_url is not logged (may expose internal network).

down_revision: 0023_bed_management_tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0024_integrations_tables"
down_revision = "0023_bed_management_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create integration tables with RLS and indexes."""

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    connector_type = postgresql.ENUM(
        "openmrs", "dhis2", "generic_fhir",
        name="connectortype", create_type=True,
    )
    auth_type = postgresql.ENUM(
        "basic", "oauth2", "api_key",
        name="authtype", create_type=True,
    )
    sync_direction = postgresql.ENUM(
        "inbound", "outbound", "bidirectional",
        name="syncdirection", create_type=True,
    )
    sync_status = postgresql.ENUM(
        "started", "completed", "failed", "partial",
        name="syncstatus", create_type=True,
    )

    for enum in (connector_type, auth_type, sync_direction, sync_status):
        enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # connector_configs table
    # ------------------------------------------------------------------
    op.create_table(
        "connector_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_type",
                  sa.Enum("openmrs","dhis2","generic_fhir", name="connectortype"),
                  nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        # base_url: not logged — may reveal internal network topology
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("auth_type",
                  sa.Enum("basic","oauth2","api_key", name="authtype"),
                  nullable=False),
        # CRITICAL: credentials is encrypted at rest in production
        # NEVER SELECT this column in logging/monitoring queries
        sa.Column("credentials", postgresql.JSONB, nullable=False, server_default="{}",
                  comment="ENCRYPTED auth credentials — NEVER LOG"),
        sa.Column("sync_direction",
                  sa.Enum("inbound","outbound","bidirectional", name="syncdirection"),
                  nullable=False),
        # cron schedule string (e.g., "0 2 * * *")
        sa.Column("sync_schedule", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_connector_configs_tenant", "connector_configs", ["tenant_id"])
    op.create_index("ix_connector_configs_type", "connector_configs",
                    ["tenant_id", "connector_type"])

    op.execute("ALTER TABLE connector_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE connector_configs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON connector_configs
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )

    # ------------------------------------------------------------------
    # sync_logs table — NO PHI in any column
    # ------------------------------------------------------------------
    op.create_table(
        "sync_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("connector_configs.id"), nullable=False),
        sa.Column("direction",
                  sa.Enum("inbound","outbound","bidirectional", name="syncdirection"),
                  nullable=False),
        sa.Column("status",
                  sa.Enum("started","completed","failed","partial", name="syncstatus"),
                  nullable=False, server_default="started"),
        sa.Column("records_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_succeeded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer, nullable=False, server_default="0"),
        # error_summary: operational metadata only — NO PHI
        sa.Column("error_summary", sa.Text, nullable=True,
                  comment="Operational error metadata — NO PHI"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sync_logs_connector", "sync_logs", ["connector_id"])
    op.create_index("ix_sync_logs_tenant", "sync_logs", ["tenant_id"])
    op.create_index("ix_sync_logs_started_at", "sync_logs", ["started_at"])

    op.execute("ALTER TABLE sync_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE sync_logs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation_policy ON sync_logs
           USING (tenant_id = current_setting('app.current_tenant')::uuid)
           WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);"""
    )


def downgrade() -> None:
    """Drop integrations tables and enum types."""
    for table in ("sync_logs", "connector_configs"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")

    op.drop_index("ix_sync_logs_started_at", table_name="sync_logs")
    op.drop_index("ix_sync_logs_tenant", table_name="sync_logs")
    op.drop_index("ix_sync_logs_connector", table_name="sync_logs")
    op.drop_table("sync_logs")

    op.drop_index("ix_connector_configs_type", table_name="connector_configs")
    op.drop_index("ix_connector_configs_tenant", table_name="connector_configs")
    op.drop_table("connector_configs")

    op.execute("DROP TYPE IF EXISTS syncstatus;")
    op.execute("DROP TYPE IF EXISTS syncdirection;")
    op.execute("DROP TYPE IF EXISTS authtype;")
    op.execute("DROP TYPE IF EXISTS connectortype;")
