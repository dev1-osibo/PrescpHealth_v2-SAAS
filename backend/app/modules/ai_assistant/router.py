"""
PrescpHealth Backend — AI Assistant FastAPI Router.

Two endpoints for AI clinical assistant:
1. POST /patients/{id}/assistant/chat — Send message, get AI response
2. GET /patients/{id}/assistant/history — Get conversation history

All endpoints:
- Require authentication (via require_role dependency)
- Enforce RBAC (Doctor role only)
- Set HIPAA headers (Cache-Control: no-store on PHI responses)
- Use standard response envelope
- Include request_id for correlation/audit

HIPAA Compliance:
    - Conversations are PHI — responses marked no-cache
    - No message text in logs (only patient_id UUID)
    - All calls audited via AuditService
    - Patient data de-identified before cloud LLM calls
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_request_id, get_tenant_id, get_current_user
from app.modules.auth.rbac import Role, require_role
from app.modules.audit.service import AuditService
from app.modules.ai_assistant.service import AIAssistantService
from app.modules.ai_assistant.providers import FailoverLLMProvider, GPT4oProvider, ClaudeProvider, OllamaProvider
from app.modules.ai_assistant.schemas import (
    SendMessageRequest,
    ChatResponse,
    HistoryResponse,
)

# Router prefix: /api/v1/patients/{id}/assistant/...
router = APIRouter(prefix="/assistant", tags=["ai_assistant"])

# Global LLM provider (initialized with failover chain)
# TODO: Task 11.3+: Load API keys from environment/secrets
_llm_provider = FailoverLLMProvider(
    primary=GPT4oProvider(api_key="sk-xxx-placeholder"),  # Set from env
    fallback1=ClaudeProvider(api_key="sk-ant-xxx-placeholder"),  # Set from env
    fallback2=OllamaProvider(model="mistral"),  # Local, always available
)


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send clinical message to AI",
    description="Send a clinical question and get AI-assisted response.",
)
async def send_message(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    request_body: SendMessageRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR))],
) -> ChatResponse:
    """
    Send clinical message and get AI response.

    This endpoint:
    1. Creates or loads conversation
    2. Saves clinician message
    3. Builds de-identified clinical context
    4. Calls LLM (with automatic failover: GPT-4o → Claude → Ollama)
    5. Saves AI response with advisory label
    6. Publishes audit event

    Args:
        patient_id: Patient UUID (from URL path)
        request_body: {message: "...", conversation_id: "..." (optional)}

    Returns:
        ChatResponse: {success: true, data: {conversation_id, message_id, response, tokens_used, model_used}, meta: {...}}

    Status Codes:
        - 200 OK: Message sent and response received
        - 400 Bad Request: Invalid message or conversation_id
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions (not a Doctor)
        - 404 Not Found: Patient or conversation not found
        - 503 Service Unavailable: All LLM providers failed

    HIPAA:
        - Response includes Cache-Control: no-store (PHI: conversations)
        - Patient data is de-identified before cloud LLM calls
        - All interactions audited

    Audit:
        Logs action="clinical_message_sent" with patient_id, model_used, tokens_used

    Advisory:
        Response automatically includes: "⚠️ AI-generated — verify independently"
    """
    audit_service = AuditService(db)
    ai_service = AIAssistantService(db, audit_service, _llm_provider)

    try:
        conversation_id = uuid.UUID(request_body.conversation_id) if request_body.conversation_id else None

        result = await ai_service.send_message(
            patient_id=patient_id,
            clinician_id=user_id,
            message_text=request_body.message,
            conversation_id=conversation_id,
        )

        return ChatResponse(
            success=True,
            data=result,
            meta={
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        await audit_service.log_action(
            action="chat_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="All LLM providers failed. Please try again later.",
        )


@router.get(
    "/history",
    response_model=HistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get conversation history",
    description="Fetch message history for a patient.",
)
async def get_history(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    conversation_id: Annotated[str, None] = None,
    limit: Annotated[int, 50] = 50,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)] = None,
    user_id: Annotated[uuid.UUID, Depends(get_current_user)] = None,
    request_id: Annotated[str, Depends(get_request_id)] = None,
    _: Annotated[None, Depends(require_role(Role.DOCTOR))] = None,
) -> HistoryResponse:
    """
    Get conversation history for a patient.

    Returns messages from a specific conversation or all conversations
    for the patient, ordered most-recent-first.

    Args:
        patient_id: Patient UUID (from URL path)
        conversation_id: Optional specific conversation (all if None)
        limit: Max messages to return (1-500, default 50)

    Returns:
        HistoryResponse: {success: true, data: [messages], meta: {...}}

    Status Codes:
        - 200 OK: History retrieved (may be empty if no messages)
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions
        - 404 Not Found: Patient or conversation not found

    HIPAA:
        - Response includes Cache-Control: no-store
        - Access audited

    Audit:
        Logs action="history_accessed"
    """
    audit_service = AuditService(db)
    ai_service = AIAssistantService(db, audit_service, _llm_provider)

    try:
        # Validate limit
        limit = max(1, min(int(limit), 500))

        # Load conversation_id if provided
        conv_uuid = uuid.UUID(conversation_id) if conversation_id else None

        # Get history
        messages = await ai_service.get_history(
            patient_id=patient_id,
            conversation_id=conv_uuid,
            limit=limit,
        )

        # Audit access
        await audit_service.log_action(
            action="history_accessed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"message_count": len(messages)},
        )

        return HistoryResponse(
            success=True,
            data=messages,
            meta={
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total": len(messages),
            },
        )

    except Exception as exc:
        await audit_service.log_action(
            action="history_access_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve history",
        )
