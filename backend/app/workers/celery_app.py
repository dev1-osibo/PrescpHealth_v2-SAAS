"""
PrescpHealth Backend — Celery Application Configuration.

Configures the Celery distributed task queue with Redis as broker.
Defines queue routing so tasks are processed with appropriate priority:
  - notification queue: Highest priority (alerts must reach clinicians fast)
  - risk queue: High priority (risk scores needed for clinical decisions)
  - forecast queue: Medium priority (forecasts are less time-sensitive)
  - report queue: Low priority (PDF/CSV generation can wait)

Architecture:
    Celery workers run as separate processes (not inside the FastAPI server).
    They share the same codebase but are started with:
        celery -A app.workers.celery_app worker --queues=risk,forecast
        celery -A app.workers.celery_app worker --queues=notification
        celery -A app.workers.celery_app beat  (periodic tasks)

    This separation allows scaling workers independently per queue load.

Retry Policy:
    Failed tasks retry with exponential backoff: 30s, 120s, 480s (max 3 retries).
    After max retries, task is marked as failed and logged for investigation.
"""

from celery import Celery

from app.config import get_settings

# ---------------------------------------------------------------------------
# Create Celery application instance
# ---------------------------------------------------------------------------
settings = get_settings()

celery_app = Celery(
    "prescphealth",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# ---------------------------------------------------------------------------
# Celery Configuration
# ---------------------------------------------------------------------------
celery_app.conf.update(
    # --- Serialization ---
    # JSON is human-readable and safe (no pickle deserialization attacks)
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # --- Time Limits ---
    # Hard kill after this many seconds (prevents zombie tasks)
    task_time_limit=settings.celery_task_time_limit,
    # Soft limit raises SoftTimeLimitExceeded (allows cleanup before hard kill)
    task_soft_time_limit=settings.celery_task_soft_time_limit,

    # --- Retry Policy ---
    # Exponential backoff: 30s, 120s, 480s (max 3 retries)
    task_default_retry_delay=30,
    task_max_retries=settings.celery_max_retries,

    # --- Result Backend ---
    # Results expire after 1 hour (we poll for status, don't need long retention)
    result_expires=3600,

    # --- Worker Settings ---
    # Prefetch 1 task at a time per worker (prevents one worker hogging all tasks)
    worker_prefetch_multiplier=1,
    # Acknowledge task AFTER execution (not before) — prevents task loss on crash
    task_acks_late=True,
    # Reject and requeue tasks if worker is killed mid-execution
    task_reject_on_worker_lost=True,

    # --- Timezone ---
    # All timestamps in UTC per i18n steering rule
    timezone="UTC",
    enable_utc=True,

    # --- Queue Routing ---
    # Tasks are routed to specific queues based on their module.
    # Priority order: notification > risk > forecast > report
    task_routes={
        # Alert/notification tasks — highest priority
        "app.modules.alerts.tasks.*": {"queue": "notification"},
        # Risk computation tasks — high priority (clinical decisions depend on these)
        "app.modules.risk_engine.tasks.*": {"queue": "risk"},
        # Forecast tasks — medium priority
        "app.modules.forecast_engine.tasks.*": {"queue": "forecast"},
        # Report generation — low priority (can wait)
        "app.modules.reports.tasks.*": {"queue": "report"},
    },

    # --- Queue Definitions ---
    # Define all queues with their priority weights
    task_queues={
        "notification": {"exchange": "notification", "routing_key": "notification"},
        "risk": {"exchange": "risk", "routing_key": "risk"},
        "forecast": {"exchange": "forecast", "routing_key": "forecast"},
        "report": {"exchange": "report", "routing_key": "report"},
        "celery": {"exchange": "celery", "routing_key": "celery"},  # Default queue
    },

    # Default queue for tasks without explicit routing
    task_default_queue="celery",
)

# ---------------------------------------------------------------------------
# Auto-discover tasks from all modules
# ---------------------------------------------------------------------------
# As modules are added, their tasks.py files are auto-discovered here.
# Each module's tasks.py defines Celery tasks decorated with @celery_app.task
celery_app.autodiscover_tasks([
    "app.modules.risk_engine",
    "app.modules.forecast_engine",
    "app.modules.alerts",
    "app.modules.reports",
])
