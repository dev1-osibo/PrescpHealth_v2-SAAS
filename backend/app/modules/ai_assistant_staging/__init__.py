"""
PrescpHealth Backend — AI Clinical Assistant Module (Staging).

The AI Assistant provides clinical decision support via conversational interface.

Module Responsibility:
    - Expose API endpoints for sending clinical questions to AI
    - Manage conversation history (patient-clinician-AI)
    - Support pluggable LLM providers (OpenAI GPT-4o, Anthropic Claude, local Ollama)
    - Implement LLM failover (primary → fallback on error/timeout)
    - Build clinical context (patient profile, measurements, risk scores)
    - Anonymize PHI before sending to cloud LLMs
    - Log every interaction for audit compliance

Key Components:
    - models.py: SQLAlchemy models (Conversation, Message)
    - service.py: AIAssistantService (send message, get history, context building)
    - providers.py: LLM provider abstraction (GPT-4o, Claude, Ollama, failover)
    - router.py: FastAPI endpoints with RBAC
    - schemas.py: Pydantic request/response models

Dependencies:
    - Requires Task 9 (Risk Engine) for risk context
    - Requires Task 7 (Measurement module) for patient data
    - Requires Task 5 (Patient module) for patient profile
    - Requires core services: audit, events, pagination
    - Requires LLM APIs (OpenAI, Anthropic, local Ollama)

HIPAA Compliance:
    - De-identify patient data before sending to cloud LLMs (GPT-4o, Claude)
    - Log clinical discussions as PHI (audit only, stored encrypted)
    - All responses include advisory: "AI-generated — verify independently"
    - Never send patient names to cloud LLMs (use anonymized identifiers)
"""

from app.modules.ai_assistant_staging.service import AIAssistantService
from app.modules.ai_assistant_staging.router import router

__all__ = ["AIAssistantService", "router"]
