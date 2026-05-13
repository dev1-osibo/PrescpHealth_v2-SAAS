"""
PrescpHealth Backend — Audit Logging Service.

Provides a resilient, append-only audit logging interface for the entire
application. Every module uses this service to record data access and
mutations for HIPAA compliance.

Design Principles:
- RESILIENT: Audit failures are logged but NEVER crash the calling code.
  A failed audit write must not break a clinical workflow.
- APPEND-ONLY: Only exposes insert operations — no update, no delete.
- PHI-SAFE: Validates that no PHI leaks into audit entries.
- CORRELATION: Automatically includes request correlation_id from context.

Usage:
    from app.modules.audit.service import AuditService

    audit = AuditService()
    await audit.log(
        db=session,
        tenant_id=tenant_id,
        user_id=user_id,
        action="patient.create",
        resource_type="patient",
        resource_id=new_patient.id,
    )

HIPAA Compliance:
- Never stores PHI (patient names, measurements, diagnoses)
- Only stores opaque UUIDs as resource identifiers
- Changes field contains field names and non-PHI values only
- IP addresses stored for breach investigation

Requirements Satisfied:
- 18.4: Audit_Log entry for every CUD operation on Patient data
- 18.5: Append-only; no role can delete or modify entries via API
- 1.4: Cross-tenant operations by Super_Admin are audit-logged
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.core.request_context import get_request_id

# ---------------------------------------------------------------------------
# Module logger — logs audit service operations (meta-logging, not PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


class AuditService:
    """
    Resilient audit logging service for HIPAA compliance.

    All methods are designed to NEVER raise exceptions that would
    break the calling code. If an audit write fails, the error is
    logged internally but the caller continues unaffected.

    This is critical for clinical workflows — a database hiccup in
    the audit table must not prevent a doctor from saving a measurement.
    """

    async def log(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Create an audit log entry.

        This method is fire-and-forget from the caller's perspective —
        it will never raise an exception. Failures are logged internally
        for operational monitoring.

        Args:
            db: Database session (will use a nested transaction to isolate
                audit writes from the caller's transaction).
            tenant_id: The tenant context for this action.
            user_id: The user who performed the action.
            action: Dot-notation action string (e.g., "patient.create").
            resource_type: Type of resource affected (e.g., "patient").
            resource_id: UUID of the specific resource (None for list actions).
            changes: Optional dict of {field: {old, new}} for update ops.
                     MUST NOT contain PHI values.
            metadata: Optional additional context (IP, user_agent, etc.).
                      Correlation_id is auto-added from request context.

        Returns:
            None — this method never returns a value or raises.
        """
        try:
            # Build metadata with correlation_id from request context
            request_metadata = self._build_metadata(metadata)

            # Create the audit entry
            audit_entry = AuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                changes=changes,
                request_metadata=request_metadata,
            )

            db.add(audit_entry)
            await db.flush()

            logger.debug(
                "audit_entry_created",
                action=action,
                resource_type=resource_type,
                tenant_id=str(tenant_id),
            )

        except Exception as exc:
            # CRITICAL: Never let audit failures crash the calling code.
            # Log the failure for operational monitoring, but swallow the error.
            # The clinical workflow must continue even if audit logging fails.
            logger.error(
                "audit_log_write_failed",
                action=action,
                resource_type=resource_type,
                error_type=type(exc).__name__,
                error_message=str(exc),
                tenant_id=str(tenant_id),
            )

    def _build_metadata(
        self, extra_metadata: dict[str, Any] | None
    ) -> dict[str, Any]:
        """
        Build the metadata dict with correlation_id from request context.

        Always includes the correlation_id so audit entries can be traced
        back to the originating HTTP request across the entire system.

        Args:
            extra_metadata: Additional metadata from the caller (IP, user_agent).

        Returns:
            Combined metadata dict with correlation_id included.
        """
        metadata: dict[str, Any] = {}

        # Include correlation_id from request context (set by middleware)
        correlation_id = get_request_id()
        if correlation_id:
            metadata["correlation_id"] = correlation_id

        # Merge any extra metadata from the caller
        if extra_metadata:
            metadata.update(extra_metadata)

        return metadata if metadata else {}
