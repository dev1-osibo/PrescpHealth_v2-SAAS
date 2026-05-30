"""
PrescpHealth Backend — AI Assistant Service.

AIAssistantService manages clinical conversations with AI.

Key Responsibilities:
    - Build clinical context (patient profile, measurements, risk scores)
    - De-identify patient data before sending to cloud LLMs (no names, MRNs, PII)
    - Call LLM provider (with automatic failover)
    - Persist conversation and messages in database
    - Include advisory: "AI-generated — verify independently"
    - Audit every interaction

HIPAA Compliance:
    - De-identify before cloud LLM calls (GPT-4o, Claude)
    - Keep identifying info on-premises only (never send to cloud)
    - Ollama (local) receives all data (stays on-premises)
    - All responses include advisory label
    - Audit trail for compliance
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.audit.service import AuditService
from app.modules.ai_assistant.models import Conversation, Message
from app.modules.ai_assistant.providers import LLMProvider, LLMError

logger = structlog.get_logger(__name__)


class AIAssistantService:
    """
    Service for AI clinical assistant conversations.

    Manages conversation lifecycle, context building, LLM calls, and persistence.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: AuditService,
        llm_provider: LLMProvider,
    ):
        """
        Initialize AIAssistantService.

        Args:
            db: AsyncSession for database operations
            audit_service: AuditService for audit logging
            llm_provider: LLM provider (with failover support)
        """
        self.db = db
        self.audit_service = audit_service
        self.llm_provider = llm_provider

    async def send_message(
        self,
        patient_id: uuid.UUID,
        clinician_id: uuid.UUID,
        message_text: str,
        conversation_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """
        Send clinical message and get AI response.

        Orchestrates:
        1. Load/create conversation
        2. Build clinical context (de-identified for cloud LLMs)
        3. Call LLM provider (with failover)
        4. Persist messages and conversation
        5. Audit interaction

        Args:
            patient_id: Patient UUID
            clinician_id: Clinician UUID
            message_text: Clinical question/message
            conversation_id: Optional existing conversation ID (new if None)

        Returns:
            dict: {
                "conversation_id": "...",
                "message_id": "...",
                "response": "AI response text (with advisory label)",
                "tokens_used": 42,
                "model_used": "gpt-4o",
            }

        Raises:
            LLMError: All LLM providers failed
        """
        try:
            # Get or create conversation
            if conversation_id:
                conv = await self.db.get(Conversation, conversation_id)
                if not conv:
                    raise ValueError(f"Conversation {conversation_id} not found")
            else:
                conv = Conversation(
                    patient_id=patient_id,
                    clinician_id=clinician_id,
                    started_at=datetime.now(timezone.utc),
                    last_message_at=datetime.now(timezone.utc),
                    message_count=0,
                    is_active=True,
                )
                self.db.add(conv)
                await self.db.flush()

            # Save clinician message
            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=message_text,
            )
            self.db.add(user_msg)
            await self.db.flush()

            # Build clinical context (de-identified for cloud LLMs)
            context = await self._build_context(patient_id)

            # Build message history for LLM
            messages = await self._get_conversation_history(conv.id)

            # Call LLM with failover
            try:
                ai_response = await self.llm_provider.send(messages, context)
                tokens_used = await self.llm_provider.count_tokens(ai_response)
                model_used = self.llm_provider.__class__.__name__.replace("Provider", "").lower()
            except LLMError as exc:
                logger.error(
                    "llm_call_failed",
                    patient_id=str(patient_id),
                    error=str(exc),
                )
                raise

            # Add advisory label
            advisory = "\n\n⚠️ AI-generated suggestion — verify independently with clinical judgment"
            full_response = ai_response + advisory

            # Save AI response
            ai_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content=full_response,
                model_used=model_used,
                tokens_used=tokens_used,
            )
            self.db.add(ai_msg)

            # Update conversation metadata
            conv.message_count += 2  # Clinician + AI
            conv.last_message_at = datetime.now(timezone.utc)

            await self.db.flush()
            await self.db.commit()

            # Audit interaction
            await self.audit_service.log_action(
                action="clinical_message_sent",
                resource_type="conversation",
                resource_id=conv.id,
                user_id=clinician_id,
                changes={
                    "patient_id": str(patient_id),
                    "model_used": model_used,
                    "tokens_used": tokens_used,
                },
            )

            logger.info(
                "ai_response_generated",
                patient_id=str(patient_id),
                conversation_id=str(conv.id),
                model=model_used,
                tokens=tokens_used,
            )

            return {
                "conversation_id": str(conv.id),
                "message_id": str(ai_msg.id),
                "response": full_response,
                "tokens_used": tokens_used,
                "model_used": model_used,
            }

        except Exception as exc:
            logger.error(
                "send_message_failed",
                patient_id=str(patient_id),
                error=str(exc),
            )
            raise

    async def get_history(
        self,
        patient_id: uuid.UUID,
        conversation_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get conversation history for a patient.

        Args:
            patient_id: Patient UUID
            conversation_id: Optional specific conversation (all if None)
            limit: Max messages to return

        Returns:
            list of dicts: [{role, content, model_used, created_at, ...}, ...]
        """
        if conversation_id:
            # Get messages for specific conversation
            stmt = select(Message).where(
                Message.conversation_id == conversation_id
            ).order_by(
                desc(Message.created_at)
            ).limit(limit)
        else:
            # Get messages from all conversations for this patient
            stmt = select(Message).join(Conversation).where(
                Conversation.patient_id == patient_id
            ).order_by(
                desc(Message.created_at)
            ).limit(limit)

        result = await self.db.execute(stmt)
        messages = result.scalars().all()

        return [
            {
                "id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "role": msg.role,
                "content": msg.content,
                "model_used": msg.model_used,
                "tokens_used": msg.tokens_used,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ]

    async def _build_context(self, patient_id: uuid.UUID) -> dict:
        """
        Build clinical context for LLM.

        De-identifies patient data before sending to cloud LLMs:
        - No patient name (use ID only)
        - No MRN
        - No full dates (use age instead)
        - Clinical data (measurements, risks) are OK (no direct identifiers)

        Args:
            patient_id: Patient UUID

        Returns:
            dict: De-identified clinical context
        """
        # TODO: Task 11.2+: Fetch patient data from Patients service
        # TODO: Task 11.2+: Fetch latest measurements from Measurements service
        # TODO: Task 11.2+: Fetch risk scores from Risk Engine
        # For now, return stub context

        context = {
            "patient_id": str(patient_id),
            "age_range": "50-60",  # De-identified (not exact birth date)
            "sex": "M",
            "conditions": ["hypertension", "type_2_diabetes"],
            "recent_measurements": {
                "systolic_bp": 160,
                "diastolic_bp": 95,
                "glucose": 185,
                "weight_kg": 95,
            },
            "risk_scores": {
                "stroke": 68,
                "cvd": 72,
                "diabetes": 75,
            },
            "note": "De-identified clinical context (safe for cloud LLMs)",
        }

        return context

    async def _get_conversation_history(self, conversation_id: uuid.UUID) -> list[dict]:
        """
        Get message history for LLM context.

        Formats messages as [{role, content}, ...] for LLM API.

        Args:
            conversation_id: Conversation UUID

        Returns:
            list of {role, content} dicts
        """
        stmt = select(Message).where(
            Message.conversation_id == conversation_id
        ).order_by(
            Message.created_at
        ).limit(20)  # Last 20 messages for context window

        result = await self.db.execute(stmt)
        messages = result.scalars().all()

        return [
            {
                "role": msg.role,
                "content": msg.content,
            }
            for msg in messages
        ]
