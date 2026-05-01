---
inclusion: always
---

# Security & HIPAA Compliance — PrescpHealth Rebuild

## HIPAA Regulatory Context

PrescpHealth handles Protected Health Information (PHI) and must comply with:
- **HIPAA Privacy Rule** — controls who can access PHI and under what conditions
- **HIPAA Security Rule** — technical safeguards for electronic PHI (ePHI)
- **HIPAA Breach Notification Rule** — incident response requirements
- **HITECH Act** — strengthens HIPAA enforcement, requires encryption

This platform serves clinicians in Africa and underserved communities, so also consider:
- **NDPR (Nigeria Data Protection Regulation)** — where applicable
- **POPIA (South Africa)** — where applicable
- **General data sovereignty** — data residency per tenant configuration

## PHI Protection Rules (Non-Negotiable)

### What counts as PHI
Any data that can identify a patient combined with health information:
- Names, dates of birth, addresses, phone numbers, email
- Medical record numbers, patient IDs (even UUIDs when combined with health data)
- Lab results, diagnoses, medications, risk scores, measurements
- Any AI-generated clinical insights tied to a patient

### Code-Level PHI Rules

1. **Never log PHI** — no patient names, measurements, diagnoses, or risk scores in application logs. Log only opaque IDs (patient_id UUID) and action metadata.

2. **Never expose PHI in errors** — error messages must not contain patient data. Use generic messages with request_id for correlation.

3. **Never cache PHI in browser** — all API responses containing PHI must include:
   ```python
   headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
   headers["Pragma"] = "no-cache"
   ```

4. **Never hard-delete PHI** — soft delete only, with configurable retention (minimum 6 years per HIPAA, our policy: 7 years). Anonymize on soft delete.

5. **Encrypt PHI at rest** — PostgreSQL with TDE or column-level encryption for sensitive fields. Redis data encrypted via application-layer encryption before caching.

6. **Encrypt PHI in transit** — TLS 1.2+ mandatory on all connections (API, DB, Redis, external services).

7. **Minimum necessary principle** — API endpoints return only the PHI needed for the specific use case. No "return everything" endpoints.

## Authentication & Access Control

- JWT access tokens: 15-minute expiry (short-lived to limit exposure)
- Refresh tokens: 7-day expiry with rotation (detect reuse = revoke family)
- MFA required for all clinician roles (TOTP-based)
- Account lockout: 5 failed attempts in 10 minutes
- Session timeout: automatic logout after 30 minutes of inactivity
- Password requirements: minimum 12 chars, complexity rules, bcrypt cost 12

## Tenant Isolation (Critical for Multi-Tenancy)

- PostgreSQL Row-Level Security (RLS) on EVERY table with tenant_id
- RLS enforced at database level — not just application logic
- Tenant context set via PostgreSQL session variable before every query
- Cross-tenant access is IMPOSSIBLE by design, not just by convention
- Super_Admin cross-tenant access uses explicit tenant switching with full audit

## Audit Trail Requirements

- Log ALL access to PHI (reads AND writes) — not just mutations
- Audit logs are append-only (no UPDATE, no DELETE permissions)
- Include: who, what, when, from where (IP), which tenant, which patient
- Retain audit logs for minimum 7 years
- Monthly partitioning for performance and retention management

## Input Validation & Sanitization

- Validate ALL user input at the API boundary (Pydantic schemas)
- Reject inputs that don't match expected patterns — don't try to "fix" them
- SQL injection prevention: SQLAlchemy parameterized queries ONLY (never raw SQL string interpolation)
- XSS prevention: sanitize any user-provided text stored and later rendered
- File upload validation: check MIME type, file size limits, scan for malicious content
- Measurement values: enforce physiological ranges (reject impossible values)

## Secret Management

- Never hardcode secrets (API keys, DB passwords, JWT secrets) in source code
- Use environment variables via pydantic-settings
- `.env` files NEVER committed to git (`.gitignore` enforced)
- Rotate secrets on schedule: JWT signing keys quarterly, API keys annually
- External API keys (OpenAI, Anthropic, SendGrid, Twilio) stored in env vars only

## Data Minimization

- Collect only what's clinically necessary
- De-identify data for population analytics where possible
- Patient portal shows plain-language risk summaries — not raw scores
- Export functions include only requested data fields

## Breach Response (Code-Level Preparation)

- All security events logged to dedicated security audit stream
- Failed auth attempts tracked with IP and user-agent
- Anomaly detection hooks: unusual access patterns, bulk data access, off-hours access
- Rate limiting prevents data harvesting (1000 req/min clinician, 100 req/min patient)

## Secure Coding Patterns

```python
# ALWAYS — parameterized queries
result = await session.execute(
    select(Patient).where(Patient.tenant_id == tenant_id, Patient.id == patient_id)
)

# NEVER — string interpolation in queries
result = await session.execute(f"SELECT * FROM patients WHERE id = '{patient_id}'")
```

```python
# ALWAYS — log without PHI
logger.info("Risk computation completed", extra={
    "patient_id": patient_id,  # UUID is OK
    "disease_count": len(scores),
    "duration_ms": elapsed
})

# NEVER — log with PHI
logger.info(f"Computed risk for {patient.full_name}: stroke={score.value}")
```

```python
# ALWAYS — validate before processing
class MeasurementCreate(BaseModel):
    """Validates measurement input at API boundary."""
    measurement_type: MeasurementType
    value: float = Field(..., ge=0, le=1000)  # Broad range, specific validation in service
    recorded_at: datetime

# NEVER — trust raw input
def save_measurement(data: dict):  # No validation = vulnerability
    ...
```

## Third-Party Service Security

- OpenAI/Anthropic: never send full patient identifiers to LLM APIs. Use anonymized context.
- SendGrid/Twilio: notification content should be minimal ("You have a new alert" not "Your stroke risk is 85%")
- All external API calls use HTTPS only
- Implement circuit breakers and timeouts on all external calls
