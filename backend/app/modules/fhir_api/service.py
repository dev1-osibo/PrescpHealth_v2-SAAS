"""
PrescpHealth Backend — FHIR R4 Service.

Orchestrates CRUD operations for supported FHIR R4 resources.
Translates between FHIR JSON and internal ORM models.

Supported resources:
    Encounter, MedicationRequest, ServiceRequest, DiagnosticReport, Patient

FHIR R4 Reference:
    https://www.hl7.org/fhir/R4/

PHI:
    FHIR resource JSON contains PHI. It is stored and returned but NEVER logged.
    Only resource_type and resource_id (UUIDs) appear in log messages.
"""

import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.fhir_api.search import FHIRSearchParams
from app.modules.fhir_api.validator import (
    build_operation_outcome,
    validate_fhir_resource,
)

logger = structlog.get_logger(__name__)
_audit = AuditService()

# Internal table names for each supported FHIR resource type
_RESOURCE_TABLE_MAP: dict[str, str] = {
    "Encounter": "encounters",
    "Patient": "patients",
    "MedicationRequest": "prescriptions",  # Internal table name
    "ServiceRequest": "service_requests",
    "DiagnosticReport": "diagnostic_reports",
}

# The FHIR JSON column on each table (for tables that store fhir_json)
_FHIR_COLUMN_MAP: dict[str, str] = {
    "Encounter": "fhir_json",
    "Patient": "fhir_json",
    "MedicationRequest": "fhir_json",
    "ServiceRequest": "fhir_json",
    "DiagnosticReport": "fhir_json",
}


class FHIRService:
    """
    FHIR R4 resource operations for external API consumers.

    All methods validate incoming resources, map to internal models,
    and return FHIR-formatted responses.
    """

    def validate_resource(
        self,
        resource_type: str,
        fhir_json: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Validate a FHIR R4 resource and return OperationOutcome on failure.

        Args:
            resource_type: Expected resource type.
            fhir_json: Parsed FHIR JSON.

        Returns:
            None if valid, or OperationOutcome dict if validation fails.
        """
        errors = validate_fhir_resource(resource_type, fhir_json)
        if errors:
            return build_operation_outcome(errors)
        return None

    def parse_to_internal(
        self,
        resource_type: str,
        fhir_json: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Convert a FHIR R4 resource to an internal representation dict.

        Extracts common fields (id, status, subject) and maps them to
        internal field names. Resource-specific mapping is handled by
        private helpers.

        Args:
            resource_type: FHIR resource type.
            fhir_json: Validated FHIR JSON.

        Returns:
            Internal dict with normalised field names.
        """
        # Common fields across most FHIR resources
        internal: dict[str, Any] = {
            "fhir_resource_type": resource_type,
            "status": fhir_json.get("status"),
            "fhir_json": fhir_json,  # Store the full FHIR JSON for roundtrip fidelity
        }

        # Extract subject (patient reference) → patient_id
        subject_ref = fhir_json.get("subject", {}).get("reference", "")
        if "Patient/" in subject_ref:
            patient_id_str = subject_ref.replace("Patient/", "")
            try:
                internal["patient_id"] = uuid.UUID(patient_id_str)
            except ValueError:
                pass

        # Resource-specific field mappings
        if resource_type == "Encounter":
            internal.update(self._parse_encounter(fhir_json))
        elif resource_type == "MedicationRequest":
            internal.update(self._parse_medication_request(fhir_json))

        return internal

    def print_to_fhir(
        self,
        resource_type: str,
        internal_record: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Convert an internal record dict to a FHIR R4 resource JSON.

        If the record has a stored fhir_json, return it directly (preferred).
        Otherwise build a minimal FHIR representation.

        Args:
            resource_type: FHIR resource type.
            internal_record: Dict from the database or internal service.

        Returns:
            FHIR R4 resource dict.
        """
        # If we have stored FHIR JSON, return it directly for roundtrip fidelity
        if "fhir_json" in internal_record and internal_record["fhir_json"]:
            return internal_record["fhir_json"]

        # Build minimal FHIR representation from internal fields
        return self._build_minimal_fhir(resource_type, internal_record)

    async def search(
        self,
        db: AsyncSession,
        resource_type: str,
        params: FHIRSearchParams,
        tenant_id: uuid.UUID,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Search FHIR resources with parameter filters.

        Args:
            db: Async DB session (tenant RLS applied).
            resource_type: FHIR resource type to search.
            params: Parsed FHIR search parameters.
            tenant_id: Tenant context.

        Returns:
            Tuple of (FHIR resource list, total count).
        """
        table = _RESOURCE_TABLE_MAP.get(resource_type)
        if not table:
            return [], 0

        # Build WHERE clauses dynamically from search params
        conditions = ["tenant_id = :tenant_id"]
        bind_params: dict[str, Any] = {"tenant_id": tenant_id}

        if params._id:
            conditions.append("id = :res_id")
            bind_params["res_id"] = params._id
        if params.patient:
            conditions.append("patient_id = :patient_id")
            bind_params["patient_id"] = params.patient
        if params.status:
            conditions.append("status = :status")
            bind_params["status"] = params.status
        if params.date_from:
            conditions.append("created_at >= :date_from")
            bind_params["date_from"] = params.date_from

        where_clause = " AND ".join(conditions)

        # Count query
        count_sql = sa_text(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}")
        total_row = (await db.execute(count_sql, bind_params)).scalar()
        total = int(total_row or 0)

        # Data query — fetch fhir_json if available, else key fields
        data_sql = sa_text(
            f"SELECT id, status, fhir_json FROM {table} "
            f"WHERE {where_clause} "
            f"LIMIT :limit OFFSET :offset"
        )
        bind_params["limit"] = params.limit
        bind_params["offset"] = params.offset

        try:
            rows = (await db.execute(data_sql, bind_params)).mappings().all()
            resources = [
                self.print_to_fhir(resource_type, dict(row)) for row in rows
            ]
        except Exception:
            # Table may not have fhir_json column — return empty stub
            logger.warning("fhir_search_fallback", resource_type=resource_type)
            resources = []
            total = 0

        return resources, total

    async def read_resource(
        self,
        db: AsyncSession,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> Optional[dict[str, Any]]:
        """
        Read a single FHIR resource by ID.

        Args:
            db: Async DB session.
            resource_type: FHIR resource type.
            resource_id: Resource UUID.

        Returns:
            FHIR resource dict or None if not found.
        """
        table = _RESOURCE_TABLE_MAP.get(resource_type)
        if not table:
            return None

        sql = sa_text(
            f"SELECT id, status, fhir_json FROM {table} WHERE id = :res_id"
        )
        try:
            row = (await db.execute(sql, {"res_id": resource_id})).mappings().first()
            if row is None:
                return None
            return self.print_to_fhir(resource_type, dict(row))
        except Exception:
            logger.warning("fhir_read_error", resource_type=resource_type,
                           resource_id=str(resource_id))
            return None

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _parse_encounter(self, fhir_json: dict[str, Any]) -> dict[str, Any]:
        """Extract Encounter-specific fields from FHIR JSON."""
        fields: dict[str, Any] = {}
        enc_class = fhir_json.get("class", {})
        if isinstance(enc_class, dict):
            fields["encounter_class"] = enc_class.get("code", "ambulatory")
        # reason is PHI — stored in internal dict but not logged
        reason_refs = fhir_json.get("reasonCode", [])
        if reason_refs:
            fields["reason_for_visit"] = reason_refs[0].get("text", "")
        return fields

    def _parse_medication_request(self, fhir_json: dict[str, Any]) -> dict[str, Any]:
        """Extract MedicationRequest-specific fields from FHIR JSON."""
        fields: dict[str, Any] = {}
        med = fhir_json.get("medicationCodeableConcept", {})
        if med:
            fields["medication_code"] = med.get("coding", [{}])[0].get("code", "")
            fields["medication_name"] = med.get("text", "")
        return fields

    def _build_minimal_fhir(
        self, resource_type: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a minimal FHIR resource from internal fields."""
        resource: dict[str, Any] = {
            "resourceType": resource_type,
            "id": str(record.get("id", "")),
            "status": record.get("status", "unknown"),
        }
        # Add patient subject reference if available
        if "patient_id" in record and record["patient_id"]:
            resource["subject"] = {"reference": f"Patient/{record['patient_id']}"}
        return resource
