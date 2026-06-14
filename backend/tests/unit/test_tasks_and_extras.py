"""
PrescpHealth Backend — Unit Tests: Tasks and Service Extras.

Supplemental tests targeting remaining uncovered statements in:
  - app.modules.alerts.service (evaluate_thresholds)
  - app.modules.alerts.tasks (simple tasks, async helpers)
  - app.modules.reports.tasks (async PDF task helpers)
  - app.modules.population.tasks (async refresh helper)
  - app.modules.alerts.rules_engine (_load_thresholds, register_subscriptions coverage)
  - app.modules.alerts.escalation (check_and_escalate coverage)

All tests use AsyncMock; no real DB or Celery broker needed.
No PHI in test data — synthetic identifiers only.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uuid() -> uuid.UUID:
    """Return a fresh synthetic UUID."""
    return uuid.uuid4()


def _make_db_mock() -> AsyncMock:
    """Return an AsyncMock satisfying the AsyncSession interface."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.scalars = AsyncMock(return_value=MagicMock(
        all=MagicMock(return_value=[]),
        first=MagicMock(return_value=None),
    ))
    return db


def _make_audit_mock() -> AsyncMock:
    """Return an AsyncMock satisfying the AuditService interface."""
    audit = AsyncMock()
    audit.log_audit = AsyncMock()
    return audit


# ---------------------------------------------------------------------------
# AlertService.evaluate_thresholds tests
# ---------------------------------------------------------------------------

class TestAlertServiceEvaluateThresholds:
    """Tests for AlertService.evaluate_thresholds — covers lines 73-95."""

    def _make_service(self):
        """Instantiate AlertService with mocked dependencies."""
        from app.modules.alerts.service import AlertService
        return AlertService(
            db=_make_db_mock(),
            audit_service=_make_audit_mock(),
            request_id="test-eval-thresholds",
            tenant_id=_make_uuid(),
            user_id=_make_uuid(),
        )

    @pytest.mark.asyncio
    async def test_evaluate_thresholds_measurement_saved_event(self):
        """evaluate_thresholds routes measurement_saved events to evaluate_measurement."""
        from app.modules.alerts.rules_engine import AlertRulesEngine
        svc = self._make_service()
        patient_id = _make_uuid()

        event = {
            "event_type": "measurement_saved",
            "measurement_type": "systolic_bp",
            "value": 145.0,
        }

        with patch.object(AlertRulesEngine, "evaluate_measurement", new=AsyncMock()) as mock_eval:
            result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        mock_eval.assert_awaited_once_with(
            patient_id=patient_id,
            measurement_type="systolic_bp",
            value=145.0,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_evaluate_thresholds_risk_score_computed_event(self):
        """evaluate_thresholds routes risk_score_computed events to evaluate_risk_score."""
        from app.modules.alerts.rules_engine import AlertRulesEngine
        svc = self._make_service()
        patient_id = _make_uuid()

        event = {
            "event_type": "risk_score_computed",
            "disease": "diabetes",
            "score": 0.88,
            "stratum": "critical",
        }

        with patch.object(AlertRulesEngine, "evaluate_risk_score", new=AsyncMock()) as mock_eval:
            result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        mock_eval.assert_awaited_once_with(
            patient_id=patient_id,
            disease="diabetes",
            score=0.88,
            stratum="critical",
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_evaluate_thresholds_unknown_event_type_returns_empty(self):
        """evaluate_thresholds returns empty list for unknown event types."""
        from app.modules.alerts.rules_engine import AlertRulesEngine
        svc = self._make_service()
        patient_id = _make_uuid()

        event = {"event_type": "unknown_event"}

        result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        assert result == []

    @pytest.mark.asyncio
    async def test_evaluate_thresholds_missing_event_type(self):
        """evaluate_thresholds handles events with no event_type key."""
        svc = self._make_service()
        patient_id = _make_uuid()

        result = await svc.evaluate_thresholds(patient_id=patient_id, event={})

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_evaluate_thresholds_measurement_event_missing_fields(self):
        """evaluate_thresholds handles measurement_saved events with missing value/type."""
        from app.modules.alerts.rules_engine import AlertRulesEngine
        svc = self._make_service()
        patient_id = _make_uuid()

        event = {"event_type": "measurement_saved"}  # missing measurement_type and value

        with patch.object(AlertRulesEngine, "evaluate_measurement", new=AsyncMock()):
            result = await svc.evaluate_thresholds(patient_id=patient_id, event=event)

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Alerts Tasks tests (simple tasks without Celery broker)
# ---------------------------------------------------------------------------

class TestAlertsTasks:
    """Tests for app.modules.alerts.tasks covering the simpler functions."""

    def test_check_missed_followups_task_callable(self):
        """check_missed_followups_task is importable and callable."""
        from app.modules.alerts.tasks import check_missed_followups_task
        assert callable(check_missed_followups_task)

    def test_check_escalations_task_callable(self):
        """check_escalations_task is importable and callable."""
        from app.modules.alerts.tasks import check_escalations_task
        assert callable(check_escalations_task)

    def test_dispatch_alert_task_callable(self):
        """dispatch_alert_task is importable and callable."""
        from app.modules.alerts.tasks import dispatch_alert_task
        assert callable(dispatch_alert_task)

    @pytest.mark.asyncio
    async def test_dispatch_alert_async_returns_skip_when_not_found(self):
        """_dispatch_alert_async returns skip dict when alert is not found in DB."""
        from app.modules.alerts.tasks import _dispatch_alert_async

        mock_task = MagicMock()
        mock_task.request.id = "test-task-id"
        mock_task.request.retries = 0
        alert_id = str(_make_uuid())

        # Context manager mock for db session
        mock_db = _make_db_mock()
        mock_db.scalars = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.get_async_session_context", return_value=mock_ctx):
            result = await _dispatch_alert_async(mock_task, alert_id, ["in_app"])

        assert result.get("skipped") is True
        assert result.get("reason") == "alert_not_found"

    @pytest.mark.asyncio
    async def test_dispatch_alert_async_dispatches_when_alert_found(self):
        """_dispatch_alert_async calls dispatcher.dispatch when alert is found."""
        from app.modules.alerts.tasks import _dispatch_alert_async
        from app.modules.alerts.dispatcher import AlertDispatcher

        mock_task = MagicMock()
        mock_task.request.id = "test-task-id"
        mock_task.request.retries = 0
        alert_id = str(_make_uuid())
        tenant_id = _make_uuid()

        # Mock alert
        mock_alert = MagicMock()
        mock_alert.tenant_id = tenant_id
        mock_alert.dispatch_status = {"in_app": "sent"}

        mock_db = _make_db_mock()
        mock_db.scalars = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=mock_alert)))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_updated_alert = MagicMock()
        mock_updated_alert.dispatch_status = {"in_app": "sent"}

        with patch("app.core.database.get_async_session_context", return_value=mock_ctx):
            with patch.object(AlertDispatcher, "dispatch", new=AsyncMock(return_value=mock_updated_alert)):
                result = await _dispatch_alert_async(mock_task, alert_id, ["in_app"])

        assert "in_app" in result

    @pytest.mark.asyncio
    async def test_check_escalations_async_runs_without_tenants(self):
        """_check_escalations_async completes without error when tenant list is empty."""
        from app.modules.alerts.tasks import _check_escalations_async
        # Empty tenant list is the current stub behavior — should just log and return
        await _check_escalations_async()


# ---------------------------------------------------------------------------
# Reports Tasks tests (async helper functions)
# ---------------------------------------------------------------------------

class TestReportsTasks:
    """Tests for app.modules.reports.tasks covering async PDF helper functions."""

    @pytest.mark.asyncio
    async def test_generate_clinical_pdf_async_success(self):
        """_generate_clinical_pdf_async returns a completed status dict on success."""
        from app.modules.reports.tasks import _generate_clinical_pdf_async

        mock_task = MagicMock()
        mock_task.request.id = "test-task-id"
        mock_task.request.retries = 0

        patient_id = str(_make_uuid())
        task_id = str(_make_uuid())
        tenant_id = str(_make_uuid())
        sections = ["demographics", "risk_scores"]

        with patch("app.modules.reports.tasks._update_task_status", new=AsyncMock()):
            result = await _generate_clinical_pdf_async(
                mock_task, patient_id, task_id, sections, tenant_id
            )

        assert result.get("status") == "completed"
        assert result.get("task_id") == task_id
        assert "bytes_size" in result

    @pytest.mark.asyncio
    async def test_generate_clinical_pdf_async_calls_update_on_success(self):
        """_generate_clinical_pdf_async updates task status to 'completed' on success."""
        from app.modules.reports.tasks import _generate_clinical_pdf_async

        mock_task = MagicMock()
        mock_task.request.id = "test-task-id"
        mock_task.request.retries = 0

        patient_id = str(_make_uuid())
        task_id = str(_make_uuid())
        tenant_id = str(_make_uuid())

        mock_update = AsyncMock()
        with patch("app.modules.reports.tasks._update_task_status", new=mock_update):
            await _generate_clinical_pdf_async(
                mock_task, patient_id, task_id, ["demographics"], tenant_id
            )

        mock_update.assert_awaited_once()
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_generate_referral_pdf_async_success(self):
        """_generate_referral_pdf_async returns a completed status dict on success."""
        from app.modules.reports.tasks import _generate_referral_pdf_async

        mock_task = MagicMock()
        mock_task.request.id = "test-referral-task"
        mock_task.request.retries = 0

        patient_id = str(_make_uuid())
        task_id = str(_make_uuid())
        tenant_id = str(_make_uuid())

        with patch("app.modules.reports.tasks._update_task_status", new=AsyncMock()):
            result = await _generate_referral_pdf_async(
                mock_task,
                patient_id,
                task_id,
                "Dr. Test Referrer",
                "Elevated cardiovascular risk",
                tenant_id,
            )

        assert result.get("status") == "completed"
        assert result.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_generate_referral_pdf_async_calls_update_on_success(self):
        """_generate_referral_pdf_async updates task status to 'completed' on success."""
        from app.modules.reports.tasks import _generate_referral_pdf_async

        mock_task = MagicMock()
        mock_task.request.id = "test-task"
        mock_task.request.retries = 0

        mock_update = AsyncMock()
        with patch("app.modules.reports.tasks._update_task_status", new=mock_update):
            await _generate_referral_pdf_async(
                mock_task,
                str(_make_uuid()),
                str(_make_uuid()),
                "Dr. Test",
                "Referral reason",
                str(_make_uuid()),
            )

        mock_update.assert_awaited_once()
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_update_task_status_logs_on_import_error(self):
        """_update_task_status gracefully handles ImportError (no raise)."""
        from app.modules.reports.tasks import _update_task_status

        # Force ImportError by patching the import
        with patch.dict("sys.modules", {"app.core.tasks_tracker": None}):
            # Should not raise — swallows the ImportError
            await _update_task_status(
                task_id=str(_make_uuid()),
                status="completed",
                result={"bytes_size": 1024},
            )

    @pytest.mark.asyncio
    async def test_update_task_status_with_error_string(self):
        """_update_task_status accepts an error string without raising."""
        from app.modules.reports.tasks import _update_task_status

        with patch.dict("sys.modules", {"app.core.tasks_tracker": None}):
            await _update_task_status(
                task_id=str(_make_uuid()),
                status="failed",
                error="PDF generation timed out",
            )

    @pytest.mark.asyncio
    async def test_generate_clinical_pdf_async_updates_failed_on_exception(self):
        """_generate_clinical_pdf_async calls _update_task_status('failed') when PDF build raises."""
        from app.modules.reports.tasks import _generate_clinical_pdf_async
        from app.modules.reports.pdf_builder import PDFBuilder

        mock_task = MagicMock()
        mock_task.request.id = "test-task"
        mock_task.request.retries = 0
        mock_task.retry = MagicMock(side_effect=Exception("Celery retry"))

        patient_id = str(_make_uuid())
        task_id = str(_make_uuid())
        tenant_id = str(_make_uuid())

        mock_update = AsyncMock()

        with patch("app.modules.reports.tasks._update_task_status", new=mock_update):
            with patch.object(PDFBuilder, "build_clinical_pdf", new=AsyncMock(side_effect=ValueError("build failed"))):
                with pytest.raises(Exception):
                    await _generate_clinical_pdf_async(
                        mock_task, patient_id, task_id, ["demographics"], tenant_id
                    )

        # Should have called update_task_status with 'failed'
        failed_calls = [
            c for c in mock_update.call_args_list
            if c.kwargs.get("status") == "failed"
        ]
        assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# Population Tasks tests (async refresh helper)
# ---------------------------------------------------------------------------

class TestPopulationTasks:
    """Tests for app.modules.population.tasks covering the refresh helper."""

    @pytest.mark.asyncio
    async def test_refresh_async_runs_for_each_metric_type(self):
        """_refresh_async iterates over _METRIC_TYPES without raising."""
        from app.modules.population.tasks import _refresh_async, _METRIC_TYPES

        tenant_id = str(_make_uuid())

        # Make session context fail — _refresh_async should swallow errors per metric
        error_ctx = MagicMock()
        error_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB unavailable"))
        error_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.get_async_session_context", return_value=error_ctx):
            # All metric types will fail, but _refresh_async swallows them
            await _refresh_async(tenant_id)

        # If we got here without raising, the task completed gracefully
        assert True

    @pytest.mark.asyncio
    async def test_refresh_async_handles_per_metric_exception(self):
        """_refresh_async does not raise when individual metrics fail."""
        from app.modules.population.tasks import _refresh_async

        tenant_id = str(_make_uuid())

        # Force all DB operations to fail
        error_ctx = MagicMock()
        error_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection refused"))
        error_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.get_async_session_context", return_value=error_ctx):
            # Should NOT raise — swallows all errors per metric type
            await _refresh_async(tenant_id)

        assert True  # reached here without exception

    def test_refresh_population_metrics_task_callable(self):
        """refresh_population_metrics_task is importable and callable."""
        from app.modules.population.tasks import refresh_population_metrics_task
        assert callable(refresh_population_metrics_task)

    def test_metric_types_list_contains_all_expected_types(self):
        """_METRIC_TYPES contains all expected metric type identifiers."""
        from app.modules.population.tasks import _METRIC_TYPES
        assert "risk_distribution" in _METRIC_TYPES
        assert any(t.startswith("trend_") for t in _METRIC_TYPES)

    @pytest.mark.asyncio
    async def test_refresh_async_with_invalid_tenant_uuid_raises(self):
        """_refresh_async raises ValueError for an invalid tenant UUID string."""
        from app.modules.population.tasks import _refresh_async

        with pytest.raises(ValueError):
            await _refresh_async("not-a-valid-uuid")


# ---------------------------------------------------------------------------
# AlertRulesEngine._load_thresholds tests (covers line 81)
# ---------------------------------------------------------------------------

class TestAlertRulesEngineLoadThresholds:
    """Tests for AlertRulesEngine._load_thresholds — covers the DB query path."""

    @pytest.mark.asyncio
    async def test_load_thresholds_calls_db_scalars(self):
        """_load_thresholds executes a DB query via db.scalars."""
        from app.modules.alerts.rules_engine import AlertRulesEngine

        db = _make_db_mock()
        db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        engine = AlertRulesEngine(db=db, tenant_id=_make_uuid(), alert_service=AsyncMock())

        result = await engine._load_thresholds(patient_id=_make_uuid())

        db.scalars.assert_awaited_once()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_load_thresholds_with_measurement_type_filter(self):
        """_load_thresholds accepts measurement_type filter without error."""
        from app.modules.alerts.rules_engine import AlertRulesEngine

        db = _make_db_mock()
        db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        engine = AlertRulesEngine(db=db, tenant_id=_make_uuid(), alert_service=AsyncMock())

        result = await engine._load_thresholds(
            patient_id=_make_uuid(),
            measurement_type="blood_glucose",
        )

        db.scalars.assert_awaited_once()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_load_thresholds_with_disease_filter(self):
        """_load_thresholds accepts disease filter without error."""
        from app.modules.alerts.rules_engine import AlertRulesEngine

        db = _make_db_mock()
        db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        engine = AlertRulesEngine(db=db, tenant_id=_make_uuid(), alert_service=AsyncMock())

        result = await engine._load_thresholds(
            patient_id=_make_uuid(),
            disease="diabetes",
        )

        db.scalars.assert_awaited_once()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# EscalationService.check_and_escalate tests
# ---------------------------------------------------------------------------

class TestEscalationCheckAndEscalate:
    """Tests for EscalationService.check_and_escalate — covers the bulk scan logic."""

    @pytest.mark.asyncio
    async def test_check_and_escalate_no_overdue_no_mutations(self):
        """check_and_escalate with no overdue alerts makes no DB mutations."""
        from app.modules.alerts.escalation import EscalationService

        db = _make_db_mock()
        db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        svc = EscalationService(
            db=db,
            audit_service=_make_audit_mock(),
            tenant_id=_make_uuid(),
        )
        # Should complete without any escalation calls
        await svc.check_and_escalate()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_and_escalate_calls_escalate_per_overdue_alert(self):
        """check_and_escalate calls escalate_alert for each overdue alert."""
        from app.modules.alerts.escalation import EscalationService
        from datetime import timedelta

        db = _make_db_mock()
        tenant_id = _make_uuid()

        # Make two overdue alerts at level 0
        alert1 = MagicMock()
        alert1.id = _make_uuid()
        alert1.tenant_id = tenant_id
        alert1.escalation_level = 0
        alert1.status = "active"
        alert1.severity = "critical"
        alert1.acknowledged_at = None
        alert1.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

        alert2 = MagicMock()
        alert2.id = _make_uuid()
        alert2.tenant_id = tenant_id
        alert2.escalation_level = 0
        alert2.status = "active"
        alert2.severity = "high"
        alert2.acknowledged_at = None
        alert2.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # First call returns level-0 overdue alerts, subsequent calls return empty
        call_count = {"n": 0}

        async def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(all=MagicMock(return_value=[alert1, alert2]))
            return MagicMock(all=MagicMock(return_value=[]))

        db.scalars = AsyncMock(side_effect=side_effect)

        svc = EscalationService(db=db, audit_service=_make_audit_mock(), tenant_id=tenant_id)

        # Patch escalate_alert to avoid DB complexity
        with patch.object(svc, "escalate_alert", new=AsyncMock()) as mock_escalate:
            await svc.check_and_escalate()

        # Should have been called for both overdue alerts
        assert mock_escalate.await_count >= 2

    @pytest.mark.asyncio
    async def test_check_and_escalate_resolves_max_level_alerts(self):
        """check_and_escalate resolves alerts at MAX_ESCALATION_LEVEL as unacknowledged."""
        from app.modules.alerts.escalation import EscalationService, MAX_ESCALATION_LEVEL
        from datetime import timedelta

        db = _make_db_mock()
        tenant_id = _make_uuid()

        # Max-level alert
        max_alert = MagicMock()
        max_alert.id = _make_uuid()
        max_alert.tenant_id = tenant_id
        max_alert.escalation_level = MAX_ESCALATION_LEVEL
        max_alert.status = "escalated"
        max_alert.severity = "critical"
        max_alert.acknowledged_at = None
        max_alert.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        max_alert.resolved_at = None

        # Levels 0 and 1 return empty; max-level returns our alert
        call_count = {"n": 0}

        async def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:  # levels 0 and 1
                return MagicMock(all=MagicMock(return_value=[]))
            # Level 2 (max) overdue
            return MagicMock(all=MagicMock(return_value=[max_alert]))

        db.scalars = AsyncMock(side_effect=side_effect)

        audit = _make_audit_mock()
        svc = EscalationService(db=db, audit_service=audit, tenant_id=tenant_id)

        await svc.check_and_escalate()

        # Max-level alert should be resolved
        assert max_alert.status == "resolved"
        assert max_alert.resolved_at is not None
        db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# Additional AlertDispatcher edge-case tests
# ---------------------------------------------------------------------------

class TestAlertDispatcherEdgeCases:
    """Additional edge-case tests for AlertDispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_whatsapp_channel_marks_sent(self):
        """dispatch marks whatsapp channel as 'sent' in dispatch_status."""
        from app.modules.alerts.dispatcher import AlertDispatcher

        db = _make_db_mock()
        alert = MagicMock()
        alert.id = _make_uuid()
        alert.patient_id = _make_uuid()
        alert.tenant_id = _make_uuid()
        alert.dispatch_status = {}
        alert.channels_dispatched = []
        db.scalars = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=alert)))
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        dispatcher = AlertDispatcher(db=db, tenant_id=alert.tenant_id)
        await dispatcher.dispatch(alert.id, ["whatsapp"])

        assert alert.dispatch_status.get("whatsapp") == "sent"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_channel_does_not_raise(self):
        """dispatch gracefully skips channels it does not recognise."""
        from app.modules.alerts.dispatcher import AlertDispatcher

        db = _make_db_mock()
        alert = MagicMock()
        alert.id = _make_uuid()
        alert.patient_id = _make_uuid()
        alert.tenant_id = _make_uuid()
        alert.dispatch_status = {}
        alert.channels_dispatched = []
        db.scalars = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=alert)))
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        dispatcher = AlertDispatcher(db=db, tenant_id=alert.tenant_id)
        # "fax" is not a real channel — should not raise
        await dispatcher.dispatch(alert.id, ["fax"])

    @pytest.mark.asyncio
    async def test_dispatch_handles_channel_exception_by_recording_failure(self):
        """dispatch records channel failure status when a channel raises an exception."""
        from app.modules.alerts.dispatcher import AlertDispatcher

        db = _make_db_mock()
        alert = MagicMock()
        alert.id = _make_uuid()
        alert.patient_id = _make_uuid()
        alert.tenant_id = _make_uuid()
        alert.dispatch_status = {}
        alert.channels_dispatched = []
        db.scalars = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=alert)))
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        dispatcher = AlertDispatcher(db=db, tenant_id=alert.tenant_id)

        # Make send_email raise an exception
        with patch.object(dispatcher, "send_email", new=AsyncMock(side_effect=RuntimeError("SMTP error"))):
            await dispatcher.dispatch(alert.id, ["email"])

        # Should record failure status
        email_status = alert.dispatch_status.get("email", "")
        assert "failed" in email_status


# ---------------------------------------------------------------------------
# Tasks backoff constant tests
# ---------------------------------------------------------------------------

class TestTasksBackoffConstants:
    """Tests for task backoff constants in alerts and reports tasks."""

    def test_alerts_tasks_backoff_constants(self):
        """alerts/tasks.py has correct backoff base and factor values."""
        from app.modules.alerts.tasks import _BACKOFF_BASE, _BACKOFF_FACTOR
        assert _BACKOFF_BASE == 30
        assert _BACKOFF_FACTOR == 4

    def test_reports_tasks_backoff_constants(self):
        """reports/tasks.py has correct backoff base and factor values."""
        from app.modules.reports.tasks import _BACKOFF_BASE, _BACKOFF_FACTOR
        assert _BACKOFF_BASE == 30
        assert _BACKOFF_FACTOR == 4

    def test_population_metric_types_constant(self):
        """population/tasks.py _METRIC_TYPES has at least 5 entries."""
        from app.modules.population.tasks import _METRIC_TYPES
        assert len(_METRIC_TYPES) >= 5
