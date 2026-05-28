"""Add missing updated_at column to dispensings table.

Revision ID: 0010_fix_dispensings_updated_at
Revises: 0009_lab_order_tables
Create Date: 2025-06-20

The Dispensing model inherits from TimestampMixin which provides both
created_at and updated_at columns. However, migration 0008 only created
the created_at column on the dispensings table, omitting updated_at.

This migration adds the missing column to bring the schema in sync
with the SQLAlchemy model definition.

Safety:
- Additive change only (ADD COLUMN) — no data loss risk
- DEFAULT NOW() ensures existing rows get a valid timestamp
- NOT NULL constraint safe because DEFAULT fills all existing rows
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision: str = "0010_fix_dispensings_updated_at"
down_revision: Union[str, None] = "0009_lab_order_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the missing updated_at column to dispensings table."""
    op.add_column(
        "dispensings",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Last modification timestamp (UTC)",
        ),
    )


def downgrade() -> None:
    """Remove the updated_at column from dispensings table."""
    op.drop_column("dispensings", "updated_at")
