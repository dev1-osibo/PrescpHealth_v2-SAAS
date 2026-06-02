"""
PrescpHealth Backend — Report Service.

Core business logic for the reports module. Handles:
  - Enqueuing PDF generation tasks (clinical and referral)
  - Streaming CSV exports (measurements and population)

Follows the same structural patterns as alerts_staging/service.py:
  - Injected DB session + AuditService + correlation IDs
  - PHI-safe logging (UUIDs only; never patient names or clinical values)
  - Full async/await throughout
  - Audit logging on every mutation/export
"""
import uuid
import structlog
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports_staging.csv_exporter import CSVExporter
from app.modules.reports_staging.exceptions import ReportError

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional task tracker import — graceful stub if module not yet available
# ---------------------------------------------------------------------------
try:
    from app.core.tasks_tracker_staging import BackgroundTaskTracker  # type: ignore[import]
    TRACKER_AVAILABLE = True
except ImportError:
    TRACKER_AVAILABLE = False

    class BackgroundTaskTracker:  # type: ignore[no-redef]
        """Stub tracker used when app.core.tasks_tracker_staging is not installed."""

        def __init__(self, db: Any) -> None:
            """Initialize stub tracker."""
            self.db = db

        async def create_task(self, task_type: str, tenant_id: uuid.UUID) -> str:
            """Return a new UUID as a pseudo task_id."""
            return str(uuid.uuid4())

        async def update_status(
            self,
            task_id: str,
            status: str,
            result: dict | None = None,
            error: str | None = None,
        ) -> None:
            """No-op status update in stub mode."""
            pass


class ReportService:
    """
    Orchestrates report generation: PDF tasks and CSV streaming.

    Instantiated per-request with injected DB session and audit service.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: Any,
        request_id: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Args:
            db: Async SQLAlchemy session (request-scoped).
            audit_service: Injected AuditService for mutation logging.
            request_id: Correlation ID from HTTP request.
            tenant_id: Current tenant scope enforced on all queries.
            user_id: Authenticated user; used as actor in audit records.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def request_clinical_report(
        self,
        patient_id: uuid.UUID,
        sections: list[str],
    ) -> str:
        """
        Enqueue a clinical PDF generation task and return its task_id.

        Creates a BackgroundTask tracking record, enqueues the Celery task,
        and writes an audit log entry.

        PHI safety: logs only patient_id UUID and task_id.

        Args:
            patient_id: UUID of the patient for whom the report is generated.
            sections: Clinical sections to include in the PDF.

        Returns:
            task_id (str UUID) that the caller can use to poll task status.
        """
        from app.modules.reports_staging.tasks import generate_clinical_pdf_task

        tracker = BackgroundTaskTracker(db=self.db)
        task_id = await tracker.create_task(
            task_type="clinical_pdf",
            tenant_id=self.tenant_id,
        )

        generate_clinical_pdf_task.delay(
            str(patient_id),
            str(task_id),
            sections,
            str(self.tenant_id),
        )

        await self.audit_service.log_audit(
            action="report_requested",
            resource_type="patient",
            resource_id=str(patient_id),
            changes={"task_id": task_id, "sections": sections},
        )

        logger.info(
            "clinical_report_requested",
            patient_id=str(patient_id),
            task_id=str(task_id),
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        return str(task_id)

    async def request_referral_report(
        self,
        patient_id: uuid.UUID,
        referring_physician: str,
        referral_reason: str,
    ) -> str:
        """
        Enqueue a referral letter PDF generation task and return its task_id.

        PHI safety: logs only patient_id UUID and task_id.

        Args:
            patient_id: UUID of the patient being referred.
            referring_physician: Name/ID of the referring clinician.
            referral_reason: Clinical reason text (not logged).

        Returns:
            task_id (str UUID) for polling task status.
        """
        from app.modules.reports_staging.tasks import generate_referral_pdf_task

        tracker = BackgroundTaskTracker(db=self.db)
        task_id = await tracker.create_task(
            task_type="referral_pdf",
            tenant_id=self.tenant_id,
        )

        generate_referral_pdf_task.delay(
            str(patient_id),
            str(task_id),
            referring_physician,
            referral_reason,
            str(self.tenant_id),
        )

        await self.audit_service.log_audit(
            action="referral_requested",
            resource_type="patient",
            resource_id=str(patient_id),
            changes={"task_id": task_id},
        )

        logger.info(
            "referral_report_requested",
            patient_id=str(patient_id),
            task_id=str(task_id),
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        return str(task_id)

    async def stream_measurements_csv(
        self,
        patient_id: uuid.UUID,
    ) -> AsyncGenerator[str, None]:
        """
        Stream patient measurements as CSV rows.

        Instantiates CSVExporter and delegates to export_measurements.
        Writes an audit log entry for the export action.

        Args:
            patient_id: UUID of the patient whose measurements to export.

        Returns:
            Async generator of CSV string rows (header + data).
        """
        await self.audit_service.log_audit(
            action="measurements_exported",
            resource_type="patient",
            resource_id=str(patient_id),
            changes={},
        )

        logger.info(
            "measurements_csv_stream_started",
            patient_id=str(patient_id),
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        exporter = CSVExporter(db=self.db, tenant_id=self.tenant_id)
        return exporter.export_measurements(patient_id=patient_id)

    async def stream_population_csv(self) -> AsyncGenerator[str, None]:
        """
        Stream tenant population risk snapshot as CSV rows.

        Instantiates CSVExporter and delegates to export_population.
        Writes an audit log entry for the export action.

        Returns:
            Async generator of CSV string rows (header + data).
        """
        await self.audit_service.log_audit(
            action="population_exported",
            resource_type="tenant",
            resource_id=str(self.tenant_id),
            changes={},
        )

        logger.info(
            "population_csv_stream_started",
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        exporter = CSVExporter(db=self.db, tenant_id=self.tenant_id)
        return exporter.export_population(tenant_id=self.tenant_id)
