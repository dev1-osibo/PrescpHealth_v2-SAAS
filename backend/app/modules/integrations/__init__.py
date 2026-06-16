"""
PrescpHealth Backend — Integrations Module (Staging).

Provides configurable data connectors for syncing clinical data between
PrescpHealth and external systems (OpenMRS, DHIS2, generic FHIR servers).

Submodules:
    enums           — ConnectorType, AuthType, SyncDirection, SyncStatus
    exceptions      — Domain-specific error classes
    models          — ConnectorConfig, SyncLog ORM models
    schemas         — Pydantic request/response schemas
    service         — Connector CRUD and sync orchestration
    sync_engine     — Core sync logic with retry and conflict resolution
    connectors/     — Per-system connector stubs (OpenMRS, DHIS2, generic FHIR)
    tasks           — Celery async tasks
    router          — FastAPI route definitions

Security:
    ConnectorConfig.credentials JSONB is encrypted at rest.
    Credentials are NEVER logged in any code path.
    Only connector IDs and sync metadata appear in logs.

HIPAA:
    SyncLog.error_summary contains NO PHI — metadata only.
    Cache-Control: no-store on all API responses.
"""

from app.modules.integrations.enums import (  # noqa: F401
    AuthType,
    ConnectorType,
    SyncDirection,
    SyncStatus,
)
from app.modules.integrations.models import (  # noqa: F401
    ConnectorConfig,
    SyncLog,
)

__all__ = [
    "AuthType",
    "ConnectorType",
    "SyncDirection",
    "SyncStatus",
    "ConnectorConfig",
    "SyncLog",
]
