"""
PrescpHealth Backend — Unit Tests: Alert and Notification System.

Tests cover enums, exception hierarchy, schema validation, and escalation logic.
No real DB connections are made — all tests are pure unit tests.

Run with:
    pytest backend/tests/unit/test_alerts_staging.py -v
"""
import uuid
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


def test_enums_valid() -> None:
    """All expected enum values are present and have correct string values."""
    from app.modules.alerts_staging.enums import (
        AlertType,
        AlertSeverity,
        AlertStatus,
        ThresholdCondition,
        DispatchChannel,
    )

    # AlertType — all five trigger classifications
    assert AlertType.THRESHOLD_BREACH == "threshold_breach"
    assert AlertType.RISK_CRITICAL == "risk_critical"
    assert AlertType.FORECAST_WARNING == "forecast_warning"
    assert AlertType.MISSED_FOLLOWUP == "missed_followup"
    assert AlertType.DRUG_INTERACTION == "drug_interaction"

    # AlertSeverity — five urgency levels
    assert AlertSeverity.CRITICAL == "critical"
    assert AlertSeverity.HIGH == "high"
    assert AlertSeverity.MODERATE == "moderate"
    assert AlertSeverity.LOW == "low"
    assert AlertSeverity.INFO == "info"

    # AlertStatus — lifecycle states
    assert AlertStatus.ACTIVE == "active"
    assert AlertStatus.ACKNOWLEDGED == "acknowledged"
    assert AlertStatus.ESCALATED == "escalated"
    assert AlertStatus.RESOLVED == "resolved"
    assert AlertStatus.EXPIRED == "expired"

    # ThresholdCondition — three evaluation directions
    assert ThresholdCondition.ABOVE == "above"
    assert ThresholdCondition.BELOW == "below"
    assert ThresholdCondition.ENTERS_STRATUM == "enters_stratum"

    # DispatchChannel — four delivery channels
    assert DispatchChannel.IN_APP == "in_app"
    assert DispatchChannel.EMAIL == "email"
    assert DispatchChannel.SMS == "sms"
    assert DispatchChannel.WHATSAPP == "whatsapp"


def test_alert_type_values() -> None:
    """All AlertType enum values are strings (required for JSON serialization)."""
    from app.modules.alerts_staging.enums import AlertType

    for member in AlertType:
        assert isinstance(member.value, str), (
            f"AlertType.{member.name}.value should be str, got {type(member.value)}"
        )


# ---------------------------------------------------------------------------
# Exception hierarchy tests
# ---------------------------------------------------------------------------


def test_exceptions_hierarchy() -> None:
    """All alert exceptions inherit from AlertError base."""
    from app.modules.alerts_staging.exceptions import (
        AlertError,
        AlertNotFoundError,
        ThresholdConfigurationError,
        DispatchFailedError,
        EscalationError,
    )

    # All subclasses should be catchable as AlertError
    assert issubclass(AlertNotFoundError, AlertError)
    assert issubclass(ThresholdConfigurationError, AlertError)
    assert issubclass(DispatchFailedError, AlertError)
    assert issubclass(EscalationError, AlertError)

    # AlertError itself inherits from base Exception
    assert issubclass(AlertError, Exception)

    # Verify message formatting is correct in each exception
    not_found = AlertNotFoundError("abc-123")
    assert "abc-123" in not_found.message

    config_err = ThresholdConfigurationError("missing measurement_type")
    assert "missing measurement_type" in config_err.message

    dispatch_err = DispatchFailedError("alert-uuid", "email")
    assert "email" in dispatch_err.message

    esc_err = EscalationError("alert-uuid", "max level")
    assert "max level" in esc_err.message


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_schema_acknowledge_request_valid() -> None:
    """AcknowledgeAlertRequest accepts valid notes string."""
    from app.modules.alerts_staging.schemas import AcknowledgeAlertRequest

    # With notes
    req = AcknowledgeAlertRequest(notes="Patient called back, situation resolved.")
    assert req.notes == "Patient called back, situation resolved."

    # Without notes (optional)
    req_no_notes = AcknowledgeAlertRequest()
    assert req_no_notes.notes is None


def test_schema_configure_threshold_valid() -> None:
    """ConfigureThresholdRequest validates a well-formed threshold configuration."""
    from app.modules.alerts_staging.schemas import ConfigureThresholdRequest
    from app.modules.alerts_staging.enums import ThresholdCondition, AlertSeverity

    req = ConfigureThresholdRequest(
        patient_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        measurement_type="blood_glucose",
        condition=ThresholdCondition.ABOVE,
        threshold_value=250.0,
        severity=AlertSeverity.CRITICAL,
    )

    assert req.measurement_type == "blood_glucose"
    assert req.condition == ThresholdCondition.ABOVE
    assert req.threshold_value == 250.0
    assert req.severity == AlertSeverity.CRITICAL
    assert req.disease is None       # Optional; not provided
    assert req.target_stratum is None


def test_schema_threshold_condition_invalid() -> None:
    """ConfigureThresholdRequest rejects an invalid condition value."""
    from app.modules.alerts_staging.schemas import ConfigureThresholdRequest
    from app.modules.alerts_staging.enums import AlertSeverity

    with pytest.raises(ValidationError) as exc_info:
        ConfigureThresholdRequest(
            measurement_type="blood_pressure",
            condition="between",           # Not a valid ThresholdCondition value
            threshold_value=120.0,
            severity=AlertSeverity.HIGH,
        )

    # Pydantic should report an enum validation failure
    errors = exc_info.value.errors()
    assert len(errors) >= 1
    assert any("condition" in str(e.get("loc", "")) for e in errors)


def test_schema_alert_response_from_dict() -> None:
    """AlertResponse can be constructed from a plain dictionary."""
    from app.modules.alerts_staging.schemas import AlertResponse
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "patient_id": uuid.uuid4(),
        "alert_type": "threshold_breach",
        "severity": "critical",
        "title": "High glucose alert",
        "message": "Blood glucose above threshold",
        "payload": {"threshold_id": str(uuid.uuid4())},
        "status": "active",
        "created_at": now,
        "escalation_level": 0,
        "channels_dispatched": ["in_app"],
        "dispatch_status": {"in_app": "sent"},
    }

    response = AlertResponse(**data)

    assert response.alert_type == "threshold_breach"
    assert response.severity == "critical"
    assert response.escalation_level == 0
    assert response.acknowledged_at is None  # Default None for optional fields
    assert "in_app" in response.channels_dispatched


# ---------------------------------------------------------------------------
# Escalation logic tests
# ---------------------------------------------------------------------------


def test_escalation_timeout_logic() -> None:
    """
    EscalationService._get_escalation_timeout() returns correct timedeltas.
    Level 0 = 15 minutes (nurse to doctor threshold).
    Level 1 = 30 minutes (doctor to clinic_admin threshold).
    """
    from app.modules.alerts_staging.escalation import EscalationService

    # Construct a minimal EscalationService without real DB dependencies
    # _get_escalation_timeout is a pure function (no DB interaction)
    mock_db = MagicMock()
    mock_audit = MagicMock()
    tenant_id = uuid.uuid4()

    svc = EscalationService(db=mock_db, audit_service=mock_audit, tenant_id=tenant_id)

    # Level 0: Nurse acknowledgment window = 15 minutes
    timeout_level_0 = svc._get_escalation_timeout(0)
    assert timeout_level_0 == timedelta(minutes=15), (
        f"Expected 15 minutes for level 0, got {timeout_level_0}"
    )

    # Level 1: Doctor acknowledgment window = 30 minutes
    timeout_level_1 = svc._get_escalation_timeout(1)
    assert timeout_level_1 == timedelta(minutes=30), (
        f"Expected 30 minutes for level 1, got {timeout_level_1}"
    )

    # Level 2+: Beyond max — should also return 30 minutes (defensive fallback)
    timeout_level_2 = svc._get_escalation_timeout(2)
    assert timeout_level_2 == timedelta(minutes=30)
