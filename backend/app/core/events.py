"""
PrescpHealth Backend — Domain Event Bus.

Implements an in-process publish/subscribe event system for decoupling
modules. When something important happens (measurement saved, risk computed),
the originating module publishes an event. Other modules subscribe to events
they care about and react accordingly.

Why events instead of direct service calls:
- Decoupling: The measurement module doesn't need to know about the risk engine.
  It just publishes 'MeasurementSaved' and whoever cares will react.
- Extensibility: Adding a new reaction (e.g., "also notify the patient portal")
  doesn't require modifying the original module.
- Testability: Each subscriber can be tested independently.
- Audit trail: Events provide a natural log of what happened and when.

Event Flow Example:
    1. Clinician saves a blood pressure measurement
    2. MeasurementService publishes MeasurementSaved event
    3. Subscribers react:
       - RiskEngine: triggers async risk recomputation
       - AlertService: checks if measurement exceeds thresholds
       - AuditService: logs the data access

Architecture:
    - Events are simple dataclasses with typed fields
    - Handlers are async functions registered at startup
    - Publishing is fire-and-forget (handlers run in background)
    - Errors in one handler don't affect other handlers
    - correlation_id flows through events for end-to-end tracing

Limitations:
    - In-process only (not distributed). For multi-instance deployments,
      events that need cross-instance delivery should use Celery tasks.
    - No guaranteed delivery. If the process crashes mid-handling, the
      event is lost. Critical flows should use Celery for durability.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from uuid import UUID

import structlog

# ---------------------------------------------------------------------------
# Module logger — logs event publishing and handling without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Type alias for event handler functions
EventHandler = Callable[["DomainEvent"], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Base Event Class
# ---------------------------------------------------------------------------
@dataclass
class DomainEvent:
    """
    Base class for all domain events.

    Every event carries metadata for tracing and audit:
    - correlation_id: Links this event to the originating request
    - tenant_id: Which tenant this event belongs to
    - occurred_at: When the event happened (UTC)
    - event_type: Machine-readable event name (set by subclasses)

    Subclasses add domain-specific fields (patient_id, scores, etc.)
    """

    correlation_id: str
    tenant_id: UUID
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = "domain_event"


# ---------------------------------------------------------------------------
# Concrete Event Types
# ---------------------------------------------------------------------------
@dataclass
class MeasurementSaved(DomainEvent):
    """
    Published when a new clinical measurement is saved.

    Triggers: risk recomputation, threshold alert checks, audit logging.

    Forward-compatibility fields (Task 9 & 10):
    - is_flagged: Allows Risk Engine to prioritize flagged measurements
    - flag_reason: Provides context for alert generation without re-querying
    - is_validated: Allows Risk Engine to skip unvalidated Patient_User entries
    """

    event_type: str = "measurement_saved"
    patient_id: UUID | None = None
    measurement_type: str = ""
    measurement_id: UUID | None = None
    # --- Forward-compatibility fields for Risk Engine (Task 9) ---
    # These have defaults so existing publishers/subscribers are unaffected
    is_flagged: bool = False
    flag_reason: str | None = None
    is_validated: bool = False


@dataclass
class RiskScoreComputed(DomainEvent):
    """
    Published when risk scores are computed for a patient.

    Triggers: alert threshold evaluation, forecast update consideration.
    """

    event_type: str = "risk_score_computed"
    patient_id: UUID | None = None
    disease_count: int = 0
    computation_id: UUID | None = None


@dataclass
class ForecastCompleted(DomainEvent):
    """
    Published when a health trajectory forecast completes.

    Triggers: forecast-based alert checks, patient timeline update.
    """

    event_type: str = "forecast_completed"
    patient_id: UUID | None = None
    forecast_id: UUID | None = None


@dataclass
class AlertGenerated(DomainEvent):
    """
    Published when a new clinical alert is generated.

    Triggers: notification dispatch (email/SMS/WhatsApp/in-app).
    """

    event_type: str = "alert_generated"
    patient_id: UUID | None = None
    alert_id: UUID | None = None
    severity: str = ""  # "critical", "high", "moderate", "low"


@dataclass
class HealthStatusChanged(DomainEvent):
    """
    Published when a patient's health status changes significantly.

    Triggers: drug interaction re-evaluation, care plan review.
    Examples: new diagnosis added, eGFR drops below threshold, risk stratum changes.
    """

    event_type: str = "health_status_changed"
    patient_id: UUID | None = None
    change_type: str = ""  # "diagnosis_added", "risk_stratum_changed", "lab_critical"


@dataclass
class LabResultReceived(DomainEvent):
    """
    Published when a lab result is recorded for a lab order.

    Triggers: downstream processing, clinical review notifications,
    and integration with external systems. The abnormal flag allows
    subscribers to prioritize critical results without re-querying.

    HIPAA: Contains only opaque IDs and the abnormal flag — no PHI
    (no test names, no result values, no patient names).
    """

    event_type: str = "lab_result_received"
    patient_id: UUID | None = None
    lab_order_id: UUID | None = None
    lab_result_id: UUID | None = None
    is_abnormal: bool = False
    loinc_code: str = ""


@dataclass
class PrescriptionWritten(DomainEvent):
    """
    Published when a new prescription is successfully written.

    Triggers: medication list update, potential DDI re-evaluation for
    other active prescriptions, pharmacy notification.

    HIPAA: Only contains opaque UUIDs — no drug names or dosages.
    """

    event_type: str = "prescription_written"
    patient_id: UUID | None = None
    prescription_id: UUID | None = None
    encounter_id: UUID | None = None


@dataclass
class EncounterCompleted(DomainEvent):
    """
    Published when a clinician completes an encounter (discharge).

    Triggers: billing invoice generation, FHIR resource update,
    notification to patient portal, care plan finalization.

    The event carries only opaque IDs — no clinical content (PHI-safe).
    """

    event_type: str = "encounter_completed"
    encounter_id: UUID | None = None
    patient_id: UUID | None = None


# ---------------------------------------------------------------------------
# Event Bus — In-Process Pub/Sub
# ---------------------------------------------------------------------------
class EventBus:
    """
    Simple in-process event bus for domain event pub/sub.

    Handlers are registered at application startup and called whenever
    a matching event is published. Multiple handlers can subscribe to
    the same event type.

    Thread Safety:
        This is designed for async (single-thread) usage within FastAPI.
        All handlers are async functions run via asyncio.

    Error Isolation:
        If one handler raises an exception, other handlers still execute.
        Failed handlers are logged but don't propagate errors to the publisher.
    """

    def __init__(self) -> None:
        """Initialize with empty handler registry."""
        # Maps event_type string -> list of handler functions
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Register a handler for a specific event type.

        Args:
            event_type: The event_type string to listen for (e.g., "measurement_saved")
            handler: Async function that accepts a DomainEvent and processes it.

        Usage:
            bus.subscribe("measurement_saved", risk_engine.on_measurement_saved)
            bus.subscribe("risk_score_computed", alert_service.on_risk_computed)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info("event_handler_registered", event_type=event_type, handler=handler.__name__)

    async def publish(self, event: DomainEvent) -> None:
        """
        Publish an event to all registered handlers.

        Handlers run concurrently (asyncio.gather). If any handler fails,
        the error is logged but other handlers complete normally.
        The publisher is never blocked by handler failures.

        Args:
            event: The domain event to publish.
        """
        handlers = self._handlers.get(event.event_type, [])

        if not handlers:
            # No subscribers — this is fine, just means no one cares yet
            return

        logger.info(
            "event_published",
            event_type=event.event_type,
            correlation_id=event.correlation_id,
            handler_count=len(handlers),
        )

        # Run all handlers concurrently, isolating failures
        results = await asyncio.gather(
            *[self._safe_handle(handler, event) for handler in handlers],
            return_exceptions=True,
        )

        # Log any handler failures (but don't propagate)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "event_handler_failed",
                    event_type=event.event_type,
                    handler=handlers[i].__name__,
                    error_type=type(result).__name__,
                    correlation_id=event.correlation_id,
                )

    async def _safe_handle(self, handler: EventHandler, event: DomainEvent) -> None:
        """
        Execute a single handler with error isolation.

        Wraps the handler call in try/except so one failing handler
        doesn't prevent others from executing.

        Args:
            handler: The async handler function.
            event: The domain event to pass to the handler.
        """
        try:
            await handler(event)
        except Exception as e:
            # Re-raise so asyncio.gather captures it (logged in publish())
            raise e


# ---------------------------------------------------------------------------
# Global event bus instance — shared across the application
# ---------------------------------------------------------------------------
# Initialized once, handlers registered during app startup.
# All modules import this instance to publish/subscribe.
event_bus = EventBus()
