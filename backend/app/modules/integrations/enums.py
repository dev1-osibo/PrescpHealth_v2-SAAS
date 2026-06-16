"""
PrescpHealth Backend — Integrations Enums.

Enumerations for the integrations module.
str-Enum for clean JSON serialization.
"""

from enum import Enum


class ConnectorType(str, Enum):
    """
    Type of external system being connected to.

    openmrs        — OpenMRS electronic medical records
    dhis2          — DHIS2 district health information system
    generic_fhir   — Any FHIR R4 compliant server
    """

    OPENMRS = "openmrs"
    DHIS2 = "dhis2"
    GENERIC_FHIR = "generic_fhir"


class AuthType(str, Enum):
    """
    Authentication method used to connect to the external system.

    Credentials are stored in ConnectorConfig.credentials JSONB (never logged).
    """

    BASIC = "basic"       # Username + password
    OAUTH2 = "oauth2"     # OAuth 2.0 client credentials
    API_KEY = "api_key"   # API key / token in header


class SyncDirection(str, Enum):
    """
    Data flow direction for a connector.

    inbound      — Pull data FROM external system INTO PrescpHealth.
    outbound     — Push data FROM PrescpHealth TO external system.
    bidirectional — Both; conflict resolution applies.
    """

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(str, Enum):
    """
    Status of a single sync execution run.

    started   — Sync initiated; records being processed.
    completed — All records processed successfully.
    failed    — Sync aborted due to unrecoverable error.
    partial   — Some records processed; others failed.
    """

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
