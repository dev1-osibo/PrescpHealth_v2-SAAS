# Registration Module (Staging)

Handles patient intake, consent capture, identity verification, and registration completion.

## Module Structure

| File | Purpose |
|------|---------|
| `enums.py` | `ConsentType`, `VerificationType` |
| `exceptions.py` | `RegistrationNotFoundError`, `RegistrationIncompleteError`, `ConsentNotFoundError`, `ConsentAlreadyRevokedError` |
| `models.py` | `Consent`, `IdentityVerification` ORM models |
| `schemas.py` | Pydantic request/response schemas |
| `service.py` | `RegistrationService` — intake, update, complete, MRN generation |
| `service_consent.py` | `ConsentService` — capture, revoke, check, list active |
| `router.py` | FastAPI router — 5 endpoints |

## Migration
`0021_registration_tables.py` — creates `consents` and `identity_verifications` tables.

## Endpoints

| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | `/api/v1/registration/intake` | Nurse, Clinic_Admin | Start intake |
| PUT | `/api/v1/registration/{patient_id}` | Nurse, Clinic_Admin | Update registration |
| POST | `/api/v1/registration/{patient_id}/consent` | Nurse, Clinic_Admin | Capture consent |
| POST | `/api/v1/registration/{patient_id}/identity` | Nurse, Clinic_Admin | Record identity verification |
| POST | `/api/v1/registration/{patient_id}/complete` | Nurse, Clinic_Admin | Finalize + generate MRN |

## Registration Workflow

```
1. POST /intake          → patient_id returned (status: intake)
2. PUT /{patient_id}     → fill in address, phone, insurance, etc.
3. POST /consent         → capture HIPAA notice + treatment consents
4. POST /identity        → record government ID verification
5. POST /complete        → validate fields → generate MRN → status: active
```

## MRN Format
`MRN-{TENANT_SHORT}-{SEQUENCE}`
- `TENANT_SHORT` = first 6 hex characters of tenant UUID (uppercase)
- `SEQUENCE` = count of existing tenant patients + 1, zero-padded to 6 digits

## HIPAA Compliance
- `digital_signature` (Consent): NEVER logged — base64 biometric/signature data
- `document_number` (IdentityVerification): NEVER logged — government ID number
- `IdentityVerificationResponse` schema omits `document_number` from API responses
- All responses include `Cache-Control: no-store` headers
- All mutations audit-logged via `AuditService`
