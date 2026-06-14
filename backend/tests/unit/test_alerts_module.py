"""
Tests for app.modules.alerts — enums, exceptions, models, schemas,
rules engine, escalation service, dispatcher, and alert service.

All tests use synthetic data only. No real PHI.
DB is mocked via AsyncMock — no network calls.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

from app.modules.alerts.enums import (
    AlertType,
    AlertSeverity,
    AlertStatus,
    ThresholdCondition,
    DispatchChannel,
)


def test_alert_type_threshold_breach():
    """AlertType.THRESHOLD_BREACH has correct string value."""
    assert AlertType.THRESHOLD_BREACH.value == "threshold_breach"


def test_alert_type_risk_critical():
    """AlertType.RISK_CRITICAL has correct string value."""
    assert AlertType.RISK_CRITICAL.value == "risk_critical"


def test_alert_type_forecast_warning():
    """AlertType.FORECAST_WARNING has correct string value."""
    assert AlertType.FORECAST_WARNING.value == "forecast_warning"


def test_alert_type_missed_followup():
    """AlertType.MISSED_FOLLOWUP has correct string value."""
    assert AlertType.MISSED_FOLLOWUP.value == "missed_followup"


def test_alert_type_drug_interaction():
    """AlertType.DRUG_INTERACTION has correct string value."""
    assert AlertType.DRUG_INTERACTION.value == "drug_interaction"


def test_alert_type_count():
    """AlertType has exactly 5 members."""
    assert len(AlertType) == 5


def test_alert_severity_all_values():
    """AlertSeverity has all 5 expected severity levels."""
    values = {s.value for s in AlertSeverity}
    assert values == {"critical", "high", "moderate", "low", "info"}


def test_alert_status_all_values():
    """AlertStatus has all 5 lifecycle states."""
    values = {s.value for s in AlertStatus}
    assert values == {"active", "acknowledged", "escalated", "resolved", "expired"}


def test_threshold_condition_above():
    """ThresholdCondition.ABOVE has correct string value."""
    assert ThresholdCondition.ABOVE.value == "above"


def test_threshold_condition_below():
    """ThresholdCondition.BELOW has correct string value."""
    assert ThresholdCondition.BELOW.value == "below"


def test_threshold_condition_enters_stratum():
    """ThresholdCondition.ENTERS_STRATUM has correct string value."""
    assert ThresholdCondition.ENTERS_STRATUM.value == "enters_stratum"


def test_dispatch_channel_all_values():
    """DispatchChannel has all 4 expected channels."""
    values = {c.value for c in DispatchChannel}
    assert values == {"in_app", "email", "sms", "whatsapp"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

from app.modules.alerts.exceptions import (
    AlertError,
    AlertNotFoundError,
    ThresholdConfigurationError,
    DispatchFailedError,
    EscalationError,
)


def test_alert_error_default_message():
    """AlertError uses default message when none provided."""
    err = AlertError()
    assert "alert" in str(err).lower()


def test_alert_error_custom_message():
    """AlertError stores and returns custom message."""
    err = AlertError("custom alert error")
    assert err.message == "custom alert error"
    assert isinstance(err, Exception)


def test_alert_not_found_error():
    """AlertNotFoundError includes the alert id in its message."""
    err = AlertNotFoundError("00000000-0000-0000-0000-000000000001")
    assert "00000000-0000-0000-0000-000000000001" in str(err)
    assert isinstance(err, AlertError)


def test_threshold_configuration_error():
    """ThresholdConfigurationError includes the reason string."""
    err = ThresholdConfigurationError("missing measurement_type")
    assert "missing measurement_type" in str(err)
    assert isinstance(err, AlertError)


def test_dispatch_failed_error():
    """DispatchFailedError includes alert_id and channel."""
    err = DispatchFailedError("abc-123", "email")
    assert "abc-123" in str(err)
    assert "email" in str(err)
    assert isinstance(err, AlertError)


def test_escalation_error():
    """EscalationError includes alert_id and reason."""
    err = EscalationError("xyz-999", "already at max level")
    assert "xyz-999" in str(err)
    assert "already at max level" in str(err)
    assert isinstance(err, AlertError)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

from app.modules.alerts.schemas import (
    AlertResponse,
    AlertListResponse,
    AcknowledgeAlertRequest,
    ConfigureThresholdRequest,
    ThresholdResponse,
    SingleAlertResponse,
)


def test_configure_threshold_request_valid_measurement():
    """ConfigureThresholdRequest accepts a valid measurement-type threshold."""
    req = ConfigureThresholdRequest(
        measurement_type="systolic_bp",
        condition=ThresholdCondition.ABOVE,
        threshold_value=180.0,
        severity=AlertSeverity.CRITICAL,
    )
    assert req.threshold_value == 180.0
    assert req.condition == ThresholdCondition.ABOVE
    assert req.severity == AlertSeverity.CRITICAL
    assert req.patient_id is None


def test_configure_threshold_request_valid_disease():
    """ConfigureThresholdRequest accepts a valid disease/stratum threshold."""
    req = ConfigureThresholdRequest(
        disease="diabetes",
        condition=ThresholdCondition.ENTERS_STRATUM,
        target_stratum="critical",
        severity=AlertSeverity.HIGH,
    )
    assert req.disease == "diabetes"
    assert req.target_stratum == "critical"


def test_configure_threshold_request_with_patient_id():
    """ConfigureThresholdRequest accepts optional patient_id for patient-specific thresholds."""
    patient_id = uuid.uuid4()
    req = ConfigureThresholdRequest(
        patient_id=patient_id,
        measurement_type="blood_glucose",
        condition=ThresholdCondition.BELOW,
        threshold_value=70.0,
        severity=AlertSeverity.MODERATE,
    )
    assert req.patient_id == patient_id


def test_configure_threshold_request_missing_required_fields():
    """ConfigureThresholdRequest rejects request missing condition and severity."""
    with pytest.raises(ValidationError):
        ConfigureThresholdRequest(measurement_type="bp")


def test_acknowledge_alert_request_no_notes():
    """AcknowledgeAlertRequest accepts request without notes."""
    req = AcknowledgeAlertRequest()
    assert req.notes is None


def test_acknowledge_alert_request_with_notes():
    """AcknowledgeAlertRequest stores optional clinical notes."""
    req = AcknowledgeAlertRequest(notes="Reviewed with attending physician.")
    assert req.notes == "Reviewed with attending physician."


def test_acknowledge_alert_request_notes_max_length():
    """AcknowledgeAlertRequest rejects notes exceeding 1000 characters."""
    with pytest.raises(ValidationError):
        AcknowledgeAlertRequest(notes="x" * 1001)


def test_alert_response_serialization():
    """AlertResponse serializes from a dict of alert fields."""
    now = datetime.now(timezone.utc)
    alert_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    data = {
        "id": alert_id,
        "tenant_id": tenant_id,
        "patient_id": patient_id,
        "alert_type": "threshold_breach",
        "severity": "critical",
        "title": "BP threshold breach",
        "message": "Systolic BP exceeded threshold",
        "payload": {"measurement_type": "systolic_bp"},
        "status": "active",
        "created_at": now,
        "escalation_level": 0,
        "channels_dispatched": [],
        "dispatch_status": {},
    }
    resp = AlertResponse(**data)
    assert resp.id == alert_id
    assert resp.alert_type == "threshold_breach"
    assert resp.acknowledged_at is None


def test_alert_list_response_envelope():
    """AlertListResponse wraps data list in success envelope."""
    resp = AlertListResponse(data=[], meta={"total": 0})
    assert resp.success is True
    assert resp.data == []


def test_threshold_response_serialization():
    """ThresholdResponse serializes with required fields."""
    now = datetime.now(timezone.utc)
    resp = ThresholdResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        patient_id=None,
        measurement_type="systolic_bp",
        disease=None,
        condition="above",
        threshold_value=180.0,
        target_stratum=None,
        severity="critical",
        is_active=True,
        created_by=uuid.uuid4(),
        created_at=now,
    )
    assert resp.is_active is True
    assert resp.condition == "above"


def test_single_alert_response_envelope():
    """SingleAlertResponse wraps a single alert in the standard envelope."""
    now = datetime.now(timezone.utc)
    alert_data = AlertResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        alert_type="risk_critical",
        severity="high",
        title="Risk alert",
        message="Patient risk elevated",
        payload={},
        status="active",
        created_at=now,
        escalation_level=0,
        channels_dispatched=[],
        dispatch_status={},
    )
    env = SingleAlertResponse(data=alert_data, meta={"request_id": "test"})
    assert env.success is True
    assert env.data.alert_type == "risk_critical"


# ---------------------------------------------------------------------------
# Models — basic instantiation (covers model field definitions)
# ---------------------------------------------------------------------------

from app.modules.alerts.models import Alert, AlertThreshold, EscalationRecord


def test_alert_model_instantiation():
    """Alert model can be instantiated with all required fields."""
    alert = Alert(
        tenant_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        alert_type=AlertType.THRESHOLD_BREACH.value,
        severity=AlertSeverity.CRITICAL.value,
        title="Test Alert",
        message="Synthetic test alert message",
        payload={"measurement_type": "systolic_bp"},
        status=AlertStatus.ACTIVE.value,
        escalation_level=0,
        channels_dispatched=[],
        dispatch_status={},
    )
    assert alert.status == "active"
    assert alert.escalation_level == 0


def test_alert_threshold_model_instantiation():
    """AlertThreshold model can be instantiated with measurement_type config."""
    threshold = AlertThreshold(
        tenant_id=uuid.uuid4(),
        patient_id=None,
        measurement_type="blood_glucose",
        condition=ThresholdCondition.ABOVE.value,
        threshold_value=200.0,
        severity=AlertSeverity.HIGH.value,
        is_active=True,
        created_by=uuid.uuid4(),
    )
    assert threshold.is_active is True
    assert threshold.condition == "above"


def test_escalation_record_model_instantiation():
    """EscalationRecord model can be instantiated with transition fields."""
    record = EscalationRecord(
        tenant_id=uuid.uuid4(),
        alert_id=uuid.uuid4(),
        from_level=0,
        to_level=1,
        escalated_at=datetime.now(timezone.utc),
        target_user_id=uuid.uuid4(),
        reason="unacknowledged_timeout",
    )
    assert record.from_level == 0
    assert record.to_level == 1
    assert record.reason == "unacknowledged_timeout"


# ---------------------------------------------------------------------------
# Rules Engine
# ---------------------------------------------------------------------------

from app.modules.alerts.rules_engine import AlertRulesEngine


def _make_threshold(
    condition: str,
    threshold_value: float | None = None,
    target_stratum: str | None = None,
    severity: str = "high",
    is_active: bool = True,
) -> MagicMock:
    """Helper: build a mock AlertThreshold with specified attributes."""
    t = MagicMock()
    t.id = uuid.uuid4()
    t.condition = condition
    t.threshold_value = threshold_value
    t.target_stratum = target_stratum
    t.severity = severity
    t.is_active = is_active
    return t


@pytest.mark.asyncio
async def test_evaluate_measurement_above_breach():
    """evaluate_measurement triggers alert when value exceeds ABOVE threshold."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="above", threshold_value=180.0)

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    # Patch _load_thresholds to return our mock threshold
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_measurement(patient_id=patient_id, measurement_type="systolic_bp", value=190.0)

    mock_alert_service.create_alert.assert_called_once()
    call_kwargs = mock_alert_service.create_alert.call_args.kwargs
    assert call_kwargs["alert_type"] == AlertType.THRESHOLD_BREACH


@pytest.mark.asyncio
async def test_evaluate_measurement_above_no_breach():
    """evaluate_measurement does NOT fire alert when value is below ABOVE threshold."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="above", threshold_value=180.0)

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_measurement(patient_id=patient_id, measurement_type="systolic_bp", value=120.0)

    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_measurement_below_breach():
    """evaluate_measurement triggers alert when value drops below BELOW threshold."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="below", threshold_value=70.0)

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_measurement(patient_id=patient_id, measurement_type="blood_glucose", value=60.0)

    mock_alert_service.create_alert.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_measurement_below_no_breach():
    """evaluate_measurement does NOT fire when value is above BELOW threshold."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="below", threshold_value=70.0)

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_measurement(patient_id=patient_id, measurement_type="blood_glucose", value=95.0)

    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_measurement_no_thresholds():
    """evaluate_measurement does nothing when no thresholds configured."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    engine = AlertRulesEngine(db=mock_db, tenant_id=uuid.uuid4(), alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[])

    await engine.evaluate_measurement(patient_id=uuid.uuid4(), measurement_type="weight", value=100.0)

    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_measurement_threshold_value_none():
    """evaluate_measurement skips threshold when threshold_value is None."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="above", threshold_value=None)

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_measurement(patient_id=patient_id, measurement_type="systolic_bp", value=999.0)

    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_risk_score_stratum_match():
    """evaluate_risk_score fires RISK_CRITICAL alert when patient enters monitored stratum."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="enters_stratum", target_stratum="critical")

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_risk_score(
        patient_id=patient_id,
        disease="diabetes",
        score=0.91,
        stratum="critical",
    )

    mock_alert_service.create_alert.assert_called_once()
    call_kwargs = mock_alert_service.create_alert.call_args.kwargs
    assert call_kwargs["alert_type"] == AlertType.RISK_CRITICAL


@pytest.mark.asyncio
async def test_evaluate_risk_score_stratum_no_match():
    """evaluate_risk_score does NOT fire when stratum does not match target_stratum."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    threshold = _make_threshold(condition="enters_stratum", target_stratum="critical")

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[threshold])

    await engine.evaluate_risk_score(
        patient_id=patient_id,
        disease="diabetes",
        score=0.45,
        stratum="moderate",
    )

    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_risk_score_no_thresholds():
    """evaluate_risk_score does nothing when no thresholds configured."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    engine = AlertRulesEngine(db=mock_db, tenant_id=uuid.uuid4(), alert_service=mock_alert_service)
    engine._load_thresholds = AsyncMock(return_value=[])

    await engine.evaluate_risk_score(
        patient_id=uuid.uuid4(),
        disease="hypertension",
        score=0.8,
        stratum="high",
    )
    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_forecast_with_crossing():
    """evaluate_forecast fires FORECAST_WARNING for each projected crossing."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=mock_alert_service)

    forecast_data = {
        "forecast_id": str(uuid.uuid4()),
        "projected_crossings": [
            {"measurement_type": "systolic_bp", "days_until": 14, "projected_value": 195.0},
            {"measurement_type": "blood_glucose", "days_until": 7, "projected_value": 250.0},
        ],
    }

    await engine.evaluate_forecast(patient_id=patient_id, forecast_data=forecast_data)

    assert mock_alert_service.create_alert.call_count == 2
    call_kwargs = mock_alert_service.create_alert.call_args.kwargs
    assert call_kwargs["alert_type"] == AlertType.FORECAST_WARNING


@pytest.mark.asyncio
async def test_evaluate_forecast_empty_crossings():
    """evaluate_forecast fires no alerts when projected_crossings is empty."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    engine = AlertRulesEngine(db=mock_db, tenant_id=uuid.uuid4(), alert_service=mock_alert_service)

    await engine.evaluate_forecast(
        patient_id=uuid.uuid4(),
        forecast_data={"forecast_id": str(uuid.uuid4()), "projected_crossings": []},
    )

    mock_alert_service.create_alert.assert_not_called()


@pytest.mark.asyncio
async def test_check_missed_followup_returns_false():
    """check_missed_followup placeholder always returns False."""
    mock_db = AsyncMock()
    mock_alert_service = AsyncMock()
    engine = AlertRulesEngine(db=mock_db, tenant_id=uuid.uuid4(), alert_service=mock_alert_service)

    result = await engine.check_missed_followup(patient_id=uuid.uuid4())

    assert result is False


@pytest.mark.asyncio
async def test_load_thresholds_queries_db():
    """_load_thresholds executes a DB query and returns matching thresholds."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_threshold = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_threshold]
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    engine = AlertRulesEngine(db=mock_db, tenant_id=tenant_id, alert_service=AsyncMock())
    result = await engine._load_thresholds(patient_id=patient_id, measurement_type="systolic_bp")

    assert result == [mock_threshold]
    mock_db.scalars.assert_called_once()


# ---------------------------------------------------------------------------
# Escalation Service
# ---------------------------------------------------------------------------

from app.modules.alerts.escalation import EscalationService


def test_get_escalation_timeout_level_0():
    """Level 0 escalation timeout is 15 minutes."""
    svc = EscalationService(db=AsyncMock(), audit_service=AsyncMock(), tenant_id=uuid.uuid4())
    timeout = svc._get_escalation_timeout(0)
    assert timeout == timedelta(minutes=15)


def test_get_escalation_timeout_level_1():
    """Level 1 escalation timeout is 30 minutes."""
    svc = EscalationService(db=AsyncMock(), audit_service=AsyncMock(), tenant_id=uuid.uuid4())
    timeout = svc._get_escalation_timeout(1)
    assert timeout == timedelta(minutes=30)


def test_get_escalation_timeout_level_2_plus():
    """Level 2+ escalation timeout defaults to 30 minutes."""
    svc = EscalationService(db=AsyncMock(), audit_service=AsyncMock(), tenant_id=uuid.uuid4())
    assert svc._get_escalation_timeout(2) == timedelta(minutes=30)
    assert svc._get_escalation_timeout(5) == timedelta(minutes=30)


@pytest.mark.asyncio
async def test_escalate_alert_success():
    """escalate_alert increments escalation level and creates EscalationRecord."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    mock_alert = MagicMock()
    mock_alert.id = alert_id
    mock_alert.escalation_level = 0

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_alert
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_alert)

    svc = EscalationService(db=mock_db, audit_service=mock_audit, tenant_id=tenant_id)
    result = await svc.escalate_alert(alert_id=alert_id, target_user_id=target_user_id)

    assert mock_alert.escalation_level == 1
    assert mock_alert.status == AlertStatus.ESCALATED.value
    mock_db.add.assert_called_once()
    mock_audit.log_audit.assert_called_once()


@pytest.mark.asyncio
async def test_escalate_alert_not_found():
    """escalate_alert raises EscalationError when alert not found."""
    from app.modules.alerts.exceptions import EscalationError

    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = EscalationService(db=mock_db, audit_service=AsyncMock(), tenant_id=uuid.uuid4())

    with pytest.raises(EscalationError, match="alert not found"):
        await svc.escalate_alert(alert_id=uuid.uuid4(), target_user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_escalate_alert_at_max_level():
    """escalate_alert raises EscalationError when alert is already at max escalation."""
    from app.modules.alerts.exceptions import EscalationError

    mock_db = AsyncMock()
    mock_alert = MagicMock()
    mock_alert.escalation_level = 2  # MAX_ESCALATION_LEVEL

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_alert
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = EscalationService(db=mock_db, audit_service=AsyncMock(), tenant_id=uuid.uuid4())

    with pytest.raises(EscalationError, match="maximum escalation"):
        await svc.escalate_alert(alert_id=uuid.uuid4(), target_user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_check_and_escalate_no_overdue_alerts():
    """check_and_escalate completes without error when no overdue alerts exist."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()

    # Both queries return empty results
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = EscalationService(db=mock_db, audit_service=mock_audit, tenant_id=tenant_id)
    await svc.check_and_escalate()

    # No commits needed when no overdue alerts
    mock_db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

from app.modules.alerts.dispatcher import AlertDispatcher


@pytest.mark.asyncio
async def test_send_in_app_succeeds():
    """send_in_app always completes without error."""
    mock_db = AsyncMock()
    dispatcher = AlertDispatcher(db=mock_db, tenant_id=uuid.uuid4())

    mock_alert = MagicMock()
    mock_alert.id = uuid.uuid4()

    await dispatcher.send_in_app(alert=mock_alert)
    # No exception raised — in-app delivery always succeeds


@pytest.mark.asyncio
async def test_send_email_stub():
    """send_email stub completes without error (real SendGrid not integrated)."""
    mock_db = AsyncMock()
    dispatcher = AlertDispatcher(db=mock_db, tenant_id=uuid.uuid4())

    mock_alert = MagicMock()
    mock_alert.id = uuid.uuid4()

    await dispatcher.send_email(alert=mock_alert, recipient_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_send_sms_stub():
    """send_sms stub completes without error (real Twilio not integrated)."""
    mock_db = AsyncMock()
    dispatcher = AlertDispatcher(db=mock_db, tenant_id=uuid.uuid4())

    mock_alert = MagicMock()
    mock_alert.id = uuid.uuid4()

    await dispatcher.send_sms(alert=mock_alert, recipient_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_send_whatsapp_stub():
    """send_whatsapp stub completes without error (future integration)."""
    mock_db = AsyncMock()
    dispatcher = AlertDispatcher(db=mock_db, tenant_id=uuid.uuid4())

    mock_alert = MagicMock()
    mock_alert.id = uuid.uuid4()

    await dispatcher.send_whatsapp(alert=mock_alert, recipient_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_dispatch_alert_not_found():
    """dispatch raises DispatchFailedError when alert not found in tenant."""
    from app.modules.alerts.exceptions import DispatchFailedError

    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    dispatcher = AlertDispatcher(db=mock_db, tenant_id=uuid.uuid4())

    with pytest.raises(DispatchFailedError):
        await dispatcher.dispatch(alert_id=uuid.uuid4(), channels=["in_app"])


@pytest.mark.asyncio
async def test_dispatch_in_app_channel():
    """dispatch processes in_app channel and marks it sent."""
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
    result = await dispatcher.dispatch(alert_id=alert_id, channels=["in_app"])

    assert mock_alert.dispatch_status.get("in_app") == "sent"
    assert "in_app" in mock_alert.channels_dispatched


@pytest.mark.asyncio
async def test_dispatch_skips_already_sent_channel():
    """dispatch skips channels already marked sent (idempotency)."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()

    mock_alert = MagicMock()
    mock_alert.id = alert_id
    mock_alert.patient_id = uuid.uuid4()
    mock_alert.dispatch_status = {"in_app": "sent"}
    mock_alert.channels_dispatched = ["in_app"]

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_alert
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_alert)

    dispatcher = AlertDispatcher(db=mock_db, tenant_id=tenant_id)

    with patch.object(dispatcher, "send_in_app", new_callable=AsyncMock) as mock_send:
        await dispatcher.dispatch(alert_id=alert_id, channels=["in_app"])
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_email_and_sms():
    """dispatch processes email and sms channels and marks both sent."""
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
    await dispatcher.dispatch(alert_id=alert_id, channels=["email", "sms"])

    assert mock_alert.dispatch_status.get("email") == "sent"
    assert mock_alert.dispatch_status.get("sms") == "sent"


# ---------------------------------------------------------------------------
# Alert Service
# ---------------------------------------------------------------------------

from app.modules.alerts.service import AlertService


def _make_alert_service(mock_db=None, tenant_id=None, user_id=None):
    """Helper: build an AlertService with mock dependencies."""
    return AlertService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-request-id",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_create_alert_persists_and_dispatches():
    """create_alert persists alert record and enqueues dispatch task."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_alert = MagicMock()
    mock_alert.id = uuid.uuid4()
    mock_alert.severity = "critical"
    mock_alert.alert_type = "threshold_breach"

    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_alert)

    svc = _make_alert_service(mock_db=mock_db, tenant_id=tenant_id)
    svc.db.add = mock_db.add

    with patch("app.modules.alerts.tasks.dispatch_alert_task") as mock_task:
        mock_task.delay = MagicMock()

        # patch flush to set mock_alert on add
        added_alerts = []
        original_add = mock_db.add

        def capture_add(obj):
            added_alerts.append(obj)

        mock_db.add.side_effect = capture_add

        result = await svc.create_alert(
            alert_type=AlertType.THRESHOLD_BREACH,
            severity=AlertSeverity.CRITICAL,
            patient_id=patient_id,
            title="Systolic BP breach",
            message="Synthetic test alert",
            payload={"measurement_type": "systolic_bp"},
        )

        mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_acknowledge_alert_success():
    """acknowledge sets acknowledged_at, acknowledged_by, and status."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_alert = MagicMock()
    mock_alert.id = alert_id
    mock_alert.status = "active"

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_alert
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_alert)

    svc = _make_alert_service(mock_db=mock_db, tenant_id=tenant_id, user_id=user_id)

    result = await svc.acknowledge(
        alert_id=alert_id,
        user_id=user_id,
        notes="Reviewed with patient",
    )

    assert mock_alert.status == AlertStatus.ACKNOWLEDGED.value
    assert mock_alert.acknowledged_by == user_id
    assert mock_alert.acknowledgment_notes == "Reviewed with patient"


@pytest.mark.asyncio
async def test_acknowledge_alert_not_found():
    """acknowledge raises AlertNotFoundError when alert not found."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_alert_service(mock_db=mock_db)

    with pytest.raises(AlertNotFoundError):
        await svc.acknowledge(alert_id=uuid.uuid4(), user_id=uuid.uuid4(), notes=None)


@pytest.mark.asyncio
async def test_configure_threshold_success():
    """configure_threshold persists AlertThreshold with correct fields."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    created_by = uuid.uuid4()

    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_threshold = MagicMock()
    mock_threshold.id = uuid.uuid4()
    mock_threshold.severity = "critical"
    mock_threshold.condition = "above"
    mock_db.refresh = AsyncMock(return_value=mock_threshold)

    data = ConfigureThresholdRequest(
        measurement_type="systolic_bp",
        condition=ThresholdCondition.ABOVE,
        threshold_value=180.0,
        severity=AlertSeverity.CRITICAL,
    )

    svc = _make_alert_service(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.configure_threshold(data=data, created_by=created_by)

    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_configure_threshold_missing_type_and_disease():
    """configure_threshold raises ThresholdConfigurationError when neither measurement_type nor disease is set."""
    from app.modules.alerts.exceptions import ThresholdConfigurationError

    # Build a ConfigureThresholdRequest without measurement_type or disease
    # We do this by post-hoc clearing the field since schema normally allows either
    data = ConfigureThresholdRequest(
        measurement_type=None,
        disease=None,
        condition=ThresholdCondition.ABOVE,
        threshold_value=100.0,
        severity=AlertSeverity.HIGH,
    )

    svc = _make_alert_service()

    with pytest.raises(ThresholdConfigurationError, match="measurement_type or disease"):
        await svc.configure_threshold(data=data, created_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_patient_alerts_returns_list():
    """get_patient_alerts returns paginated alert list for a patient."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_alert = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_alert]
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_alert_service(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.get_patient_alerts(
        patient_id=patient_id,
        status_filter=None,
        limit=20,
        offset=0,
    )

    assert result == [mock_alert]


@pytest.mark.asyncio
async def test_get_patient_alerts_with_status_filter():
    """get_patient_alerts applies status filter when provided."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_alert_service(mock_db=mock_db)
    result = await svc.get_patient_alerts(
        patient_id=uuid.uuid4(),
        status_filter="active",
        limit=10,
        offset=0,
    )
    assert result == []


@pytest.mark.asyncio
async def test_get_unacknowledged_returns_list():
    """get_unacknowledged returns unacknowledged active/escalated alerts."""
    mock_db = AsyncMock()

    mock_alert = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_alert]
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_alert_service(mock_db=mock_db)
    result = await svc.get_unacknowledged()

    assert result == [mock_alert]
