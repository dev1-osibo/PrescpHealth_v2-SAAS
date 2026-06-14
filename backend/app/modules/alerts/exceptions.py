"""PrescpHealth Backend — Alert System Exceptions."""


class AlertError(Exception):
    """Base exception for alert system errors."""

    def __init__(self, message: str = "Alert system error"):
        self.message = message
        super().__init__(self.message)


class AlertNotFoundError(AlertError):
    """Raised when an alert cannot be found."""

    def __init__(self, alert_id: str):
        super().__init__(f"Alert not found: {alert_id}")


class ThresholdConfigurationError(AlertError):
    """Raised when threshold configuration is invalid."""

    def __init__(self, reason: str):
        super().__init__(f"Threshold configuration error: {reason}")


class DispatchFailedError(AlertError):
    """Raised when alert dispatch fails across all channels."""

    def __init__(self, alert_id: str, channel: str):
        super().__init__(f"Dispatch failed for alert {alert_id} on channel {channel}")


class EscalationError(AlertError):
    """Raised when alert escalation fails."""

    def __init__(self, alert_id: str, reason: str):
        super().__init__(f"Escalation failed for alert {alert_id}: {reason}")
