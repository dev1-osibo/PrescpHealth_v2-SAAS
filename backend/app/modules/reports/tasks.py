"""
PrescpHealth Backend — Report Generation Celery Tasks.

Background tasks for asynchronous PDF generation.
Follows alerts/tasks.py patterns:
  - bind=True for self-retry access
  - asyncio.run() bridges sync Celery context to async PDF builder
  - Exponential backoff retry on failures
  - PHI-safe logging (task_id and patient_id UUID only)

Retry policy:
  max_retries=3, time_limit=30 seconds.
  Delay formula: 30 * (4 ** retry_count) → 30 s, 2 min, 8 min.
"""
import asyncio
import uuid
import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)

_BACKOFF_BASE = 30
_BACKOFF_FACTOR = 4


@shared_task(
    bind=True,
    name="reports.generate_clinical_pdf",
    max_retries=3,
    time_limit=30,
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_clinical_pdf_task(
    self,
    patient_id: str,
    task_id: str,
    sections: list[str],
    tenant_id: str,
) -> dict:
    """
    Generate a clinical summary PDF and update the task tracker record.

    PHI safety: logs only task_id and patient_id UUID — never PDF content.

    Args:
        patient_id: Patient UUID string.
        task_id: BackgroundTask tracking UUID string.
        sections: List of clinical section keys to render.
        tenant_id: Tenant UUID string.

    Returns:
        dict with status and bytes_size on success.

    Raises:
        Retries up to max_retries times with exponential backoff.
    """
    return asyncio.run(
        _generate_clinical_pdf_async(self, patient_id, task_id, sections, tenant_id)
    )


async def _generate_clinical_pdf_async(
    task: object,
    patient_id: str,
    task_id: str,
    sections: list[str],
    tenant_id: str,
) -> dict:
    """
    Async implementation of generate_clinical_pdf_task.

    Args:
        task: Celery task instance (for retry/request access).
        patient_id: Patient UUID string.
        task_id: BackgroundTask tracking UUID string.
        sections: Section keys to render.
        tenant_id: Tenant UUID string.

    Returns:
        dict summarising the completed task.
    """
    from app.modules.reports.pdf_builder import PDFBuilder

    logger.info(
        "generate_clinical_pdf_task_started",
        task_id=task_id,
        patient_id=patient_id,
        retry_count=task.request.retries,
    )

    try:
        builder = PDFBuilder(
            tenant_id=uuid.UUID(tenant_id),
            request_id=task_id,
        )
        pdf_bytes = await builder.build_clinical_pdf(
            patient_id=uuid.UUID(patient_id),
            sections=sections,
        )

        await _update_task_status(
            task_id=task_id,
            status="completed",
            result={"bytes_size": len(pdf_bytes)},
        )

        logger.info(
            "generate_clinical_pdf_task_completed",
            task_id=task_id,
            patient_id=patient_id,
            bytes_size=len(pdf_bytes),
        )

        return {"status": "completed", "task_id": task_id, "bytes_size": len(pdf_bytes)}

    except Exception as exc:
        await _update_task_status(task_id=task_id, status="failed", error=str(exc))

        retry_delay = _BACKOFF_BASE * (_BACKOFF_FACTOR ** task.request.retries)
        logger.warning(
            "generate_clinical_pdf_task_retry",
            task_id=task_id,
            patient_id=patient_id,
            retry_count=task.request.retries,
            retry_delay_seconds=retry_delay,
            error_type=type(exc).__name__,
        )
        raise task.retry(exc=exc, countdown=retry_delay)


@shared_task(
    bind=True,
    name="reports.generate_referral_pdf",
    max_retries=3,
    time_limit=30,
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_referral_pdf_task(
    self,
    patient_id: str,
    task_id: str,
    referring_physician: str,
    referral_reason: str,
    tenant_id: str,
) -> dict:
    """
    Generate a referral letter PDF and update the task tracker record.

    PHI safety: logs only task_id and patient_id UUID.

    Args:
        patient_id: Patient UUID string.
        task_id: BackgroundTask tracking UUID string.
        referring_physician: Referring clinician name/ID.
        referral_reason: Clinical reason text (not logged).
        tenant_id: Tenant UUID string.

    Returns:
        dict with status and bytes_size on success.

    Raises:
        Retries up to max_retries times with exponential backoff.
    """
    return asyncio.run(
        _generate_referral_pdf_async(
            self, patient_id, task_id, referring_physician, referral_reason, tenant_id
        )
    )


async def _generate_referral_pdf_async(
    task: object,
    patient_id: str,
    task_id: str,
    referring_physician: str,
    referral_reason: str,
    tenant_id: str,
) -> dict:
    """
    Async implementation of generate_referral_pdf_task.

    Args:
        task: Celery task instance.
        patient_id: Patient UUID string.
        task_id: BackgroundTask tracking UUID string.
        referring_physician: Referring clinician identifier.
        referral_reason: Clinical reason (not logged).
        tenant_id: Tenant UUID string.

    Returns:
        dict summarising the completed task.
    """
    from app.modules.reports.pdf_builder import PDFBuilder

    logger.info(
        "generate_referral_pdf_task_started",
        task_id=task_id,
        patient_id=patient_id,
        retry_count=task.request.retries,
    )

    try:
        builder = PDFBuilder(
            tenant_id=uuid.UUID(tenant_id),
            request_id=task_id,
        )
        pdf_bytes = await builder.build_referral_pdf(
            patient_id=uuid.UUID(patient_id),
            referring_physician=referring_physician,
            referral_reason=referral_reason,
        )

        await _update_task_status(
            task_id=task_id,
            status="completed",
            result={"bytes_size": len(pdf_bytes)},
        )

        logger.info(
            "generate_referral_pdf_task_completed",
            task_id=task_id,
            patient_id=patient_id,
            bytes_size=len(pdf_bytes),
        )

        return {"status": "completed", "task_id": task_id, "bytes_size": len(pdf_bytes)}

    except Exception as exc:
        await _update_task_status(task_id=task_id, status="failed", error=str(exc))

        retry_delay = _BACKOFF_BASE * (_BACKOFF_FACTOR ** task.request.retries)
        logger.warning(
            "generate_referral_pdf_task_retry",
            task_id=task_id,
            patient_id=patient_id,
            retry_count=task.request.retries,
            retry_delay_seconds=retry_delay,
            error_type=type(exc).__name__,
        )
        raise task.retry(exc=exc, countdown=retry_delay)


async def _update_task_status(
    task_id: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """
    Update the BackgroundTask record status via the task tracker.

    Gracefully skips if the tracker module is not yet available.

    Args:
        task_id: UUID string of the task to update.
        status: New status value ("completed" or "failed").
        result: Optional result dict to store on success.
        error: Optional error string to store on failure.
    """
    try:
        from app.core.tasks_tracker import BackgroundTaskTracker  # type: ignore[import]
        from app.core.database import get_async_session_context  # type: ignore[import]

        async with get_async_session_context() as db:
            tracker = BackgroundTaskTracker(db=db)
            await tracker.update_status(
                task_id=task_id,
                status=status,
                result=result,
                error=error,
            )
    except (ImportError, Exception) as exc:
        logger.warning(
            "task_status_update_skipped",
            task_id=task_id,
            status=status,
            error_type=type(exc).__name__,
            note="tasks_tracker not available; status update is a no-op",
        )
