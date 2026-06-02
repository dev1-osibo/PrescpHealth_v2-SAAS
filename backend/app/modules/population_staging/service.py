"""
PrescpHealth Backend — Population Analytics Service.

Computes and caches population-level risk metrics per tenant. All DB queries
are tenant-scoped via tenant_id. On query failure a safe stub is returned so
the API stays functional before the risk_scores table exists.

PHI safety: logs contain tenant_id/request_id UUIDs only — never scores,
            names, or clinical values.
"""
import uuid
import structlog
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.population_staging.exceptions import ComputationError
from app.modules.population_staging.models import CachedPopulationMetric
from app.modules.population_staging.schemas import (
    DashboardResponse, RiskDistributionItem, TrendPoint, WatchlistPatient,
)

logger = structlog.get_logger(__name__)

_VALID_WINDOWS = {"1m", "3m", "6m", "12m"}
_WINDOW_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}
_CACHE_TTL_HOURS = 1


class PopulationService:
    """
    Population analytics for a single tenant per request.
    Instantiated with injected DB session and audit service.
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
            audit_service: AuditService for mutation logging.
            request_id: HTTP correlation ID included in all log entries.
            tenant_id: Tenant scope enforced on all queries.
            user_id: Authenticated user recorded in audit events.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_dashboard_metrics(self) -> DashboardResponse:
        """
        Return aggregate dashboard metrics, served from cache when available.
        Falls back to computed-from-DB then stub on failure.
        Audit-logs: "population_dashboard_accessed".
        """
        await self.audit_service.log_audit(
            action="population_dashboard_accessed",
            resource_type="population_metric",
            resource_id=str(self.tenant_id),
            changes={},
        )
        cached = await self._safe_load_cache("risk_distribution", None, None)
        if cached:
            return DashboardResponse(**cached)

        result = await self._safe_compute(self._compute_dashboard, self._stub_dashboard)
        await self._safe_cache("risk_distribution", None, None, result.model_dump(mode="json"))
        logger.info("population_dashboard_accessed", tenant_id=str(self.tenant_id),
                    request_id=self.request_id)
        return result

    async def get_watchlist(
        self, limit: int = 50, offset: int = 0, sort_by: str = "score",
    ) -> list[WatchlistPatient]:
        """
        Return paginated High/Critical risk patients ordered by score DESC.
        DB errors return an empty list stub.
        Audit-logs: "watchlist_accessed".

        Args:
            limit: Page size (max enforced at router layer).
            offset: Pagination offset.
            sort_by: Sort column name (currently only 'score' supported).
        """
        await self.audit_service.log_audit(
            action="watchlist_accessed",
            resource_type="population_metric",
            resource_id=str(self.tenant_id),
            changes={"limit": limit, "offset": offset},
        )
        try:
            rows = await self._query_watchlist(limit=limit, offset=offset)
        except Exception as exc:
            logger.warning("population_watchlist_query_failed", error_type=type(exc).__name__,
                           tenant_id=str(self.tenant_id), request_id=self.request_id)
            rows = []
        logger.info("watchlist_accessed", tenant_id=str(self.tenant_id),
                    request_id=self.request_id)
        return rows

    async def get_trends(self, window: str = "3m") -> dict[str, list[TrendPoint]]:
        """
        Return monthly avg risk scores per disease for the given window.
        Validates window, tries cache, falls back to DB then stub.
        Audit-logs: "trends_accessed".

        Args:
            window: Rolling window code — one of '1m', '3m', '6m', '12m'.

        Raises:
            ComputationError: If window is not a valid code.
        """
        if window not in _VALID_WINDOWS:
            raise ComputationError(
                f"Invalid window '{window}'; must be one of {sorted(_VALID_WINDOWS)}"
            )
        await self.audit_service.log_audit(
            action="trends_accessed",
            resource_type="population_metric",
            resource_id=str(self.tenant_id),
            changes={"window": window},
        )
        cached = await self._safe_load_cache("trend", None, window)
        if cached:
            logger.info("trends_accessed", tenant_id=str(self.tenant_id),
                        request_id=self.request_id)
            return {d: [TrendPoint(**pt) for pt in pts] for d, pts in cached.items()}

        async def _compute():
            return await self._compute_trends(window)

        trends = await self._safe_compute(_compute, lambda: {})
        serialised = {d: [pt.model_dump(mode="json") for pt in pts] for d, pts in trends.items()}
        await self._safe_cache("trend", None, window, serialised)
        logger.info("trends_accessed", tenant_id=str(self.tenant_id), request_id=self.request_id)
        return trends

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def _safe_load_cache(
        self, metric_type: str, disease: str | None, window: str | None,
    ) -> dict | None:
        """Load cached metric if not expired; return None on miss or error."""
        try:
            return await self._load_cached(metric_type, disease, window)
        except Exception as exc:
            logger.warning("population_cache_read_failed", error_type=type(exc).__name__,
                           tenant_id=str(self.tenant_id))
            return None

    async def _safe_cache(
        self, metric_type: str, disease: str | None, window: str | None, value: dict,
    ) -> None:
        """Best-effort cache write — logs warning on failure, never raises."""
        try:
            await self._cache_metric(metric_type, disease, window, value)
        except Exception as exc:
            logger.warning("population_cache_write_failed", error_type=type(exc).__name__,
                           tenant_id=str(self.tenant_id))

    async def _safe_compute(self, compute_fn, stub_fn):
        """Run compute_fn; on any exception log a warning and return stub_fn()."""
        try:
            return await compute_fn()
        except Exception as exc:
            logger.warning("population_compute_failed", error_type=type(exc).__name__,
                           tenant_id=str(self.tenant_id), request_id=self.request_id)
            return stub_fn()

    async def _load_cached(
        self, metric_type: str, disease: str | None, window: str | None,
    ) -> dict | None:
        """Query cache table for a valid (non-expired) metric entry."""
        now = datetime.now(timezone.utc)
        conds = [
            CachedPopulationMetric.tenant_id == self.tenant_id,
            CachedPopulationMetric.metric_type == metric_type,
            CachedPopulationMetric.expires_at > now,
            CachedPopulationMetric.disease.is_(None) if disease is None
            else CachedPopulationMetric.disease == disease,
            CachedPopulationMetric.time_window.is_(None) if window is None
            else CachedPopulationMetric.time_window == window,
        ]
        row = (await self.db.scalars(
            select(CachedPopulationMetric).where(and_(*conds)).limit(1)
        )).first()
        return row.value if row else None

    async def _cache_metric(
        self, metric_type: str, disease: str | None, window: str | None, value: dict,
    ) -> None:
        """Upsert a computed metric into the cache with a 1-hour TTL."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=_CACHE_TTL_HOURS)
        conds = [
            CachedPopulationMetric.tenant_id == self.tenant_id,
            CachedPopulationMetric.metric_type == metric_type,
            CachedPopulationMetric.disease.is_(None) if disease is None
            else CachedPopulationMetric.disease == disease,
            CachedPopulationMetric.time_window.is_(None) if window is None
            else CachedPopulationMetric.time_window == window,
        ]
        existing = (await self.db.scalars(
            select(CachedPopulationMetric).where(and_(*conds)).limit(1)
        )).first()
        if existing:
            existing.value = value
            existing.computed_at = now
            existing.expires_at = expires_at
        else:
            self.db.add(CachedPopulationMetric(
                tenant_id=self.tenant_id, metric_type=metric_type,
                disease=disease, time_window=window,
                value=value, computed_at=now, expires_at=expires_at,
            ))
        await self.db.commit()

    # ------------------------------------------------------------------
    # DB computation helpers
    # ------------------------------------------------------------------

    async def _compute_dashboard(self) -> DashboardResponse:
        """Compute dashboard metrics live from the risk_scores table."""
        tid = str(self.tenant_id)
        rows = (await self.db.execute(
            text("SELECT disease, stratum, COUNT(DISTINCT patient_id) AS cnt "
                 "FROM risk_scores WHERE tenant_id = :tid GROUP BY disease, stratum"),
            {"tid": tid},
        )).fetchall()
        total = sum(r.cnt for r in rows)
        distribution = [
            RiskDistributionItem(
                disease=r.disease, stratum=r.stratum, count=r.cnt,
                percentage=round((r.cnt / total * 100) if total else 0.0, 2),
            ) for r in rows
        ]
        high = sum(r.cnt for r in rows if r.stratum == "High")
        critical = sum(r.cnt for r in rows if r.stratum == "Critical")
        avg_rows = (await self.db.execute(
            text("SELECT disease, AVG(score) AS avg_score FROM risk_scores "
                 "WHERE tenant_id = :tid GROUP BY disease"),
            {"tid": tid},
        )).fetchall()
        avg_scores = {r.disease: round(float(r.avg_score), 4) for r in avg_rows}
        return DashboardResponse(
            total_active_patients=total, risk_distribution=distribution,
            high_risk_count=high, critical_risk_count=critical,
            avg_risk_scores=avg_scores, last_updated=datetime.now(timezone.utc),
        )

    async def _query_watchlist(self, limit: int, offset: int) -> list[WatchlistPatient]:
        """Query risk_scores for High/Critical patients, ordered by score DESC."""
        rows = (await self.db.execute(
            text("SELECT patient_id, disease, score, stratum, computed_at "
                 "FROM risk_scores WHERE tenant_id = :tid "
                 "AND stratum IN ('High', 'Critical') "
                 "ORDER BY score DESC LIMIT :lim OFFSET :off"),
            {"tid": str(self.tenant_id), "lim": limit, "off": offset},
        )).fetchall()
        return [WatchlistPatient(patient_id=uuid.UUID(str(r.patient_id)), disease=r.disease,
                                 score=float(r.score), stratum=r.stratum,
                                 computed_at=r.computed_at) for r in rows]

    async def _compute_trends(self, window: str) -> dict[str, list[TrendPoint]]:
        """Compute monthly avg risk score per disease for the given window."""
        months = _WINDOW_MONTHS[window]
        rows = (await self.db.execute(
            text("SELECT disease, DATE_TRUNC('month', computed_at) AS month, "
                 "AVG(score) AS avg_score FROM risk_scores "
                 "WHERE tenant_id = :tid "
                 "AND computed_at >= NOW() - make_interval(months => :months) "
                 "GROUP BY disease, month ORDER BY disease, month"),
            {"tid": str(self.tenant_id), "months": months},
        )).fetchall()
        trends: dict[str, list[TrendPoint]] = {}
        for r in rows:
            trends.setdefault(r.disease, []).append(
                TrendPoint(date=r.month, value=round(float(r.avg_score), 4), stratum="mixed")
            )
        return trends

    # ------------------------------------------------------------------
    # Stubs (returned when DB is unavailable)
    # ------------------------------------------------------------------

    def _stub_dashboard(self) -> DashboardResponse:
        """Return an empty DashboardResponse stub when DB is unavailable."""
        return DashboardResponse(
            total_active_patients=0, risk_distribution=[],
            high_risk_count=0, critical_risk_count=0,
            avg_risk_scores={}, last_updated=datetime.now(timezone.utc),
        )
