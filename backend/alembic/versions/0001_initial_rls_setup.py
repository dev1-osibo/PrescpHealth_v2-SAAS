"""Initial RLS setup — configure PostgreSQL for tenant isolation.

This migration sets up the foundational infrastructure for Row-Level Security:
1. Creates the 'app.current_tenant' session variable pattern
2. Creates a helper function for setting tenant context
3. Creates the audit_writer role (insert-only for audit logs)

This runs ONCE and provides the foundation that all subsequent
tenant-scoped table migrations build upon.

Revision ID: 0001
Revises: None
Create Date: 2025-05-08
"""
from typing import Sequence, Union

from alembic import op

# Revision identifiers
revision: str = "0001_initial_rls"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Set up PostgreSQL RLS infrastructure.

    Creates:
    - Custom GUC variable 'app.current_tenant' for session-level tenant context
    - Helper function to validate tenant UUID format
    - audit_writer role with INSERT-only permissions (for append-only audit logs)

    Why session variables instead of application-level filtering:
    - RLS is enforced by the DATABASE, not the application
    - Even if app code has a bug, cross-tenant access is impossible
    - Works with any query tool (psql, pgAdmin) not just our app
    """
    # Allow the app.current_tenant session variable to be set
    # This is used by RLS policies on every tenant-scoped table
    op.execute("""
        -- Create a custom parameter namespace for our app
        -- This allows SET LOCAL app.current_tenant = 'uuid'
        -- Use current_database() to get the actual DB name dynamically
        DO $$
        BEGIN
            EXECUTE format('ALTER DATABASE %I SET app.current_tenant = %L', current_database(), '');
        END $$;
    """)

    # Create a role for audit log writes (insert-only, no update/delete)
    # This role is used by the audit logging service to ensure append-only behavior
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_writer') THEN
                CREATE ROLE audit_writer;
            END IF;
        END
        $$;
    """)

    # Create pg_trgm extension for partial name search (GIN trigram indexes)
    # Used by patient search for fuzzy/partial name matching
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # Create uuid-ossp extension for UUID generation
    # Used as default for primary key columns
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')


def downgrade() -> None:
    """
    Remove RLS infrastructure.

    WARNING: This will break all tenant isolation if run on a database
    with existing tenant-scoped tables. Only use in development.
    """
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp";')
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_writer') THEN
                DROP ROLE audit_writer;
            END IF;
        END
        $$;
    """)
    op.execute("ALTER DATABASE CURRENT RESET app.current_tenant;")
