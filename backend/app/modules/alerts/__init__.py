"""
PrescpHealth Backend — Alerts Staging Module.

Alert and Notification System for clinical alert management, including:
- Real-time alert generation from domain events
- Multi-channel dispatch (in-app, email, SMS, WhatsApp)
- Configurable thresholds per patient or tenant-wide
- Escalation chain with timeout-based escalation
- Full audit trail via AuditService

Public exports:
- AlertService: Core business logic — create, acknowledge, query alerts
- AlertRulesEngine: Domain event evaluation against configured thresholds
- AlertDispatcher: Multi-channel notification delivery
- EscalationService: Escalation chain management
- router: FastAPI router with all alert endpoints
"""
from app.modules.alerts.service import AlertService
from app.modules.alerts.rules_engine import AlertRulesEngine
from app.modules.alerts.dispatcher import AlertDispatcher
from app.modules.alerts.escalation import EscalationService
from app.modules.alerts.router import router

__all__ = [
    "AlertService",
    "AlertRulesEngine",
    "AlertDispatcher",
    "EscalationService",
    "router",
]
