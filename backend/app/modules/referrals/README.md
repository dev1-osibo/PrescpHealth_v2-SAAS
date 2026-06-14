# Referrals Module (Staging)

Manages specialist referrals including creation, status transitions, and specialist findings recording.

## Module Structure

| File | Purpose |
|------|---------|
| `enums.py` | `ReferralUrgency`, `ReferralStatus`, `VALID_TRANSITIONS` map |
| `exceptions.py` | `ReferralNotFoundError`, `InvalidStatusTransitionError` |
| `models.py` | `Referral` SQLAlchemy ORM model |
| `schemas.py` | Pydantic request/response schemas |
| `service.py` | `ReferralService` — CRUD + status transitions |
| `router.py` | FastAPI router — 5 endpoints |

## Migration
`0019_referrals_table.py` — creates `referrals` table.

## Endpoints

| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | `/api/v1/referrals` | Doctor | Create referral |
| GET | `/api/v1/referrals` | Doctor, Nurse | List with filters |
| GET | `/api/v1/referrals/{id}` | Doctor, Nurse | Get detail |
| PUT | `/api/v1/referrals/{id}/status` | Doctor | Update status |
| POST | `/api/v1/referrals/{id}/completion` | Doctor | Record findings |

## Status Transition Map

```
pending  → accepted | declined | cancelled
accepted → scheduled | cancelled
scheduled → in_progress | cancelled
in_progress → completed
completed, cancelled, declined = TERMINAL
```

Transitions are validated by `ReferralService.update_status()` using `VALID_TRANSITIONS` dict.

## HIPAA Compliance
- All responses include `Cache-Control: no-store` headers
- No PHI in log messages — UUIDs only
- All mutations audit-logged via `AuditService`
