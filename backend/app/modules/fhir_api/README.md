# FHIR API Module (Staging)

FHIR R4-compliant REST API for external system interoperability.

## Supported Resources

- Encounter
- MedicationRequest
- ServiceRequest
- DiagnosticReport
- Patient

## Endpoints

```
GET    /api/v1/fhir/r4/{resourceType}           Search resources
GET    /api/v1/fhir/r4/{resourceType}/{id}      Read resource
POST   /api/v1/fhir/r4/{resourceType}           Create resource
PUT    /api/v1/fhir/r4/{resourceType}/{id}      Update resource
GET    /api/v1/fhir/r4/$export                  Bulk export (async)
GET    /api/v1/fhir/r4/$export-status/{id}      Poll export status
POST   /api/v1/fhir/r4/Subscription             Create webhook subscription
```

## FHIR Search Parameters

| Parameter | Resources | Description |
|-----------|-----------|-------------|
| `_id` | All | Resource UUID |
| `patient` | All | Patient reference (`Patient/{uuid}` or plain UUID) |
| `status` | Encounter, MedicationRequest, ServiceRequest, DiagnosticReport | Resource status |
| `date` | Encounter | Date range with FHIR prefixes (ge, le, gt, lt, eq) |
| `code` | ServiceRequest, DiagnosticReport | Clinical code |

## Authentication

- **External systems**: OAuth 2.0 Client Credentials (STUB)
- **Internal staff**: Doctor or Clinic_Admin JWT token

## Bulk Export

The bulk export (`$export`) is asynchronous:
1. `GET /fhir/r4/$export` → `202 Accepted` + `Content-Location` header
2. `GET /fhir/r4/$export-status/{task_id}` → poll until complete
3. Download NDJSON files from returned URLs

**STUB**: No actual export is performed in this staging implementation.

## Subscriptions

FHIR Subscriptions allow external systems to receive webhook notifications
when resources change. **STUB**: Configurations are stored in memory only.

## No Migration Required

This module reads/writes through existing tables.
