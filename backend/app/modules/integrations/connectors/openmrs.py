"""
PrescpHealth Backend — OpenMRS Connector (STUB).

Provides a stub integration with OpenMRS (https://openmrs.org).
OpenMRS uses the FHIR R4 API for modern integrations.

STUB: No real HTTP calls are made. Methods return simulated data
that mirrors the OpenMRS REST API response structure.

Production implementation would:
    1. Use httpx AsyncClient with basic auth (from credentials).
    2. Call /openmrs/ws/fhir2/R4/ endpoints.
    3. Map OpenMRS FHIR responses to internal models.
    4. Handle OpenMRS-specific extensions (e.g., obs, programs).

Security:
    Credentials passed in via ConnectorConfig — NEVER logged.
    base_url is NOT logged (may reveal internal network topology).
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class OpenMRSConnector:
    """
    OpenMRS FHIR R4 connector (STUB).

    Instantiated with connector config at sync time.
    All methods are async to support production httpx calls.
    """

    def __init__(self, connector_id: uuid.UUID, base_url: str, credentials: dict[str, Any]) -> None:
        """
        Initialise the connector.

        Args:
            connector_id: Connector config UUID (for logging).
            base_url: OpenMRS base URL — not logged.
            credentials: Auth credentials — NEVER logged.
        """
        self.connector_id = connector_id
        # Store but do not log base_url or credentials
        self._base_url = base_url
        self._credentials = credentials  # NEVER log this

    async def pull_patients(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Pull patient records from OpenMRS as FHIR Patient resources.

        STUB: Returns empty list. Production would call:
            GET /openmrs/ws/fhir2/R4/Patient?_lastUpdated=gt{since}&_count={limit}

        Args:
            since: Only pull records updated after this datetime.
            limit: Maximum records to pull per batch.

        Returns:
            List of FHIR Patient resource dicts.
        """
        logger.info(
            "openmrs_pull_patients_stub",
            connector_id=str(self.connector_id),
            since=since.isoformat() if since else None,
            limit=limit,
        )
        # STUB: return empty list (no real HTTP call)
        return []

    async def push_encounters(
        self,
        encounters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Push encounter records to OpenMRS as FHIR Encounter resources.

        STUB: Simulates a successful push. Production would call:
            POST /openmrs/ws/fhir2/R4/Encounter for each encounter,
            or use FHIR Bundle transaction for batch efficiency.

        Args:
            encounters: List of FHIR Encounter resource dicts.

        Returns:
            Summary dict with success/failure counts.
        """
        logger.info(
            "openmrs_push_encounters_stub",
            connector_id=str(self.connector_id),
            count=len(encounters),
        )
        # STUB: simulate successful push
        return {
            "total": len(encounters),
            "succeeded": len(encounters),
            "failed": 0,
            "errors": [],
        }

    async def resolve_conflict(
        self,
        local_record: dict[str, Any],
        remote_record: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Resolve a data conflict between local and OpenMRS records.

        Uses last-write-wins strategy based on lastUpdated timestamps.
        Conflict is logged (metadata only, not PHI values).

        Args:
            local_record: Internal record with meta.lastUpdated.
            remote_record: OpenMRS FHIR resource with meta.lastUpdated.

        Returns:
            The record to use (winner of conflict resolution).
        """
        local_ts = local_record.get("meta", {}).get("lastUpdated", "")
        remote_ts = remote_record.get("meta", {}).get("lastUpdated", "")

        # Last-write-wins: whichever has the more recent timestamp wins
        winner = remote_record if remote_ts > local_ts else local_record

        logger.info(
            "openmrs_conflict_resolved",
            connector_id=str(self.connector_id),
            strategy="last_write_wins",
            winner="remote" if winner is remote_record else "local",
            # Log timestamps (non-PHI metadata)
            local_ts=local_ts,
            remote_ts=remote_ts,
        )
        return winner
