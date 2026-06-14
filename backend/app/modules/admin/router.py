"""
PrescpHealth Backend — Admin Main Router.

Exposes model lifecycle endpoints (Super_Admin) and tenant-settings
endpoints (Clinic_Admin own-tenant). All responses set
Cache-Control: no-store because model artefact paths and tenant configs
are sensitive operational metadata.
"""
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.modules.admin.exceptions import ModelDeploymentError, RollbackError
from app.modules.admin.schemas import (
    DeployModelRequest,
    ModelVersionResponse,
    RollbackRequest,
    TenantSettingsRequest,
    TenantSettingsResponse,
)
from app.modules.admin.service import AdminService
from app.modules.auth.rbac import Role, require_role

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

_NO_STORE = "no-store"


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _meta(request_id: str) -> dict:
    """Build standard response meta block."""
    return {"request_id": request_id, "timestamp": datetime.now(timezone.utc).isoformat()}


def _build_admin_service(
    db: AsyncSession,
    current_user: dict,
    request_id: str,
) -> AdminService:
    """Construct AdminService with all injected dependencies."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    audit_service = AuditService(db=db, tenant_id=tenant_id)
    return AdminService(
        db=db,
        audit_service=audit_service,
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# Model management endpoints — Super_Admin only
# ---------------------------------------------------------------------------

@router.post(
    "/api/v1/admin/models/deploy",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    status_code=status.HTTP_201_CREATED,
    summary="Deploy a new model version",
)
async def deploy_model(
    body: DeployModelRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Deploy a new model version and deactivate the previous active version for the disease.
    Requires Super_Admin. Audit-logged with disease and version (no PHI).
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_admin_service(db, current_user, request_id)
    try:
        mv = await svc.model_mgmt.deploy_model(body)
        return {
            "success": True,
            "data": ModelVersionResponse(**mv).model_dump(mode="json"),
            "meta": _meta(request_id),
        }
    except ModelDeploymentError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error("deploy_model_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Model deployment failed")


@router.post(
    "/api/v1/admin/models/rollback",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    summary="Roll back to a previous model version",
)
async def rollback_model(
    body: RollbackRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Restore a prior model version as the active one for a disease.
    Requires Super_Admin. Audit-logged.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_admin_service(db, current_user, request_id)
    try:
        mv = await svc.model_mgmt.rollback_model(body)
        return {
            "success": True,
            "data": ModelVersionResponse(**mv).model_dump(mode="json"),
            "meta": _meta(request_id),
        }
    except RollbackError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except Exception as exc:
        logger.error("rollback_model_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Model rollback failed")


@router.get(
    "/api/v1/admin/models/{disease}/metrics",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    summary="Get per-version metrics for a disease model",
)
async def get_model_metrics(
    disease: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Return all recorded versions and their evaluation metrics for a disease.
    Requires Super_Admin. Audit-logged.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_admin_service(db, current_user, request_id)
    metrics = await svc.model_mgmt.get_model_metrics(disease)
    return {"success": True, "data": metrics, "meta": _meta(request_id)}


@router.post(
    "/api/v1/admin/models/{disease}/recompute",
    response_model=dict,
    dependencies=[Depends(require_role(Role.SUPER_ADMIN))],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger historical risk recomputation for a disease",
)
async def trigger_recomputation(
    disease: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Enqueue (stub) historical recomputation of risk scores for all patients
    using the current active model for the given disease.
    Returns a task_id for async polling. Requires Super_Admin.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_admin_service(db, current_user, request_id)
    task_id = await svc.model_mgmt.trigger_recomputation(disease)
    return {
        "success": True,
        "data": {"task_id": task_id, "disease": disease, "status": "queued"},
        "meta": _meta(request_id),
    }


# ---------------------------------------------------------------------------
# Tenant settings endpoints — Clinic_Admin (own tenant only)
# ---------------------------------------------------------------------------

@router.get(
    "/api/v1/admin/settings",
    response_model=dict,
    dependencies=[Depends(require_role(Role.CLINIC_ADMIN))],
    summary="Get current tenant settings",
)
async def get_tenant_settings(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Retrieve the settings block for the caller's own tenant.
    Accessible by Clinic_Admin and above.
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_admin_service(db, current_user, request_id)
    try:
        settings = await svc.get_tenant_settings()
        return {
            "success": True,
            "data": TenantSettingsResponse(**settings).model_dump(mode="json"),
            "meta": _meta(request_id),
        }
    except Exception as exc:
        logger.error("get_settings_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve settings")


@router.put(
    "/api/v1/admin/settings",
    response_model=dict,
    dependencies=[Depends(require_role(Role.CLINIC_ADMIN))],
    summary="Update current tenant settings",
)
async def update_tenant_settings(
    body: TenantSettingsRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> dict:
    """
    Merge provided fields into the caller's own tenant settings.
    Only non-None fields are applied. Accessible by Clinic_Admin and above.
    Audit-logged with changed field names only (no PHI).
    """
    response.headers["Cache-Control"] = _NO_STORE
    svc = _build_admin_service(db, current_user, request_id)
    try:
        settings = await svc.update_tenant_settings(body)
        return {
            "success": True,
            "data": TenantSettingsResponse(**settings).model_dump(mode="json"),
            "meta": _meta(request_id),
        }
    except Exception as exc:
        logger.error("update_settings_error", error_type=type(exc).__name__, request_id=request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update settings")
