"""
PrescpHealth Backend — DHIS2 Connector (STUB).

Provides a stub integration with DHIS2 (https://dhis2.org).
DHIS2 is used for aggregate public health reporting (non-individual data).

STUB: No real HTTP calls are made.

Production implementation would:
    1. Use httpx AsyncClient with basic or API key auth.
    2. POST to /api/dataValueSets for aggregate data.
    3. Use DHIS2 metadata API to resolve orgUnit and dataElement IDs.
    4. Handle DHIS2 import summaries (success/conflict/error counts).

PHI Note:
    DHIS2 receives AGGREGATE data only — no individual patient records.
    This is by design for public health reporting compliance.

Security:
    Credentials and base_url are never logged.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DHIS2Connector:
    """
    DHIS2 aggregate data push connector (STUB).

    Designed for outbound-only sync (PrescpHealth → DHIS2).
    Sends aggregate counts and statistics, not individual patient records.
    """

    def __init__(
        self,
        connector_id: uuid.UUID,
        base_url: str,
        credentials: dict[str, Any],
    ) -> None:
        """
        Initialise the DHIS2 connector.

        Args:
            connector_id: Connector config UUID (for logging only).
            base_url: DHIS2 base URL — not logged.
            credentials: Auth credentials — NEVER logged.
        """
        self.connector_id = connector_id
        self._base_url = base_url
        self._credentials = credentials  # NEVER log this

    async def push_aggregate_data(
        self,
        period: str,
        org_unit_id: str,
        data_values: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Push aggregate data values to DHIS2.

        STUB: Simulates a successful push. Production would POST to:
            {base_url}/api/dataValueSets

        Args:
            period: DHIS2 period string (e.g., "202601" for Jan 2026).
            org_unit_id: DHIS2 organisation unit UID.
            data_values: List of {dataElement, value} dicts (aggregate counts).

        Returns:
            DHIS2 import summary dict.
        """
        logger.info(
            "dhis2_push_aggregate_stub",
            connector_id=str(self.connector_id),
            period=period,
            org_unit_id=org_unit_id,
            data_element_count=len(data_values),
        )
        # STUB: simulate successful DHIS2 import
        return {
            "status": "SUCCESS",
            "importCount": {
                "imported": len(data_values),
                "updated": 0,
                "ignored": 0,
                "deleted": 0,
            },
            "conflicts": [],
        }

    def format_dhis2_payload(
        self,
        period: str,
        org_unit_id: str,
        metrics: dict[str, int | float],
    ) -> dict[str, Any]:
        """
        Format internal metrics into a DHIS2 dataValueSet payload.

        Converts internal metric names to DHIS2 dataElement UIDs using
        a mapping table. Unknown metrics are skipped with a warning.

        Args:
            period: DHIS2 period string.
            org_unit_id: DHIS2 organisation unit UID.
            metrics: Dict of {metric_name: value} (e.g., {"encounters_total": 42}).

        Returns:
            DHIS2-formatted dataValueSet dict ready for API submission.
        """
        # Stub mapping: internal metric name → DHIS2 dataElement UID
        # Production: load this mapping from ConnectorConfig.credentials or a config table
        _METRIC_MAP: dict[str, str] = {
            "encounters_total": "DE_ENCOUNTERS_001",
            "admissions_total": "DE_ADMISSIONS_001",
            "discharges_total": "DE_DISCHARGES_001",
            "medications_dispensed": "DE_MEDICATIONS_001",
        }

        data_values = []
        for metric_name, value in metrics.items():
            dhis2_element = _METRIC_MAP.get(metric_name)
            if dhis2_element is None:
                logger.warning(
                    "dhis2_unknown_metric",
                    metric=metric_name,
                    connector_id=str(self.connector_id),
                )
                continue
            data_values.append({
                "dataElement": dhis2_element,
                "period": period,
                "orgUnit": org_unit_id,
                "value": str(value),  # DHIS2 expects string values
            })

        return {
            "dataSet": "DS_PRESCPHEALTH_001",  # DHIS2 dataset UID (stub)
            "period": period,
            "orgUnit": org_unit_id,
            "dataValues": data_values,
        }
