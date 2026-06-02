"""
PrescpHealth Backend — Admin Tenant Router.

Exposes CRUD endpoints for tenant management.
All endpoints require Role.SUPER_ADMIN.
Responses set Cache-Control: no-store because tenant configs are sensitive.
"""
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditService
from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.modules.admin_staging.exceptions import TenantNotFoundError
from app.modules.admin_staging.schemas import (
    CreateTenantRequest,
    TenantListResponse,
    TenantResponse,
    UpdateTenantRequest,
)
from app.modules.admin_staging.service_tenant import TenantManagementService
from app.modules.auth.rbac import Role, require_role

logger = structlog.get_logger(__name__)
tenant_router = APIRouter(tags=["admin_tenants"])

_NO_STORE = "no-store"


def _meta(request_id: str) -> dict:
    """Build standard response meta block with request_id and UTC timestamp."""
    return {"request_id": request_id, "timestamp": datetime.now(timezone.utc).isoformat()}


def _build_tenant_service(
    db: AsyncSession,
    current_user: dict,
    request_id: str,
) -> TenantManagementService:
    """Instantiate TenantManagementService with injected dependencies."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    audit_service = AuditService(db=db, tenant_id=tenant_id)
    return TenantManagementService(
        db=db,
        audit_service=audit_service,
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


@tenant_router.post(
    "/api/v1/admin/tenants",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant",
)
async def create_tenant(
    body: CreateTenantRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Create a new tenant organisation.
    Requires Super_Admin role. Audit-logged.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_tenant_service(db, current_user, request_id)
    try:
        tenant = await svc.create_tenant(body)
        return {"success": True, "data": TenantResponse(**tenant).model_dump(mode="json"), "meta": _meta(request_id)}
    except Exception as exc:
        logger.error("create_tenant_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create tenant")


@tenant_router.get(
    "/api/v1/admin/tenants",
    response_model=TenantListResponse,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    summary="List all tenants",
)
async def list_tenants(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> TenantListResponse:
    """
    Return a paginated list of all tenants.
    Requires Super_Admin role. Audit-logged.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_tenant_service(db, current_user, request_id)
    tenants = await svc.list_tenants(limit=limit, offset=offset)
    tenant_responses = [TenantResponse(**t) for t in tenants]
    return TenantListResponse(
        data=tenant_responses,
        meta={**_meta(request_id), "count": len(tenant_responses), "limit": limit, "offset": offset},
    )


@tenant_router.get(
    "/api/v1/admin/tenants/{tenant_id}",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    summary="Get a single tenant",
)
async def get_tenant(
    tenant_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Fetch a single tenant by UUID.
    Requires Super_Admin role.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_tenant_service(db, current_user, request_id)
    try:
        tenant = await svc.get_tenant(tenant_id)
        return {"success": True, "data": TenantResponse(**tenant).model_dump(mode="json"), "meta": _meta(request_id)}
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except Exception as exc:
        logger.error("get_tenant_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve tenant")


@tenant_router.put(
    "/api/v1/admin/tenants/{tenant_id}",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    summary="Update a tenant",
)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: UpdateTenantRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Update tenant settings or active state.
    Requires Super_Admin role. Audit-logged with changed field names only.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_tenant_service(db, current_user, request_id)
    try:
        tenant = await svc.update_tenant(tenant_id, body)
        return {"success": True, "data": TenantResponse(**tenant).model_dump(mode="json"), "meta": _meta(request_id)}
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except Exception as exc:
        logger.error("update_tenant_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update tenant")
