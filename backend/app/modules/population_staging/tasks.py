"""
PrescpHealth Backend — Population Analytics Celery Tasks.

Provides a periodic task that pre-computes and caches population metrics
for all configured tenants. Designed to run every hour via Celery beat.

PHI safety:
- Logs only tenant_id UUID and metric_type name strings.
- No patient identifiers, scores, or clinical values are logged.

Beat schedule entry (add to main celery beat schedule config):

    "refresh-population-metrics": {
        "task": "app.modules.population_staging.tasks.refresh_population_metrics_task",
        "schedule": 3600,  # every hour
        "kwargs": {"tenant_id": "<uuid-string>"},
    }
"""
import asyncio
import uuid
import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)

# Metric types that are refreshed on each run
_METRIC_TYPES = ["risk_distribution", "trend_1m", "trend_3m", "trend_6m", "trend_12m"]


@shared_task(
    name="population.refresh_population_metrics",
    ignore_result=True,
)
def refresh_population_metrics_task(tenant_id: str) -> None:
    """
    Pre-compute and cache all population metrics for a given tenant.

    Triggered by Celery beat every hour. Runs metric computation for each
    metric type and stores the results in cached_population_metrics with a
    1-hour TTL. On error, logs a warning and continues (no retry needed;
    the next scheduled run will attempt recomputation).

    PHI safety: logs only tenant_id UUID and metric_type strings.

    Args:
        tenant_id: UUID string of the tenant to refresh metrics for.
    """
    logger.info(
        "population_metrics_refresh_started",
        tenant_id=tenant_id,
    )
    asyncio.run(_refresh_async(tenant_id))
    logger.info(
        "population_metrics_refresh_completed",
        tenant_id=tenant_id,
    )


async def _refresh_async(tenant_id_str: str) -> None:
    """
    Async implementation of refresh_population_metrics_task.

    Opens a DB session, instantiates PopulationService for the tenant, and
    calls each metric computation method in sequence. Errors in individual
    metric types are caught and logged without aborting the remaining types.

    Args:
        tenant_id_str: UUID string of the tenant to refresh.
    """
    from app.core.database import get_async_session_context
    from app.core.audit import AuditService
    from app.modules.population_staging.service import PopulationService

    tenant_id = uuid.UUID(tenant_id_str)
    # Synthetic request_id for background tasks
    request_id = str(uuid.uuid4())

    for metric_type in _METRIC_TYPES:
        try:
            async with get_async_session_context() as db:
                audit_service = AuditService(db=db, tenant_id=tenant_id)
                svc = PopulationService(
                    db=db,
                    audit_service=audit_service,
                    request_id=request_id,
                    tenant_id=tenant_id,
                    user_id=uuid.UUID(int=0),  # system actor
                )

                if metric_type == "risk_distribution":
                    await svc.get_dashboard_metrics()
                elif metric_type.startswith("trend_"):
                    window = metric_type.split("_", 1)[1]  # e.g. "3m"
                    await svc.get_trends(window=window)

            logger.info(
                "population_metric_type_refreshed",
                tenant_id=tenant_id_str,
                metric_type=metric_type,
            )

        except Exception as exc:
            logger.warning(
                "population_metric_refresh_failed",
                tenant_id=tenant_id_str,
                metric_type=metric_type,
                error_type=type(exc).__name__,
            )
