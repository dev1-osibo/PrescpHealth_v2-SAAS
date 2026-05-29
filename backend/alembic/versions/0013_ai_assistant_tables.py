"""AI assistant tables: conversations, messages.

Revision ID: 0013_ai_assistant_tables
Revises: 0012_forecast_engine_tables
Create Date: 2026-05-28 21:00:00.000000

This migration creates the database tables for the AI Assistant module:

1. conversations (tenant-scoped)
   - Chat session between clinician, patient, and AI
   - Tracks conversation metadata (participants, message count, active status)
   - One row per conversation (but multiple conversations per patient over time)

2. messages (tenant-scoped)
   - Individual messages in a conversation
   - Stores message text, role (user/assistant), and model metadata
   - Immutable records (audit trail)

RLS Policies:
    - conversations: tenant_id isolation
    - messages: tenant_id isolation

HIPAA Compliance:
    - Message content is PHI (clinical discussion)
    - Both tables encrypted at rest (TDE or column-level encryption)
    - Append-only audit trail (no updates/deletes)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0013_ai_assistant_tables'
down_revision = '0012_forecast_engine_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create conversations, messages tables."""

    # =========================================================================
    # 1. Create conversations table (tenant-scoped)
    # =========================================================================
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Tenant UUID for RLS'),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Patient UUID'),
        sa.Column('clinician_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Clinician (user) UUID'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When started'),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When last message sent'),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0', comment='Running message count'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='true if ongoing, false if archived'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clinician_id'], ['users.id'], ondelete='RESTRICT'),
    )

    # Index for "recent conversations first" UI sorting
    op.create_index('ix_conversation_patient_last_message', 'conversations', ['patient_id', sa.desc('last_message_at')])

    # Enable RLS on conversations
    op.execute("""
        ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON conversations
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # =========================================================================
    # 2. Create messages table (tenant-scoped)
    # =========================================================================
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Tenant UUID for RLS'),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference to conversation'),
        sa.Column('role', sa.String(20), nullable=False, comment="'user' or 'assistant'"),
        sa.Column('content', sa.Text(), nullable=False, comment='PHI: Message text (clinical discussion)'),
        sa.Column('model_used', sa.String(50), nullable=True, comment="LLM used (e.g., 'gpt-4o'). Null for user messages."),
        sa.Column('tokens_used', sa.Integer(), nullable=True, comment='Token count for cost tracking'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    )

    # Index for conversation history (most recent first)
    op.create_index('ix_message_conversation_created', 'messages', ['conversation_id', sa.desc('created_at')])

    # Enable RLS on messages
    op.execute("""
        ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON messages
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Reverse migration: drop tables."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON messages;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON conversations;")
    op.drop_table('messages')
    op.drop_table('conversations')
