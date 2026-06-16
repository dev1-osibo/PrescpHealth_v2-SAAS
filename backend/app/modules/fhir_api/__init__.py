"""
PrescpHealth Backend — FHIR API Module (Staging).

Provides FHIR R4-compliant REST endpoints for external system interoperability.
Supports: Encounter, MedicationRequest, ServiceRequest, DiagnosticReport, Patient.

Submodules:
    service         — FHIR R4 resource CRUD orchestration
    validator       — FHIR R4 required-field validation
    search          — FHIR search parameter parsing
    auth_oauth      — OAuth 2.0 client credentials (STUB)
    subscriptions   — Webhook subscription management (STUB)
    schemas         — Pydantic models for FHIR request/response
    router          — FHIR CRUD endpoints
    router_bulk     — Bulk data export endpoint

Architecture:
    External clients authenticate via OAuth 2.0 (STUB).
    Internal staff use existing Doctor/Clinic_Admin JWT tokens.
    All FHIR resources are mapped to/from internal ORM models.
    No PHI in logs — only resource_type and resource_id (UUID).

HIPAA:
    Cache-Control: no-store on all FHIR responses.
    PHI fields in FHIR JSON are stored/returned but never logged.
"""

__all__ = [
    "SUPPORTED_RESOURCES",
]

# Resources supported by this FHIR module
SUPPORTED_RESOURCES = frozenset(
    ["Encounter", "MedicationRequest", "ServiceRequest", "DiagnosticReport", "Patient"]
)
