"""
PrescpHealth Backend — Alert System Enums.
Enumerations for alert types, severities, statuses, threshold conditions, and dispatch channels.
"""
from enum import Enum


class AlertType(str, Enum):
    """Classifies the origin/reason of a clinical alert."""
    THRESHOLD_BREACH = "threshold_breach"       # A measurement exceeded a configured threshold
    RISK_CRITICAL = "risk_critical"             # A computed risk score entered a critical range
    FORECAST_WARNING = "forecast_warning"       # Forecasted trajectory indicates future risk
    MISSED_FOLLOWUP = "missed_followup"         # Patient missed a scheduled follow-up
    DRUG_INTERACTION = "drug_interaction"       # A potentially dangerous drug combination detected


class AlertSeverity(str, Enum):
    """
    Clinical urgency levels aligned with standard triage conventions.
    Used to determine escalation priority and dispatch channel selection.
    """
    CRITICAL = "critical"   # Immediate clinical action required
    HIGH = "high"           # Urgent; action within minutes to hours
    MODERATE = "moderate"   # Action required within hours to one day
    LOW = "low"             # Non-urgent; informational with action within days
    INFO = "info"           # Purely informational; no required action


class AlertStatus(str, Enum):
    """
    Lifecycle states for an alert record.
    Transitions: active → acknowledged | escalated → resolved | expired
    """
    ACTIVE = "active"               # Newly created; awaiting clinician acknowledgment
    ACKNOWLEDGED = "acknowledged"   # Clinician has reviewed and acknowledged the alert
    ESCALATED = "escalated"         # Unacknowledged past timeout; escalated to higher-level user
    RESOLVED = "resolved"           # Alert condition no longer exists or care was delivered
    EXPIRED = "expired"             # Alert aged out without acknowledgment (low/info severity only)


class ThresholdCondition(str, Enum):
    """
    Logical conditions for threshold breach evaluation.
    Determines which direction or state change triggers an alert.
    """
    ABOVE = "above"                     # Measured value exceeds threshold_value
    BELOW = "below"                     # Measured value is below threshold_value
    ENTERS_STRATUM = "enters_stratum"   # Risk score moves into a named risk stratum


class DispatchChannel(str, Enum):
    """
    Delivery channels for alert notifications.
    Each channel has independent retry logic and delivery status tracking.
    """
    IN_APP = "in_app"           # In-application notification (always attempted first)
    EMAIL = "email"             # Email notification (24-hour retry window)
    SMS = "sms"                 # SMS text message (6-hour retry window)
    WHATSAPP = "whatsapp"       # WhatsApp message (future integration)
