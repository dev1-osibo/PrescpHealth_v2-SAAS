"""
PrescpHealth Backend — Integrations Exceptions.

All error messages reference IDs and metadata only.
Credentials, endpoint URLs, and PHI never appear in exception messages.
"""

import uuid


class IntegrationError(Exception):
    """Base class for all integration errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConnectorNotFoundError(IntegrationError):
    """Raised when a connector configuration cannot be located."""

    def __init__(self, connector_id: uuid.UUID) -> None:
        super().__init__(
            message=f"Connector {connector_id} not found",
            status_code=404,
        )
        self.connector_id = connector_id


class ConnectorAlreadyExistsError(IntegrationError):
    """Raised when attempting to create a duplicate connector."""

    def __init__(self, name: str) -> None:
        # name is non-PHI (admin label), safe to include
        super().__init__(
            message=f"A connector named '{name}' already exists for this tenant",
            status_code=409,
        )


class SyncAlreadyRunningError(IntegrationError):
    """Raised when a sync is triggered while one is already in progress."""

    def __init__(self, connector_id: uuid.UUID) -> None:
        super().__init__(
            message=f"Connector {connector_id} has a sync already in progress",
            status_code=409,
        )


class ConnectorConnectionError(IntegrationError):
    """Raised when the connector cannot reach the external system."""

    def __init__(self, connector_id: uuid.UUID) -> None:
        # endpoint URL is NOT included — may expose internal network topology
        super().__init__(
            message=f"Connector {connector_id}: failed to reach external system",
            status_code=502,
        )


class SyncLogNotFoundError(IntegrationError):
    """Raised when a sync log entry cannot be located."""

    def __init__(self, log_id: uuid.UUID) -> None:
        super().__init__(
            message=f"Sync log {log_id} not found",
            status_code=404,
        )
