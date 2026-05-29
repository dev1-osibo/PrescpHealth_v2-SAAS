"""Unit test for audit/models.py re-export."""

from app.modules.audit.models import AuditLog
from app.core.audit import AuditLog as CoreAuditLog


def test_audit_log_reexported_from_module():
    """app.modules.audit.models.AuditLog is the same class as app.core.audit.AuditLog."""
    assert AuditLog is CoreAuditLog


def test_audit_log_has_tablename():
    """AuditLog has __tablename__ defined."""
    assert hasattr(AuditLog, "__tablename__")


def test_module_exports_audit_log_in_all():
    """__all__ lists AuditLog."""
    from app.modules.audit import models
    assert "AuditLog" in models.__all__
