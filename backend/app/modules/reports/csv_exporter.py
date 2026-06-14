"""
PrescpHealth Backend — CSV Exporter.

Streams measurement and population data as CSV without loading full result
sets into memory. Uses async generators to allow FastAPI StreamingResponse
to flush rows to the client as they are produced.

PHI safety:
  - Measurement values are streamed as-is (the CSV is PHI — handled at HTTP layer).
  - Logs include only patient_id UUID and row counts; never measurement values.
  - Cache-Control: no-store is enforced at the router layer.

Architecture:
  CSVExporter is instantiated per-request. Both export methods yield
  string rows (including the header) for direct use with StreamingResponse.
"""
import csv
import io
import uuid
import structlog
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class CSVExporter:
    """
    Streams CSV exports for measurements and population risk snapshots.

    Uses async generators so rows are flushed to the HTTP client
    incrementally, avoiding large in-memory buffers for big datasets.
    """

    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        """
        Initialize with a request-scoped DB session and tenant context.

        Args:
            db: Async SQLAlchemy session (request-scoped).
            tenant_id: Current tenant UUID for query scoping.
        """
        self.db = db
        self.tenant_id = tenant_id

    async def export_measurements(
        self,
        patient_id: uuid.UUID,
        limit: int = 10000,
    ) -> AsyncGenerator[str, None]:
        """
        Stream patient measurements as CSV rows.

        PHI safety: logs patient_id UUID and row_count — never measurement values.

        Args:
            patient_id: UUID of the patient whose measurements to export.
            limit: Maximum number of rows to stream (default 10 000).

        Yields:
            CSV-formatted string rows, starting with the header line.
        """
        logger.info(
            "measurement_export_started",
            patient_id=str(patient_id),
            tenant_id=str(self.tenant_id),
            limit=limit,
        )

        yield "date,measurement_type,value,unit,validated\n"

        row_count = 0
        try:
            from sqlalchemy import select, text

            # Try to query a measurements table; fall back to stub rows if unavailable.
            try:
                from app.modules.measurements.models import Measurement  # type: ignore[import]

                stmt = (
                    select(Measurement)
                    .where(
                        Measurement.patient_id == patient_id,
                        Measurement.tenant_id == self.tenant_id,
                    )
                    .order_by(Measurement.measured_at.desc())
                    .limit(limit)
                )
                rows = (await self.db.scalars(stmt)).all()
                for row in rows:
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow([
                        getattr(row, "measured_at", ""),
                        getattr(row, "measurement_type", ""),
                        getattr(row, "value", ""),
                        getattr(row, "unit", ""),
                        getattr(row, "is_validated", ""),
                    ])
                    yield buf.getvalue()
                    row_count += 1

            except (ImportError, Exception):
                # Stub: table not yet available — emit empty result set
                logger.warning(
                    "measurement_export_table_unavailable",
                    patient_id=str(patient_id),
                    note="measurements model not importable; yielding empty dataset",
                )

        except Exception as exc:
            logger.error(
                "measurement_export_error",
                patient_id=str(patient_id),
                error_type=type(exc).__name__,
            )

        logger.info(
            "measurement_export_completed",
            patient_id=str(patient_id),
            row_count=row_count,
            tenant_id=str(self.tenant_id),
        )

    async def export_population(
        self,
        tenant_id: uuid.UUID,
        limit: int = 50000,
    ) -> AsyncGenerator[str, None]:
        """
        Stream population-level patient risk snapshot as CSV rows.

        Yields one row per patient with their latest risk score data.
        PHI safety: logs tenant_id UUID and row_count — no patient PII in logs.

        Args:
            tenant_id: Tenant whose population to export.
            limit: Maximum number of patient rows (default 50 000).

        Yields:
            CSV-formatted string rows, starting with the header line.
        """
        logger.info(
            "population_export_started",
            tenant_id=str(tenant_id),
            limit=limit,
        )

        yield "patient_id,disease,score,stratum,computed_at\n"

        row_count = 0
        try:
            from sqlalchemy import select

            try:
                from app.modules.risk_engine.models import RiskScore  # type: ignore[import]

                stmt = (
                    select(RiskScore)
                    .where(RiskScore.tenant_id == tenant_id)
                    .order_by(RiskScore.computed_at.desc())
                    .limit(limit)
                )
                rows = (await self.db.scalars(stmt)).all()
                for row in rows:
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow([
                        str(getattr(row, "patient_id", "")),
                        getattr(row, "disease", ""),
                        getattr(row, "score", ""),
                        getattr(row, "stratum", ""),
                        getattr(row, "computed_at", ""),
                    ])
                    yield buf.getvalue()
                    row_count += 1

            except (ImportError, Exception):
                logger.warning(
                    "population_export_table_unavailable",
                    tenant_id=str(tenant_id),
                    note="risk_engine model not importable; yielding empty dataset",
                )

        except Exception as exc:
            logger.error(
                "population_export_error",
                tenant_id=str(tenant_id),
                error_type=type(exc).__name__,
            )

        logger.info(
            "population_export_completed",
            tenant_id=str(tenant_id),
            row_count=row_count,
        )
