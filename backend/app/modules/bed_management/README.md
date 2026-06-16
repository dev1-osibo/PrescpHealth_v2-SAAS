# Bed Management Module (Staging)

Manages inpatient ward/bed inventory, patient admissions, nursing notes, and vitals.

## Features

- **Ward & Bed Inventory** — Tracks wards with specialty, floor, and bed counts
- **Admission Lifecycle** — Admit → Transfer → Discharge with automatic bed status updates
- **Nursing Notes** — Categorised clinical notes per admission (Assessment, Intervention, etc.)
- **Vitals Charting** — Records vitals and publishes `MeasurementSaved` events
- **Audit Trail** — Every mutation logged via `AuditService`
- **HIPAA Compliant** — No PHI values in logs, `Cache-Control: no-store` on all responses

## Models

| Model | Purpose |
|-------|---------|
| `Ward` | Hospital ward / unit |
| `Bed` | Individual bed within a ward |
| `Admission` | Patient–bed binding with discharge plan |
| `NursingNote` | Clinical nursing documentation |

## Endpoints

```
POST   /api/v1/admissions                     Admit patient to bed (Doctor+)
GET    /api/v1/beds                           Bed availability by ward (Nurse+)
GET    /api/v1/admissions/{id}                Admission detail (Nurse+)
POST   /api/v1/admissions/{id}/nursing-notes  Add nursing note (Nurse+)
POST   /api/v1/admissions/{id}/vitals         Chart vitals (Nurse+)
POST   /api/v1/admissions/{id}/discharge      Discharge patient (Doctor+)
```

## RBAC

| Action | Required Role |
|--------|--------------|
| Admit patient | Doctor+ |
| Discharge patient | Doctor+ |
| Add nursing note | Nurse+ |
| Chart vitals | Nurse+ |
| View bed status | Nurse+ |

## Migration

`backend/alembic/versions/0023_bed_management_tables.py`
