"""
PrescpHealth Backend — Audit Log API Router.

Read-only endpoints for querying the audit trail:
- GET /api/v1/audit — list audit logs (paginated, filtered by tenant via RLS)
- GET /api/v1/audit/{id} — get a single audit entry

NO POST/PUT/DELETE endpoints — audit entries are append-only and created
exclusively by the AuditService at the service layer. This enforces the
immutability guarantee required by HIPAA.

Access Control:
- Super_Admin: can view audit logs across tenants (with explicit switch)
- Clinic_Admin: can view audit logs within their own tenant (RLS enforced)
- All other roles: no access to audit log API

Per API design steering rule:
- All responses use the standard envelope format
- Cursor-based pagination for list endpoint
- No PHI in any response (audit entries never contain PHI by design)

Requirements Satisfied:
- 18.4: Audit entries queryable by authorized administrators
- 18.5: No write/delete endpoints (append-only enforcement)
- 1.4: Super_Admin cross-tenant audit access
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.core.database import get_session_factory, set_tenant_context
from app.core.pagination import (
    PaginationParams,
    encode_cursor,
    decode_cursor,
    get_pagination,
)
from app.modules.audit.schemas import AuditLogResponse
from app.modules.auth.rbac import Role, require_role

# ---------------------------------------------------------------------------
# Module logger — logs audit API access without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition — read-only, admin-only
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/api/v1/audit",
    tags=["audit"],
)


# ---------------------------------------------------------------------------
# GET /api/v1/audit — List audit log entries (paginated + filtered)
# ---------------------------------------------------------------------------
@router.get(
    "",
    response_model=None,
    summary="List audit log entries",
    description="Returns a paginated list of audit log entries for the current "
    "tenant. Supports filtering by user, action, resource type, resource ID, "
    "and date range. Requires Super_Admin or Clinic_Admin role.",
)
async def list_audit_logs(
    request: Request,
    pagination: PaginationParams = Depends(get_pagination),
    user_id: Optional[uuid.UUID] = Query(None, description="Filter by acting user"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[uuid.UUID] = Query(None, description="Filter by resource ID"),
    start_date: Optional[datetime] = Query(None, description="Filter from date (UTC)"),
    end_date: Optional[datetime] = Query(None, description="Filter to date (UTC)"),
    auth_context: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """
    List audit log entries with pagination and optional filters.

    Results are ordered by created_at DESC (most recent first).
    RLS ensures only the current tenant's entries are returned.
    Cursor-based pagination for efficient deep-page access.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        # Set tenant context for RLS isolation
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        # Build query with filters
        query = select(AuditLog).order_by(desc(AuditLog.created_at))

        # Apply optional filters
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            query = query.where(AuditLog.action == action)
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        if start_date:
            query = query.where(AuditLog.created_at >= start_date)
        if end_date:
            query = query.where(AuditLog.created_at <= end_date)

        # Apply cursor-based pagination
        if pagination.cursor:
            cursor_data = decode_cursor(pagination.cursor)
            if cursor_data and cursor_data["field"] == "created_at":
                # For DESC ordering, next page has created_at < cursor value
                cursor_timestamp = datetime.fromisoformat(cursor_data["value"])
                query = query.where(AuditLog.created_at < cursor_timestamp)

        # Fetch one extra to determine has_more
        query = query.limit(pagination.page_size + 1)

        result = await db.execute(query)
        entries = list(result.scalars().all())

        # Determine pagination state
        has_more = len(entries) > pagination.page_size
        if has_more:
            entries = entries[: pagination.page_size]

        # Build cursor for next page
        next_cursor = None
        if has_more and entries:
            last_entry = entries[-1]
            next_cursor = encode_cursor(
                sort_field="created_at",
                sort_value=last_entry.created_at.isoformat(),
                direction="desc",
            )

        # Serialize entries
        items = [_serialize_audit_entry(entry) for entry in entries]

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "items": items,
                "cursor": next_cursor,
                "has_more": has_more,
            },
            "meta": {
                "request_id": request_id,
                "pagination": {
                    "cursor": next_cursor,
                    "has_more": has_more,
                },
            },
        },
    )


# ---------------------------------------------------------------------------
# GET /api/v1/audit/{audit_id} — Get single audit entry
# ---------------------------------------------------------------------------
@router.get(
    "/{audit_id}",
    response_model=None,
    summary="Get a single audit log entry",
    description="Returns a single audit log entry by ID. "
    "Requires Super_Admin or Clinic_Admin role. "
    "RLS ensures tenant isolation.",
)
async def get_audit_log(
    request: Request,
    audit_id: int,
    auth_context: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """
    Retrieve a single audit log entry by its ID.

    Returns 404 if the entry doesn't exist or belongs to a different tenant
    (RLS will filter it out, making it appear as not found).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = auth_context["tenant_id"]

    factory = get_session_factory()
    async with factory() as db:
        # Set tenant context for RLS isolation
        if tenant_id:
            await set_tenant_context(db, str(tenant_id))

        result = await db.execute(
            select(AuditLog).where(AuditLog.id == audit_id)
        )
        entry = result.scalar_one_or_none()

        if entry is None:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": "Audit log entry not found",
                        "details": [],
                        "request_id": request_id,
                    },
                },
            )

        item = _serialize_audit_entry(entry)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": item,
            "meta": {"request_id": request_id},
        },
    )


# ---------------------------------------------------------------------------
# Helper — Serialize AuditLog model to dict
# ---------------------------------------------------------------------------
def _serialize_audit_entry(entry: AuditLog) -> dict:
    """
    Convert an AuditLog SQLAlchemy model to a JSON-serializable dict.

    Handles UUID and datetime serialization. The 'metadata' field is
    mapped from the model's 'request_metadata' attribute (because
    'metadata' is reserved by SQLAlchemy's DeclarativeBase).

    Args:
        entry: AuditLog model instance.

    Returns:
        Dict matching the AuditLogResponse schema.
    """
    return {
        "id": entry.id,
        "tenant_id": str(entry.tenant_id),
        "user_id": str(entry.user_id),
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": str(entry.resource_id) if entry.resource_id else None,
        "changes": entry.changes,
        "metadata": entry.request_metadata,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
