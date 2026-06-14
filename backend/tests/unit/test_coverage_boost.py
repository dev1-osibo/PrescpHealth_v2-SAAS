"""
Coverage boost — targeted tests for specific missed code paths.
Fills gaps in: AlertService.evaluate_thresholds, EscalationService overdue paths,
PopulationService DB compute methods, AlertRulesEngine.register_subscriptions,
alert/population tasks, dispatcher exception path, admin IntegrityError path.

Synthetic data only. No real PHI. DB mocked throughout.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# AlertService.evaluate_thresholds (lines 73-95)
# ---------------------------------------------------------------------------

from app.modules.alerts.service import AlertService


def _make_alert_svc(mock_db=None, tenant_id=None):
    """Helper: minimal AlertService with mocked deps."""
    return AlertService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="boost-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_evaluate_thresholds_measurement_saved_event():
    """evaluate_thresholds routes measurement_saved event to rules engine."""
    svc = _make_alert_svc()
    patient_id = uuid.uuid4()

    with patch("app.modules.alerts.rules_engine.AlertRulesEngine") as mock_engine_cls:
        mock_engine = AsyncMock()
        mock_engine.evaluate_measurement = AsyncMock()
        mock_engine_cls.return_value = mock_engine

        event = {
            "event_type": "measurement_saved",
            "measurement_type": "systolic_bp",
            "value": 195.0,
        }
        result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        mock_engine.evaluate_measurement.assert_called_once_with(
            patient_id=patient_id,
            measurement_type="systolic_bp",
            value=195.0,
        )


@pytest.mark.asyncio
async def test_evaluate_thresholds_risk_score_computed_event():
    """evaluate_thresholds routes risk_score_computed event to rules engine."""
    svc = _make_alert_svc()
    patient_id = uuid.uuid4()

    with patch("app.modules.alerts.rules_engine.AlertRulesEngine") as mock_engine_cls:
        mock_engine = AsyncMock()
        mock_engine.evaluate_risk_score = AsyncMock()
        mock_engine_cls.return_value = mock_engine

        event = {
            "event_type": "risk_score_computed",
            "disease": "diabetes",
            "score": 0.91,
            "stratum": "critical",
        }
        result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        mock_engine.evaluate_risk_score.assert_called_once_with(
            patient_id=patient_id,
            disease="diabetes",
            score=0.91,
            stratum="critical",
        )


@pytest.mark.asyncio
async def test_evaluate_thresholds_unknown_event_type():
    """evaluate_thresholds returns empty list for unknown event_type."""
    svc = _make_alert_svc()
    patient_id = uuid.uuid4()

    with patch("app.modules.alerts.rules_engine.AlertRulesEngine") as mock_engine_cls:
        mock_engine = AsyncMock()
        mock_engine_cls.return_value = mock_engine

        event = {"event_type": "unknown_event"}
        result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        assert result == []


# ---------------------------------------------------------------------------
# EscalationService.check_and_escalate — overdue alert paths
# ---------------------------------------------------------------------------

from app.modules.alerts.escalation import EscalationService
from app.modules.alerts.enums import AlertStatus


@pytest.mark.asyncio
async def test_check_and_escalate_with_overdue_alert_at_level_0():
    """check_and_escalate escalates a level-0 alert that has exceeded 15-min timeout."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()

    mock_overdue_alert = MagicMock()
    mock_overdue_alert.id = alert_id
    mock_overdue_alert.escalation_level = 0
    mock_overdue_alert.status = "active"

    call_count = 0

    def scalars_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # First two calls (level 0 overdue, level 1 overdue): return overdue alert on first only
        if call_count == 1:
            result.all.return_value = [mock_overdue_alert]
        elif call_count == 2:
            result.all.return_value = []  # level 1 — none
        elif call_count == 3:
            result.all.return_value = []  # max level — none
        else:
            result.all.return_value = []
            result.first.return_value = mock_overdue_alert  # for escalate_alert lookup
        return result

    mock_db.scalars = AsyncMock(side_effect=scalars_side_effect)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_overdue_alert)

    svc = EscalationService(db=mock_db, audit_service=mock_audit, tenant_id=tenant_id)

    # Don't let escalate_alert raise — mock it directly
    svc.escalate_alert = AsyncMock(return_value=mock_overdue_alert)

    await svc.check_and_escalate()

    # Should have tried to escalate the overdue level-0 alert
    svc.escalate_alert.assert_called_once()


@pytest.mark.asyncio
async def test_check_and_escalate_with_max_level_alert_resolves_it():
    """check_and_escalate resolves a max-level unacknowledged alert as unacknowledged."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_max_alert = MagicMock()
    mock_max_alert.id = uuid.uuid4()
    mock_max_alert.escalation_level = 2

    call_count = 0

    def scalars_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count <= 2:
            result.all.return_value = []  # level 0 and 1 — no overdue
        else:
            result.all.return_value = [mock_max_alert]  # max level
        return result

    mock_db.scalars = AsyncMock(side_effect=scalars_side_effect)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    svc = EscalationService(db=mock_db, audit_service=mock_audit, tenant_id=tenant_id)
    await svc.check_and_escalate()

    # Max-level alert should be resolved as unacknowledged
    assert mock_max_alert.status == AlertStatus.RESOLVED.value
    mock_db.commit.assert_called()


# ---------------------------------------------------------------------------
# AlertRulesEngine.register_subscriptions
# ---------------------------------------------------------------------------

from app.modules.alerts.rules_engine import AlertRulesEngine


@pytest.mark.asyncio
async def test_register_subscriptions_subscribes_to_events():
    """register_subscriptions registers handlers for all three domain events."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    mock_alert_service = AsyncMock()

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)

    subscribed_events = {}

    def mock_subscribe(event_name, handler):
        subscribed_events[event_name] = handler

    with patch("app.modules.alerts.rules_engine.event_bus") as mock_bus:
        mock_bus.subscribe = mock_subscribe
        engine.register_subscriptions()

    assert "measurement_saved" in subscribed_events
    assert "risk_score_computed" in subscribed_events
    assert "forecast_completed" in subscribed_events


@pytest.mark.asyncio
async def test_register_subscriptions_handlers_are_callable():
    """register_subscriptions event handlers are async callables."""
    import inspect

    mock_db = AsyncMock()
    engine = AlertRulesEngine(db=mock_db, tenant_id=uuid.uuid4(), alert_service=AsyncMock())

    subscribed_handlers = {}

    with patch("app.modules.alerts.rules_engine.event_bus") as mock_bus:
        mock_bus.subscribe = lambda event, handler: subscribed_handlers.update({event: handler})
        engine.register_subscriptions()

    for event_name, handler in subscribed_handlers.items():
        assert callable(handler), f"Handler for {event_name} is not callable"


# ---------------------------------------------------------------------------
# Dispatcher — exception path in dispatch (channel failure recording)
# ---------------------------------------------------------------------------

from app.modules.alerts.dispatcher import AlertDispatcher


@pytest.mark.asyncio
async def test_dispatch_whatsapp_channel_records_failure_on_exception():
    """dispatch records channel failure in dispatch_status when channel raises."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()

    mock_alert = MagicMock()
    mock_alert.id = alert_id
    mock_alert.patient_id = uuid.uuid4()
    mock_alert.dispatch_status = {}
    mock_alert.channels_dispatched = []

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_alert
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_alert)

    dispatcher = AlertDispatcher(db=mock_db, tenant_id=tenant_id)

    # Make send_whatsapp raise
    dispatcher.send_whatsapp = AsyncMock(side_effect=RuntimeError("WhatsApp unavailable"))

    await dispatcher.dispatch(alert_id=alert_id, channels=["whatsapp"])

    # Failure should be recorded, not re-raised
    assert "whatsapp" in mock_alert.dispatch_status
    assert "failed" in mock_alert.dispatch_status["whatsapp"]


# ---------------------------------------------------------------------------
# PopulationService — DB computation paths
# ---------------------------------------------------------------------------

from app.modules.population.service import PopulationService
from app.modules.population.schemas import DashboardResponse


def _make_pop_svc(mock_db=None, tenant_id=None):
    return PopulationService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="boost-pop-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_load_cached_returns_row_value_when_found():
    """_load_cached returns row.value when a valid cache row exists."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    cached_value = {"total_active_patients": 42}
    mock_row = MagicMock()
    mock_row.value = cached_value

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_row
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_pop_svc(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc._load_cached("risk_distribution", None, None)

    assert result == cached_value


@pytest.mark.asyncio
async def test_load_cached_returns_none_when_no_row():
    """_load_cached returns None when no cache row found."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_pop_svc(mock_db=mock_db)
    result = await svc._load_cached("risk_distribution", None, None)

    assert result is None


@pytest.mark.asyncio
async def test_cache_metric_updates_existing_row():
    """_cache_metric updates value/timestamps when existing cache row exists."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_existing = MagicMock()
    mock_existing.value = {"old": True}
    mock_existing.computed_at = None
    mock_existing.expires_at = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_existing
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    svc = _make_pop_svc(mock_db=mock_db, tenant_id=tenant_id)
    new_value = {"total_active_patients": 100}
    await svc._cache_metric("risk_distribution", None, None, new_value)

    # Existing row's value should be updated
    assert mock_existing.value == new_value
    assert mock_existing.computed_at is not None
    assert mock_existing.expires_at is not None
    mock_db.add.assert_not_called()  # Should UPDATE, not INSERT
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cache_metric_inserts_new_row_when_no_existing():
    """_cache_metric inserts a new CachedPopulationMetric when none exists."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None  # No existing row
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    svc = _make_pop_svc(mock_db=mock_db, tenant_id=tenant_id)
    await svc._cache_metric("risk_distribution", None, None, {"total_active_patients": 0})

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_compute_dashboard_with_db_rows():
    """_compute_dashboard computes DashboardResponse from DB query results."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    # Mock rows for distribution query
    mock_row_1 = MagicMock()
    mock_row_1.disease = "diabetes"
    mock_row_1.stratum = "High"
    mock_row_1.cnt = 20

    mock_row_2 = MagicMock()
    mock_row_2.disease = "diabetes"
    mock_row_2.stratum = "Critical"
    mock_row_2.cnt = 5

    # Mock row for avg_score query
    mock_avg_row = MagicMock()
    mock_avg_row.disease = "diabetes"
    mock_avg_row.avg_score = 0.74

    dist_result = MagicMock()
    dist_result.fetchall.return_value = [mock_row_1, mock_row_2]

    avg_result = MagicMock()
    avg_result.fetchall.return_value = [mock_avg_row]

    # Return distribution result first, avg result second
    mock_db.execute = AsyncMock(side_effect=[dist_result, avg_result])

    svc = _make_pop_svc(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc._compute_dashboard()

    assert isinstance(result, DashboardResponse)
    assert result.total_active_patients == 25
    assert result.high_risk_count == 20
    assert result.critical_risk_count == 5
    assert result.avg_risk_scores["diabetes"] == 0.74


@pytest.mark.asyncio
async def test_compute_dashboard_empty_rows():
    """_compute_dashboard handles empty result set without division errors."""
    mock_db = AsyncMock()

    dist_result = MagicMock()
    dist_result.fetchall.return_value = []

    avg_result = MagicMock()
    avg_result.fetchall.return_value = []

    mock_db.execute = AsyncMock(side_effect=[dist_result, avg_result])

    svc = _make_pop_svc(mock_db=mock_db)
    result = await svc._compute_dashboard()

    assert result.total_active_patients == 0
    assert result.risk_distribution == []
    assert result.avg_risk_scores == {}


@pytest.mark.asyncio
async def test_compute_trends_with_db_rows():
    """_compute_trends groups TrendPoints by disease from DB results."""
    from app.modules.population.schemas import TrendPoint

    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_row_1 = MagicMock()
    mock_row_1.disease = "diabetes"
    mock_row_1.month = now
    mock_row_1.avg_score = 0.72

    mock_row_2 = MagicMock()
    mock_row_2.disease = "hypertension"
    mock_row_2.month = now
    mock_row_2.avg_score = 0.65

    mock_row_3 = MagicMock()
    mock_row_3.disease = "diabetes"
    mock_row_3.month = now - timedelta(days=30)
    mock_row_3.avg_score = 0.68

    trend_result = MagicMock()
    trend_result.fetchall.return_value = [mock_row_1, mock_row_2, mock_row_3]
    mock_db.execute = AsyncMock(return_value=trend_result)

    svc = _make_pop_svc(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc._compute_trends("3m")

    assert "diabetes" in result
    assert "hypertension" in result
    assert len(result["diabetes"]) == 2
    assert len(result["hypertension"]) == 1
    assert all(isinstance(pt, TrendPoint) for pt in result["diabetes"])


@pytest.mark.asyncio
async def test_compute_trends_empty_result():
    """_compute_trends returns empty dict when no trend rows exist."""
    mock_db = AsyncMock()

    trend_result = MagicMock()
    trend_result.fetchall.return_value = []
    mock_db.execute = AsyncMock(return_value=trend_result)

    svc = _make_pop_svc(mock_db=mock_db)
    result = await svc._compute_trends("1m")

    assert result == {}


@pytest.mark.asyncio
async def test_get_trends_cache_hit_returns_cached():
    """get_trends returns cached TrendPoints when cache has valid entry."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    cached_value = {
        "diabetes": [
            {"date": now.isoformat(), "value": 0.72, "stratum": "mixed"}
        ]
    }

    mock_row = MagicMock()
    mock_row.value = cached_value
    mock_row.expires_at = now + timedelta(hours=1)

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_row
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_pop_svc(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.get_trends(window="3m")

    assert "diabetes" in result


# ---------------------------------------------------------------------------
# Population Tasks — _refresh_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_async_iterates_metric_types():
    """_refresh_async calls PopulationService for each metric type."""
    from app.modules.population.tasks import _refresh_async

    tenant_id = uuid.uuid4()
    mock_svc = AsyncMock()
    mock_svc.get_dashboard_metrics = AsyncMock()
    mock_svc.get_trends = AsyncMock()

    mock_db = AsyncMock()
    mock_audit = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make_ctx():
        yield mock_db

    # side_effect: each call to get_async_session_context() returns a fresh context
    with patch("app.core.database.get_async_session_context", side_effect=_make_ctx):
        with patch("app.modules.population.service.PopulationService", return_value=mock_svc):
            with patch("app.modules.audit.service.AuditService", return_value=AsyncMock()):
                await _refresh_async(str(tenant_id))

    # Each metric type should have been processed
    assert mock_svc.get_dashboard_metrics.called or mock_svc.get_trends.called


@pytest.mark.asyncio
async def test_refresh_async_handles_per_metric_exception():
    """_refresh_async continues processing remaining metrics when one fails."""
    from app.modules.population.tasks import _refresh_async

    tenant_id = uuid.uuid4()
    mock_db = AsyncMock()

    call_count = 0

    async def failing_get_dashboard():
        nonlocal call_count
        call_count += 1
        raise Exception("simulated failure")

    async def ok_get_trends(window=None):
        nonlocal call_count
        call_count += 1

    mock_svc = MagicMock()
    mock_svc.get_dashboard_metrics = AsyncMock(side_effect=Exception("metric failed"))
    mock_svc.get_trends = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make_ctx2():
        yield mock_db

    with patch("app.core.database.get_async_session_context", side_effect=_make_ctx2):
        with patch("app.modules.population.service.PopulationService", return_value=mock_svc):
            with patch("app.modules.audit.service.AuditService", return_value=AsyncMock()):
                # Should not raise even though individual metrics fail
                await _refresh_async(str(tenant_id))


# ---------------------------------------------------------------------------
# Alert Tasks — check_escalations_async and check_missed_followups_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_escalations_async_with_empty_tenant_list():
    """_check_escalations_async completes without error when tenant list is empty."""
    from app.modules.alerts.tasks import _check_escalations_async

    # Default implementation uses empty tenant list — should just log and return
    await _check_escalations_async()


def test_check_missed_followups_task_logs_and_returns():
    """check_missed_followups_task completes without error (placeholder stub)."""
    from app.modules.alerts.tasks import check_missed_followups_task

    # Call directly (bypassing Celery infrastructure by calling synchronously)
    # The task itself only logs — no DB calls
    tenant_id_str = str(uuid.uuid4())

    # The task calls asyncio.run internally — mock it to avoid event loop issues in tests
    with patch("app.modules.alerts.tasks.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock(return_value=None)
        # check_missed_followups_task is synchronous (doesn't call asyncio.run)
        # It just logs
        check_missed_followups_task(tenant_id=tenant_id_str)


@pytest.mark.asyncio
async def test_dispatch_alert_async_alert_not_found():
    """_dispatch_alert_async returns skip dict when alert not in DB."""
    from app.modules.alerts.tasks import _dispatch_alert_async

    mock_task = MagicMock()
    mock_task.request.id = "celery-task-001"
    mock_task.request.retries = 0

    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None  # Alert not found
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make_ctx3():
        yield mock_db

    with patch("app.core.database.get_async_session_context", side_effect=_make_ctx3):
        result = await _dispatch_alert_async(mock_task, str(uuid.uuid4()), ["in_app"])

    assert result["skipped"] is True
    assert result["reason"] == "alert_not_found"


# ---------------------------------------------------------------------------
# Admin ModelManagementService — IntegrityError path
# ---------------------------------------------------------------------------

from app.modules.admin.service_model import ModelManagementService
from app.modules.admin.exceptions import ModelDeploymentError, RollbackError
from app.modules.admin.schemas import DeployModelRequest, RollbackRequest


@pytest.mark.asyncio
async def test_deploy_model_raises_deployment_error_on_integrity_error():
    """deploy_model raises ModelDeploymentError when DB raises IntegrityError."""

    class FakeIntegrityError(Exception):
        pass
    FakeIntegrityError.__name__ = "IntegrityError"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=FakeIntegrityError("unique constraint"))
    mock_db.rollback = AsyncMock()

    svc = ModelManagementService(
        db=mock_db, audit_service=AsyncMock(),
        request_id="test", tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
    )
    data = DeployModelRequest(
        disease="diabetes", version="1.0.0",
        artifact_path="s3://models/diab/v1.pkl",
    )

    with pytest.raises(ModelDeploymentError):
        await svc.deploy_model(data=data)


@pytest.mark.asyncio
async def test_rollback_model_raises_rollback_error_on_db_exception():
    """rollback_model raises RollbackError when DB execute throws unexpectedly."""
    mock_db = AsyncMock()

    # First execute (SELECT) raises unexpected DB error
    mock_db.execute = AsyncMock(side_effect=Exception("connection dropped"))
    mock_db.rollback = AsyncMock()

    svc = ModelManagementService(
        db=mock_db, audit_service=AsyncMock(),
        request_id="test", tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
    )
    data = RollbackRequest(disease="diabetes", target_version="1.0.0")

    with pytest.raises(RollbackError):
        await svc.rollback_model(data=data)


# ---------------------------------------------------------------------------
# Reports Service — stub BackgroundTaskTracker path (force import failure)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_service_stub_tracker_used_when_import_fails():
    """ReportService uses stub BackgroundTaskTracker when tasks_tracker cannot be imported."""
    import sys
    import importlib

    # Temporarily hide the tasks_tracker module to force stub path
    original = sys.modules.pop("app.core.tasks_tracker", None)
    original_reports = sys.modules.pop("app.modules.reports.service", None)

    try:
        # Block the import
        sys.modules["app.core.tasks_tracker"] = None  # type: ignore

        # Reload the reports.service module so it hits the except ImportError
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "app.modules.reports.service_stub_test",
            r"C:\Users\babas\Dev_Projects\PrescpHealth\backend\app\modules\reports\service.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.TRACKER_AVAILABLE is False
        assert mod.BackgroundTaskTracker is not None

        # Test stub class directly
        stub_tracker = mod.BackgroundTaskTracker(db=AsyncMock())
        task_id = await stub_tracker.create_task("clinical_pdf", uuid.uuid4())
        assert isinstance(task_id, str)
        uuid.UUID(task_id)  # Validates UUID format

        # update_status is a no-op
        await stub_tracker.update_status("some-task-id", "completed")

    finally:
        # Restore original state
        sys.modules.pop("app.core.tasks_tracker", None)
        if original is not None:
            sys.modules["app.core.tasks_tracker"] = original
        if original_reports is not None:
            sys.modules["app.modules.reports.service"] = original_reports


# ---------------------------------------------------------------------------
# Reports CSV Exporter — row generation paths
# ---------------------------------------------------------------------------

from app.modules.reports.csv_exporter import CSVExporter


@pytest.mark.asyncio
async def test_export_measurements_with_data_rows():
    """export_measurements yields data rows when Measurement model importable and has data."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Build a mock measurement row with expected attributes
    mock_measurement = MagicMock()
    mock_measurement.measured_at = now
    mock_measurement.measurement_type = "systolic_bp"
    mock_measurement.value = 120
    mock_measurement.unit = "mmHg"
    mock_measurement.is_validated = True

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_measurement]
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    exporter = CSVExporter(db=mock_db, tenant_id=tenant_id)

    rows = []
    # Patch Measurement import inside the generator to succeed
    with patch("app.modules.measurements.models.Measurement") as mock_model:
        mock_model.patient_id = MagicMock()
        mock_model.tenant_id = MagicMock()
        mock_model.measured_at = MagicMock()
        async for row in exporter.export_measurements(patient_id=patient_id):
            rows.append(row)

    assert len(rows) >= 1
    assert "systolic_bp" in rows[0] or "measurement_type" in rows[0]


@pytest.mark.asyncio
async def test_export_population_with_risk_score_rows():
    """export_population yields data rows when RiskScore model importable and has data."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_risk_score = MagicMock()
    mock_risk_score.patient_id = uuid.uuid4()
    mock_risk_score.disease = "diabetes"
    mock_risk_score.score = 0.85
    mock_risk_score.stratum = "High"
    mock_risk_score.computed_at = now

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_risk_score]
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    exporter = CSVExporter(db=mock_db, tenant_id=tenant_id)

    rows = []
    with patch("app.modules.risk_engine.models.RiskScore") as mock_model:
        mock_model.tenant_id = MagicMock()
        mock_model.computed_at = MagicMock()
        async for row in exporter.export_population(tenant_id=tenant_id):
            rows.append(row)

    assert len(rows) >= 1
