"""
PrescpHealth Backend — Population Analytics Pydantic Schemas.

All response models follow the standard envelope:
    {"success": true, "data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}

PHI note: schemas expose only aggregate data (counts, averages, strata).
          Patient UUIDs appear in WatchlistPatient but no free-text PHI is included.
"""
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Dashboard schemas
# ---------------------------------------------------------------------------

class RiskDistributionItem(BaseModel):
    """A single cell in the risk distribution matrix (disease × stratum)."""

    disease: str
    stratum: str
    count: int
    percentage: float


class DashboardResponse(BaseModel):
    """Aggregated population health metrics for the clinical dashboard."""

    total_active_patients: int
    risk_distribution: list[RiskDistributionItem]
    high_risk_count: int
    critical_risk_count: int
    avg_risk_scores: dict[str, float]  # disease -> average score across all strata
    last_updated: datetime


class DashboardEnvelope(BaseModel):
    """Standard envelope wrapping DashboardResponse."""

    success: bool = True
    data: DashboardResponse
    meta: dict


# ---------------------------------------------------------------------------
# Watchlist schemas
# ---------------------------------------------------------------------------

class WatchlistPatient(BaseModel):
    """A single patient entry on the High/Critical watchlist."""

    patient_id: uuid.UUID
    disease: str
    score: float
    stratum: str
    computed_at: datetime


class WatchlistResponse(BaseModel):
    """Standard envelope wrapping a paginated watchlist."""

    success: bool = True
    data: list[WatchlistPatient]
    meta: dict  # keys: total, limit, offset, request_id, timestamp


# ---------------------------------------------------------------------------
# Trends schemas
# ---------------------------------------------------------------------------

class TrendPoint(BaseModel):
    """A single data point in a risk score trend series."""

    date: datetime
    value: float  # average risk score for this period
    stratum: str  # dominant stratum for the period


class TrendsResponse(BaseModel):
    """Standard envelope wrapping trend data keyed by disease."""

    success: bool = True
    data: dict[str, list[TrendPoint]]  # disease -> ordered list of TrendPoints
    meta: dict  # keys: window, request_id, timestamp
