"""
Tests for app.modules.population — exceptions, schemas, models, and service.

All tests use synthetic data only. No real PHI. DB is mocked.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

from app.modules.population.exceptions import (
    PopulationError,
    MetricNotFoundError,
    ComputationError,
)


def test_population_error_base():
    """PopulationError stores message and is an Exception."""
    err = PopulationError("synthetic population error")
    assert err.message == "synthetic population error"
    assert isinstance(err, Exception)


def test_population_error_default_message():
    """PopulationError default message when none provided."""
    err = PopulationError()
    assert "population" in str(err).lower()


def test_metric_not_found_error():
    """MetricNotFoundError includes metric_type in message."""
    err = MetricNotFoundError("risk_distribution")
    assert "risk_distribution" in str(err)
    assert isinstance(err, PopulationError)


def test_computation_error_custom_detail():
    """ComputationError stores detail string."""
    err = ComputationError("invalid window code")
    assert "invalid window code" in str(err)
    assert isinstance(err, PopulationError)


def test_computation_error_default():
    """ComputationError uses default message."""
    err = ComputationError()
    assert "computation" in str(err).lower()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

from app.modules.population.schemas import (
    RiskDistributionItem,
    DashboardResponse,
    DashboardEnvelope,
    WatchlistPatient,
    WatchlistResponse,
    TrendPoint,
    TrendsResponse,
)


def test_risk_distribution_item_valid():
    """RiskDistributionItem stores disease, stratum, count, percentage."""
    item = RiskDistributionItem(
        disease="diabetes", stratum="High", count=42, percentage=15.3
    )
    assert item.disease == "diabetes"
    assert item.stratum == "High"
    assert item.count == 42
    assert item.percentage == 15.3


def test_dashboard_response_valid():
    """DashboardResponse serializes with all required fields."""
    now = datetime.now(timezone.utc)
    item = RiskDistributionItem(disease="hypertension", stratum="Moderate", count=10, percentage=5.0)
    resp = DashboardResponse(
        total_active_patients=200,
        risk_distribution=[item],
        high_risk_count=30,
        critical_risk_count=5,
        avg_risk_scores={"diabetes": 0.62},
        last_updated=now,
    )
    assert resp.total_active_patients == 200
    assert resp.high_risk_count == 30
    assert resp.avg_risk_scores["diabetes"] == 0.62


def test_dashboard_response_empty():
    """DashboardResponse accepts empty distribution list."""
    now = datetime.now(timezone.utc)
    resp = DashboardResponse(
        total_active_patients=0,
        risk_distribution=[],
        high_risk_count=0,
        critical_risk_count=0,
        avg_risk_scores={},
        last_updated=now,
    )
    assert resp.total_active_patients == 0


def test_dashboard_envelope():
    """DashboardEnvelope wraps DashboardResponse in success envelope."""
    now = datetime.now(timezone.utc)
    data = DashboardResponse(
        total_active_patients=0,
        risk_distribution=[],
        high_risk_count=0,
        critical_risk_count=0,
        avg_risk_scores={},
        last_updated=now,
    )
    env = DashboardEnvelope(data=data, meta={"request_id": "test"})
    assert env.success is True
    assert env.data.total_active_patients == 0


def test_watchlist_patient_valid():
    """WatchlistPatient stores patient_id, disease, score, stratum, computed_at."""
    now = datetime.now(timezone.utc)
    patient_id = uuid.uuid4()
    w = WatchlistPatient(
        patient_id=patient_id,
        disease="diabetes",
        score=0.91,
        stratum="Critical",
        computed_at=now,
    )
    assert w.patient_id == patient_id
    assert w.stratum == "Critical"
    assert w.score == 0.91


def test_watchlist_response_envelope():
    """WatchlistResponse wraps list of WatchlistPatients."""
    now = datetime.now(timezone.utc)
    patients = [
        WatchlistPatient(
            patient_id=uuid.uuid4(),
            disease="hypertension",
            score=0.87,
            stratum="High",
            computed_at=now,
        )
    ]
    resp = WatchlistResponse(data=patients, meta={"total": 1, "limit": 50, "offset": 0})
    assert resp.success is True
    assert len(resp.data) == 1


def test_trend_point_valid():
    """TrendPoint stores date, value, and stratum."""
    now = datetime.now(timezone.utc)
    point = TrendPoint(date=now, value=0.74, stratum="mixed")
    assert point.value == 0.74
    assert point.stratum == "mixed"


def test_trends_response_envelope():
    """TrendsResponse wraps disease-keyed trend data."""
    now = datetime.now(timezone.utc)
    point = TrendPoint(date=now, value=0.65, stratum="moderate")
    resp = TrendsResponse(
        data={"diabetes": [point]},
        meta={"window": "3m", "request_id": "test"},
    )
    assert resp.success is True
    assert "diabetes" in resp.data


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

from app.modules.population.models import CachedPopulationMetric


def test_cached_population_metric_instantiation():
    """CachedPopulationMetric can be instantiated with all fields."""
    now = datetime.now(timezone.utc)
    metric = CachedPopulationMetric(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        metric_type="risk_distribution",
        disease=None,
        time_window=None,
        value={"total_active_patients": 100},
        computed_at=now,
        expires_at=now + timedelta(hours=1),
    )
    assert metric.metric_type == "risk_distribution"
    assert metric.value["total_active_patients"] == 100
    assert metric.disease is None


def test_cached_population_metric_with_disease_and_window():
    """CachedPopulationMetric accepts disease and time_window filters."""
    now = datetime.now(timezone.utc)
    metric = CachedPopulationMetric(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        metric_type="trend",
        disease="diabetes",
        time_window="3m",
        value={"trend": []},
        computed_at=now,
        expires_at=now + timedelta(hours=1),
    )
    assert metric.disease == "diabetes"
    assert metric.time_window == "3m"


# ---------------------------------------------------------------------------
# Population Service
# ---------------------------------------------------------------------------

from app.modules.population.service import PopulationService


def _make_population_service(mock_db=None, tenant_id=None, user_id=None):
    """Helper: build a PopulationService with mock dependencies."""
    return PopulationService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-pop-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_get_trends_invalid_window():
    """get_trends raises ComputationError for invalid window code."""
    svc = _make_population_service()

    with pytest.raises(ComputationError, match="Invalid window"):
        await svc.get_trends(window="99m")


@pytest.mark.asyncio
async def test_get_trends_valid_window_stub():
    """get_trends returns empty dict when DB is unavailable (stub path)."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    # Cache miss: scalars raises
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    # DB compute fails: execute raises
    mock_db.execute = AsyncMock(side_effect=Exception("no risk_scores table"))
    mock_db.commit = AsyncMock()

    svc = _make_population_service(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.get_trends(window="3m")

    # Should return empty dict from stub path
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_trends_all_valid_windows():
    """get_trends accepts all 4 valid window codes without raising."""
    mock_db = AsyncMock()

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.execute = AsyncMock(side_effect=Exception("no table"))
    mock_db.commit = AsyncMock()

    svc = _make_population_service(mock_db=mock_db)

    for window in ["1m", "3m", "6m", "12m"]:
        result = await svc.get_trends(window=window)
        assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_dashboard_metrics_cache_hit():
    """get_dashboard_metrics returns cached result when cache is valid."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    cached_value = {
        "total_active_patients": 50,
        "risk_distribution": [],
        "high_risk_count": 10,
        "critical_risk_count": 2,
        "avg_risk_scores": {},
        "last_updated": now.isoformat(),
    }

    mock_cached_metric = MagicMock()
    mock_cached_metric.value = cached_value
    mock_cached_metric.expires_at = now + timedelta(hours=1)

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_cached_metric
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = PopulationService(
        db=mock_db,
        audit_service=mock_audit,
        request_id="test",
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
    )

    result = await svc.get_dashboard_metrics()

    assert result.total_active_patients == 50
    mock_audit.log_audit.assert_called_once()


@pytest.mark.asyncio
async def test_get_dashboard_metrics_cache_miss_stub():
    """get_dashboard_metrics returns stub response when DB is unavailable."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()

    # Cache miss
    mock_scalars_empty = MagicMock()
    mock_scalars_empty.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars_empty)

    # DB compute fails
    mock_db.execute = AsyncMock(side_effect=Exception("no risk_scores table"))
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    svc = PopulationService(
        db=mock_db,
        audit_service=mock_audit,
        request_id="test",
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
    )

    result = await svc.get_dashboard_metrics()

    # Stub returns zeroed response
    assert result.total_active_patients == 0
    assert result.risk_distribution == []


@pytest.mark.asyncio
async def test_get_watchlist_returns_empty_on_db_error():
    """get_watchlist returns empty list when DB query fails."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_db.execute = AsyncMock(side_effect=Exception("db connection failed"))

    svc = PopulationService(
        db=mock_db,
        audit_service=mock_audit,
        request_id="test",
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
    )

    result = await svc.get_watchlist(limit=10, offset=0)

    assert result == []
    mock_audit.log_audit.assert_called_once()


@pytest.mark.asyncio
async def test_get_watchlist_returns_patients():
    """get_watchlist returns WatchlistPatient records on success."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    patient_id = uuid.uuid4()

    mock_row = MagicMock()
    mock_row.patient_id = str(patient_id)
    mock_row.disease = "diabetes"
    mock_row.score = 0.91
    mock_row.stratum = "Critical"
    mock_row.computed_at = now

    mock_execute_result = MagicMock()
    mock_execute_result.fetchall.return_value = [mock_row]
    mock_db.execute = AsyncMock(return_value=mock_execute_result)

    svc = PopulationService(
        db=mock_db,
        audit_service=mock_audit,
        request_id="test",
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
    )

    result = await svc.get_watchlist(limit=10, offset=0)

    assert len(result) == 1
    assert result[0].stratum == "Critical"


def test_stub_dashboard_returns_zeroed_response():
    """_stub_dashboard returns a valid empty DashboardResponse."""
    svc = _make_population_service()
    stub = svc._stub_dashboard()

    assert isinstance(stub, DashboardResponse)
    assert stub.total_active_patients == 0
    assert stub.risk_distribution == []
    assert stub.high_risk_count == 0
    assert stub.critical_risk_count == 0


@pytest.mark.asyncio
async def test_safe_compute_returns_stub_on_exception():
    """_safe_compute returns stub_fn() result when compute_fn raises."""
    svc = _make_population_service()

    async def failing_fn():
        raise Exception("simulated failure")

    def stub_fn():
        return {"stub": True}

    result = await svc._safe_compute(failing_fn, stub_fn)
    assert result == {"stub": True}


@pytest.mark.asyncio
async def test_safe_load_cache_returns_none_on_exception():
    """_safe_load_cache returns None when DB raises."""
    mock_db = AsyncMock()
    mock_db.scalars = AsyncMock(side_effect=Exception("db error"))

    svc = _make_population_service(mock_db=mock_db)
    result = await svc._safe_load_cache("risk_distribution", None, None)
    assert result is None


@pytest.mark.asyncio
async def test_safe_cache_does_not_raise_on_exception():
    """_safe_cache silently logs warning and does not raise on DB failure."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock(side_effect=Exception("commit failed"))

    svc = _make_population_service(mock_db=mock_db)

    # Should not raise
    await svc._safe_cache("risk_distribution", None, None, {"data": "value"})
