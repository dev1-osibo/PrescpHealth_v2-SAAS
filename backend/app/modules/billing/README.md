# Billing Module (Staging)

Manages the full revenue cycle for clinical encounters.

## Features

- **Invoice Generation** — Auto-builds invoices from encounter billable items
- **Payment Recording** — Tracks cash, card, bank transfer, mobile money, and insurance
- **Insurance Claims** — Submission, approval, denial, and resubmission lifecycle
- **Audit Trail** — Every mutation logged via `AuditService`
- **HIPAA Compliant** — No PHI in logs, `Cache-Control: no-store` on all responses

## Models

| Model | Purpose |
|-------|---------|
| `Invoice` | Per-encounter billing document |
| `InvoiceLineItem` | Individual charges (consultation, procedure, lab, etc.) |
| `Payment` | Cash/card/insurance payments |
| `InsuranceClaim` | Insurance claim lifecycle |

## Endpoints

```
POST   /api/v1/invoices                     Generate invoice from encounter
GET    /api/v1/invoices                     List invoices (filterable)
GET    /api/v1/invoices/{id}                Invoice detail with line items
POST   /api/v1/invoices/{id}/payments       Record payment
POST   /api/v1/invoices/{id}/void           Void invoice
POST   /api/v1/insurance-claims             Submit claim
GET    /api/v1/insurance-claims             List claims
PUT    /api/v1/insurance-claims/{id}/status Update claim status
```

## RBAC

All endpoints require `Clinic_Admin` or higher.

## Migration

`backend/alembic/versions/0022_billing_tables.py`

## Money Handling

All monetary values use `Decimal(10,2)` — never `float`.
