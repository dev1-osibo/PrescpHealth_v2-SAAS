# Integrations Module (Staging)

Configurable data sync connectors for external EMR/health information systems.

## Supported Systems

| System | Type | Auth | Direction |
|--------|------|------|-----------|
| OpenMRS | `openmrs` | Basic | Bidirectional |
| DHIS2 | `dhis2` | Basic / API Key | Outbound only |
| Generic FHIR | `generic_fhir` | Basic / OAuth2 / API Key | Bidirectional |

## Features

- **Connector Management** — Create, update, and activate/deactivate connectors
- **Scheduled Sync** — Cron-based automatic sync via Celery
- **Manual Trigger** — Immediate sync via API
- **Retry with Backoff** — 5 retries: 30s, 2min, 8min, 30min, 2h
- **Conflict Resolution** — Last-write-wins with audit trail
- **Sync Logs** — Full audit history per connector

## Security

- `credentials` JSONB is **never** returned in API responses
- `credentials` is **never** logged in any code path
- `base_url` is not logged (may reveal internal network topology)
- All mutations are audit-logged via `AuditService`

## Endpoints

```
POST   /api/v1/integrations/connectors              Create connector
GET    /api/v1/integrations/connectors              List connectors
GET    /api/v1/integrations/connectors/{id}         Connector details
PUT    /api/v1/integrations/connectors/{id}         Update connector
POST   /api/v1/integrations/connectors/{id}/sync    Trigger sync (async, 202)
GET    /api/v1/integrations/connectors/{id}/logs    Sync history
```

## RBAC

All endpoints require `Clinic_Admin` or `Super_Admin`.

## Migration

`backend/alembic/versions/0024_integrations_tables.py`

## Celery Tasks

| Task | Queue | Schedule |
|------|-------|----------|
| `run_sync_task` | `integrations` | On demand |
| `scheduled_sync_check` | `scheduled` | Every 5 minutes |
