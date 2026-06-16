"""
PrescpHealth Backend — Integration Connectors Package.

Contains stub connector implementations for each supported external system.
Each connector provides a standard interface:
    - pull_*()  — Fetch data from external system
    - push_*()  — Send data to external system
    - resolve_conflict() — Handle data discrepancies

All connectors are STUBS — they simulate the interface without making
real HTTP calls. Production connectors would:
    1. Use httpx AsyncClient for HTTP calls.
    2. Handle authentication per auth_type (basic, oauth2, api_key).
    3. Implement proper retry logic via SyncEngine.retry_with_backoff().
    4. Map external data formats to internal FHIR/ORM models.

Security:
    Connector credentials (from ConnectorConfig.credentials) are passed
    in at runtime. They are NEVER logged in any code path.
"""

from app.modules.integrations.connectors.openmrs import OpenMRSConnector  # noqa: F401
from app.modules.integrations.connectors.dhis2 import DHIS2Connector  # noqa: F401
from app.modules.integrations.connectors.generic_fhir import GenericFHIRConnector  # noqa: F401

__all__ = ["OpenMRSConnector", "DHIS2Connector", "GenericFHIRConnector"]
