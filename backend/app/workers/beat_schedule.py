"""
PrescpHealth Backend — Celery Beat Schedule (Periodic Tasks).

Defines tasks that run on a recurring schedule:
- Population metrics refresh: Every 30 minutes (keeps dashboard data fresh)
- Escalation checks: Every 5 minutes (ensures critical alerts are escalated)
- Stale session cleanup: Every hour (removes expired refresh tokens)

These are STUBS — the actual task implementations live in their respective
module tasks.py files. This file only defines WHEN they run.

Architecture:
    Celery Beat is a single-process scheduler that enqueues periodic tasks.
    It does NOT execute them — workers pick them up from the queue.
    Only ONE beat process should run at a time (use --pidfile to enforce).

    Start with: celery -A app.workers.celery_app beat --loglevel=info
"""

from celery.schedules import crontab

from app.workers.celery_app import celery_app

# ---------------------------------------------------------------------------
# Periodic Task Schedule
# ---------------------------------------------------------------------------
celery_app.conf.beat_schedule = {
    # -----------------------------------------------------------------------
    # Population Metrics Refresh
    # -----------------------------------------------------------------------
    # Refreshes cached aggregate metrics for the population dashboard.
    # Runs every 30 minutes so dashboard data is at most 30 min stale.
    # Per design: metrics refresh interval <= 1 hour.
    "refresh-population-metrics": {
        "task": "app.modules.population.tasks.refresh_population_metrics",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "report"},  # Low priority — doesn't block clinical work
    },

    # -----------------------------------------------------------------------
    # Alert Escalation Check
    # -----------------------------------------------------------------------
    # Checks for unacknowledged Critical alerts past their timeout.
    # Escalation chain: Nurse (15min) -> Doctor (30min) -> Clinic_Admin
    # Runs every 5 minutes to ensure timely escalation.
    "check-alert-escalation": {
        "task": "app.modules.alerts.tasks.check_escalation",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "notification"},  # High priority — patient safety
    },

    # -----------------------------------------------------------------------
    # Missed Follow-up Detection
    # -----------------------------------------------------------------------
    # Identifies patients who haven't had measurements within their
    # configured follow-up interval. Generates reminder alerts.
    # Runs every hour — daily would miss urgent cases.
    "check-missed-followups": {
        "task": "app.modules.alerts.tasks.check_missed_followups",
        "schedule": crontab(minute=0),  # Top of every hour
        "options": {"queue": "notification"},
    },

    # -----------------------------------------------------------------------
    # Stale Session Cleanup
    # -----------------------------------------------------------------------
    # Removes expired refresh tokens from Redis/DB.
    # Runs every hour — not urgent but keeps storage clean.
    "cleanup-expired-sessions": {
        "task": "app.modules.auth.tasks.cleanup_expired_sessions",
        "schedule": crontab(minute=15),  # 15 past every hour
        "options": {"queue": "celery"},  # Default queue — lowest priority
    },
}
