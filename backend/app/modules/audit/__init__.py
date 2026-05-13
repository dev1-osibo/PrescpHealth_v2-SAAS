"""
PrescpHealth Backend — Audit Log Module.

Provides append-only audit logging for HIPAA compliance:
- Records all create, update, and delete operations on patient data
- Captures who (user_id), what (action), when (timestamp),
  from where (IP/metadata), which tenant, and which resource
- Enforced append-only at the database level (no UPDATE/DELETE grants)
- Monthly partitioning for 7-year retention management
- RLS on tenant_id for tenant isolation of audit records

Module Components:
- AuditLog model (core/audit.py) — SQLAlchemy model for the audit_logs table
- AuditService (service.py) — resilient service for creating audit entries
- AuditLogResponse, AuditLogFilter (schemas.py) — Pydantic schemas
- router (router.py) — read-only API endpoints for querying audit trail

Security Architecture:
- Insert-only DB role (audit_writer) — no UPDATE, no DELETE permissions
- No application API exposes delete/update on audit entries
- Even Super_Admin cannot modify audit records through the application
- Monthly partitions allow efficient retention management (DROP old partitions)
- AuditService never raises — failures are logged but don't crash callers

HIPAA Compliance:
- Never logs PHI (patient names, measurements, diagnoses)
- Logs only opaque IDs (patient_id UUID) and action metadata
- Changes field stores field names and old/new values for non-PHI fields
- 7-year minimum retention per HIPAA Security Rule

Usage:
    from app.core.audit import AuditLog  # Preferred (canonical location)
    from app.modules.audit import AuditLog  # Also works (module re-export)
    from app.modules.audit.service import AuditService  # For creating entries
"""

from app.core.audit import AuditLog
from app.modules.audit.service import AuditService

__all__ = ["AuditLog", "AuditService"]
