"""
PrescpHealth Backend — Audit Log Model Re-export.

The canonical AuditLog model lives in app.core.audit because audit logging
is cross-cutting infrastructure used by every module in the system.

This file re-exports the model for backward compatibility and to maintain
the standard module structure (modules/{name}/models.py pattern).

Usage:
    # Preferred import (from core):
    from app.core.audit import AuditLog

    # Also works (from module):
    from app.modules.audit.models import AuditLog
"""

from app.core.audit import AuditLog

__all__ = ["AuditLog"]
