"""
PrescpHealth Backend — AI Assistant SQLAlchemy Models.

Defines database models for:
- Conversation: Chat session between clinician, patient, and AI
- Message: Individual messages in a conversation

Design Principles:
    - One conversation per patient per clinician (but allow multiple parallel convos)
    - All messages (user, assistant) in same table with role field
    - Track tokens used for cost/quota monitoring
    - Model used recorded for audit/debugging

RLS and Tenant Isolation:
    - Conversation uses TenantMixin (RLS on tenant_id)
    - Message uses TenantMixin (RLS on tenant_id)

HIPAA Compliance:
    - Message content is PHI (clinical discussion) — never log raw content
    - Track message count for audit, but not message text in logs
    - All conversations stored encrypted at rest
    - Audit trail via AuditService

Indexes:
    - (patient_id, last_message_at DESC) on conversations for quick lookup
    - (conversation_id, created_at) on messages for conversation history
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    Integer,
    Boolean,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin


class Conversation(TenantMixin, Base):
    """
    Chat conversation session between clinician, patient, and AI.

    Tracks conversation metadata (when started, who's involved, message count).
    Actual messages stored in Message table.

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        patient_id: Patient UUID (FK to patients table)
        clinician_id: Which clinician initiated conversation
        started_at: When conversation started
        last_message_at: When last message was sent (for sorting)
        message_count: Running count of messages (clinician + AI)
        is_active: true if conversation is ongoing, false if archived/closed
        created_at, updated_at: From TenantMixin

    Design Note:
        - One row per conversation (clinician may have multiple convos with same patient over time)
        - is_active flag allows archiving without deleting
        - message_count tracks engagement level
        - last_message_at enables "recent convos first" UI sorting
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Conversation UUID",
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient UUID",
    )

    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Clinician UUID (user.id)",
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When conversation started",
    )

    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When last message was sent (for UI sorting)",
    )

    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Running count of messages (clinician + AI)",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
        comment="true if ongoing, false if archived/closed",
    )

    __table_args__ = (
        Index("ix_conversation_patient_last_message", "patient_id", last_message_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<Conversation patient={self.patient_id} clinician={self.clinician_id} active={self.is_active}>"


class Message(TenantMixin, Base):
    """
    Individual message in a conversation.

    Stores message text, role (user/assistant), and metadata (tokens, model used).

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        conversation_id: FK to conversations table
        role: "user" (clinician's question) or "assistant" (AI response)
        content: PHI: The message text (clinical discussion)
        model_used: Which LLM generated response (e.g., "gpt-4o", "claude", "ollama")
        tokens_used: Token count (for cost tracking)
        created_at, updated_at: From TenantMixin

    Design Note:
        - role field distinguishes clinician message from AI response
        - content is PHI (clinical context, medical questions)
        - model_used recorded for debugging/auditing (which AI generated response)
        - tokens_used enables cost monitoring per model
        - Immutable (no updates to message content)
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Message UUID",
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to conversation",
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'user' (clinician) or 'assistant' (AI)",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="PHI: The message text (clinical discussion)",
    )

    model_used: Mapped[str] = mapped_column(
        String(50),
        nullable=True,
        comment="LLM used (e.g., 'gpt-4o', 'claude-opus', 'ollama-mistral'). Null for user messages.",
    )

    tokens_used: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        comment="Token count (for cost tracking). Null for user messages.",
    )

    __table_args__ = (
        Index("ix_message_conversation_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message conversation={self.conversation_id} role={self.role} tokens={self.tokens_used}>"
