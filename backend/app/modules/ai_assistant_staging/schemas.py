"""
PrescpHealth Backend — AI Assistant Pydantic Schemas.

Request/response models for AI assistant endpoints.
"""

from datetime import datetime
from typing import Optional, List
import uuid

from pydantic import BaseModel, Field


# ============================================================================
# Request Models
# ============================================================================

class SendMessageRequest(BaseModel):
    """Request to send a clinical message to AI."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Clinical question or message"
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Existing conversation UUID (new if not provided)"
    )


# ============================================================================
# Response Models
# ============================================================================

class MessageResponse(BaseModel):
    """Single message in conversation."""

    id: str = Field(..., description="Message UUID")
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="PHI: Message text")
    model_used: Optional[str] = Field(None, description="LLM used (e.g., 'gpt-4o')")
    tokens_used: Optional[int] = Field(None, description="Token count")
    created_at: str = Field(..., description="ISO timestamp")


class ConversationResponse(BaseModel):
    """Conversation metadata."""

    id: str = Field(..., description="Conversation UUID")
    patient_id: str = Field(..., description="Patient UUID")
    clinician_id: str = Field(..., description="Clinician UUID")
    message_count: int = Field(..., description="Total messages in conversation")
    is_active: bool = Field(..., description="true if ongoing")
    last_message_at: str = Field(..., description="ISO timestamp of last message")


class ChatResponse(BaseModel):
    """Response to send_message endpoint."""

    success: bool = Field(True, description="Always true on success")
    data: dict = Field(
        ...,
        description="{conversation_id, message_id, response, tokens_used, model_used}"
    )
    meta: dict = Field(
        default_factory=dict,
        description="Metadata {request_id, timestamp, ...}"
    )


class HistoryResponse(BaseModel):
    """Response to get_history endpoint."""

    success: bool = Field(True, description="Always true")
    data: List[MessageResponse] = Field(
        ...,
        description="List of messages (most recent first)"
    )
    meta: dict = Field(
        default_factory=dict,
        description="Metadata {request_id, timestamp, pagination, ...}"
    )


# ============================================================================
# Standard Envelope (used by router)
# ============================================================================

class StandardResponse(BaseModel):
    """Standard response envelope for all API endpoints."""

    success: bool = Field(..., description="true for 2xx, false for errors")
    data: Optional[dict] = Field(None, description="Response payload")
    meta: dict = Field(
        default_factory=dict,
        description="Metadata {request_id, timestamp, ...}"
    )
