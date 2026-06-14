# Documents Module (Staging)

Handles secure upload, storage, retrieval, and metadata management of clinical documents.

## Module Structure

| File | Purpose |
|------|---------|
| `enums.py` | `DocumentType`, `ALLOWED_MIME_TYPES`, `MAX_FILE_SIZE_BYTES` |
| `exceptions.py` | `DocumentNotFoundError`, `InvalidMimeTypeError`, `FileSizeExceededError`, `StorageError` |
| `models.py` | `Document` SQLAlchemy ORM model (immutable) |
| `schemas.py` | Pydantic request/response schemas |
| `storage.py` | `StorageBackend` ABC, `LocalStorageBackend`, `S3StorageBackend` (stub) |
| `service.py` | `DocumentService` — upload, download, list |
| `router.py` | FastAPI router — 5 endpoints |

## Migration
`0020_documents_table.py` — creates `documents` table (no `updated_at`).

## Endpoints

| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | `/api/v1/documents` | Doctor, Nurse, Clinic_Admin | Upload (multipart) |
| GET | `/api/v1/documents` | Doctor, Nurse | List with filters |
| GET | `/api/v1/documents/{id}` | Doctor, Nurse | Metadata |
| GET | `/api/v1/documents/{id}/download` | Doctor, Nurse | Stream file bytes |
| GET | `/api/v1/patients/{id}/documents` | Doctor, Nurse | Patient docs |

## Allowed MIME Types
`application/pdf`, `image/jpeg`, `image/png`, `image/tiff`, `application/dicom`

## Max File Size
25 MiB (26,214,400 bytes)

## Storage Abstraction
`LocalStorageBackend` saves files to `backend/uploads/{tenant_id}/{document_id}/{filename}`.
`S3StorageBackend` is a stub — raises `NotImplementedError` until configured.

## Document Immutability
Documents have no `updated_at` column. Once uploaded, only metadata reads and downloads are permitted. Hard deletes are not implemented.

## HIPAA Compliance
- All responses include `Cache-Control: no-store` headers
- `file_name`, `storage_path`, `title` are never logged — log document UUID only
- `is_encrypted=True` is always set (encryption delegated to storage layer)
- All mutations audit-logged via `AuditService`
