"""
PrescpHealth Backend — Population Analytics SQLAlchemy Models.

Defines the CachedPopulationMetric table used to store pre-computed
population metrics with a 1-hour TTL. Computed metrics are stored as
JSONB and keyed by (tenant_id, metric_type, disease, time_window).

HIPAA: Cached metrics contain only aggregate counts/scores — no individual
       patient PHI. Cache rows are RLS-scoped to tenant_id.
Row-Level Security is enforced via the migration (0016_population_metrics_tables.py).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin


class CachedPopulationMetric(TenantMixin, Base):
    """
    Pre-computed, tenant-scoped population metric with expiry.

    Metrics are keyed by (tenant_id, metric_type, disease, time_window).
    The value column stores the fully serialised result as JSONB so it can
    be returned directly to the API without re-computation during the TTL.

    Fields:
        metric_type:  Logical name of the metric (e.g. 'risk_distribution').
        disease:      Disease filter; NULL means the metric spans all diseases.
        time_window:  Rolling window code ('1m', '3m', '6m', '12m'); NULL for
                      point-in-time metrics.
        value:        Serialised metric payload (aggregate data only — no PHI).
        computed_at:  When the value was last computed.
        expires_at:   After this timestamp the cache entry is considered stale.
    """

    __tablename__ = "cached_population_metrics"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Metric classification columns used as the composite cache key
    metric_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="e.g. 'risk_distribution', 'watchlist_count', 'prevalence', 'avg_risk_score'",
    )
    disease: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Disease filter; NULL means all diseases",
    )
    time_window: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Rolling window: '1m', '3m', '6m', '12m'; NULL for point-in-time",
    )

    # Computed payload — aggregate statistics only; no individual patient data
    value: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Serialised metric result (aggregate only — no PHI)",
    )

    # Cache lifecycle timestamps
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When this metric value was computed (UTC)",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Cache entry is stale after this timestamp (UTC)",
    )

    __table_args__ = (
        # Covering index for cache-key lookups
        Index(
            "ix_pop_metric_lookup",
            "tenant_id",
            "metric_type",
            "disease",
            "time_window",
        ),
    )
