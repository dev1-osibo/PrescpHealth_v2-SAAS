"""
PrescpHealth Backend — Integrations API Router.

Endpoints:
    POST   /api/v1/integrations/connectors               Create connector
    GET    /api/v1/integrations/connectors               List connectors
    GET    /api/v1/integrations/connectors/{id}          Connector details
    PUT    /api/v1/integrations/connectors/{id}          Update connector
    POST   /api/v1/integrations/connectors/{id}/sync     Trigger sync
    GET    /api/v1/integrations/connectors/{id}/logs     Sync history

RBAC: All endpoints require Clinic_Admin or Super_Admin.
HIPAA: Cache-Control: no-store on all responses.

Security:
    ConnectorOut never includes credentials field.
    base_url is returned (needed for UI display) but not logged.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory, set_tenant_context
from app.modules.auth.rbac import Role, require_role
from app.modules.integrations.exceptions import IntegrationError
from app.modules.integrations.schemas import (
    ConnectorCreateRequest,
    ConnectorUpdateRequest,
)
from app.modules.integrations.service import IntegrationService
from app.modules.integrations.sync_engine import SyncEngine
from app.modules.integrations.tasks import run_sync_task_logic

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["integrations"])

_svc = IntegrationService()
_sync_engine = SyncEngine()

_HIPAA_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _envelope(data: object, request_id: str) -> dict:
    """Standard response envelope."""
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def _err(message: str, request_id: str, status_code: int = 400) -> JSONResponse:
    """Error response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message, "meta": {"request_id": request_id}},
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/connectors
# ---------------------------------------------------------------------------
@router.post("/api/v1/integrations/connectors", status_code=201, summary="Create connector")
async def create_connector(
    request: Request,
    body: ConnectorCreateRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Create a new integration connector. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            connector = await _svc.create_connector(db, tenant_id, user_id, body)
            await db.commit()
            await db.refresh(connector)
        except IntegrationError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        status_code=201,
        content=_envelope(_serialize_connector(connector), rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/integrations/connectors
# ---------------------------------------------------------------------------
@router.get("/api/v1/integrations/connectors", summary="List connectors")
async def list_connectors(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """List integration connectors for the tenant. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        connectors, total = await _svc.list_connectors(db, tenant_id, limit, offset)

    items = [_serialize_connector(c) for c in connectors]
    return JSONResponse(
        content=_envelope({"items": items, "total": total}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/integrations/connectors/{id}
# ---------------------------------------------------------------------------
@router.get("/api/v1/integrations/connectors/{connector_id}", summary="Connector details")
async def get_connector(
    request: Request,
    connector_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Get connector details. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            connector = await _svc.get_connector(db, connector_id)
        except IntegrationError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        content=_envelope(_serialize_connector(connector), rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/integrations/connectors/{id}
# ---------------------------------------------------------------------------
@router.put("/api/v1/integrations/connectors/{connector_id}", summary="Update connector")
async def update_connector(
    request: Request,
    connector_id: uuid.UUID,
    body: ConnectorUpdateRequest,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """Update a connector configuration. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        try:
            connector = await _svc.update_connector(db, connector_id, tenant_id, user_id, body)
            await db.commit()
            await db.refresh(connector)
        except IntegrationError as exc:
            return _err(exc.message, rid, exc.status_code)

    return JSONResponse(
        content=_envelope(_serialize_connector(connector), rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/connectors/{id}/sync
# ---------------------------------------------------------------------------
@router.post("/api/v1/integrations/connectors/{connector_id}/sync",
             status_code=202, summary="Trigger sync")
async def trigger_sync(
    request: Request,
    connector_id: uuid.UUID,
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """
    Trigger an async sync for a connector. Clinic_Admin+.

    Returns 202 Accepted with a task_id.
    The sync runs asynchronously via Celery (stub: runs in background).
    """
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))
    user_id = uuid.UUID(str(auth["user_id"]))

    task_id = uuid.uuid4()

    # STUB: Run sync task as asyncio background task
    # Production: would call run_sync_task.delay(str(connector_id), ...)
    asyncio.create_task(
        run_sync_task_logic(
            connector_id_str=str(connector_id),
            tenant_id_str=str(tenant_id),
            triggered_by_str=str(user_id),
        )
    )

    logger.info(
        "sync_triggered",
        task_id=str(task_id),
        connector_id=str(connector_id),
        tenant_id=str(tenant_id),
    )

    return JSONResponse(
        status_code=202,
        content=_envelope({
            "task_id": str(task_id),
            "connector_id": str(connector_id),
            "status": "queued",
            "message": "Sync task queued",
        }, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/integrations/connectors/{id}/logs
# ---------------------------------------------------------------------------
@router.get("/api/v1/integrations/connectors/{connector_id}/logs", summary="Sync history")
async def list_sync_logs(
    request: Request,
    connector_id: uuid.UUID,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_role(Role.CLINIC_ADMIN)),
) -> JSONResponse:
    """List sync history for a connector. Clinic_Admin+."""
    rid = getattr(request.state, "request_id", "unknown")
    tenant_id = uuid.UUID(str(auth["tenant_id"]))

    factory = get_session_factory()
    async with factory() as db:
        await set_tenant_context(db, str(tenant_id))
        logs, total = await _svc.list_sync_logs(db, connector_id, limit, offset)

    items = [_serialize_log(lg) for lg in logs]
    return JSONResponse(
        content=_envelope({"items": items, "total": total}, rid),
        headers=_HIPAA_HEADERS,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_connector(c) -> dict:
    """Convert ConnectorConfig to dict — EXCLUDES credentials."""
    return {
        "id": str(c.id),
        "tenant_id": str(c.tenant_id),
        "connector_type": c.connector_type.value if hasattr(c.connector_type, "value") else c.connector_type,
        "name": c.name,
        "base_url": c.base_url,
        "auth_type": c.auth_type.value if hasattr(c.auth_type, "value") else c.auth_type,
        "sync_direction": c.sync_direction.value if hasattr(c.sync_direction, "value") else c.sync_direction,
        "sync_schedule": c.sync_schedule,
        "is_active": c.is_active,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "created_by": str(c.created_by),
        "created_at": c.created_at.isoformat() if getattr(c, "created_at", None) else None,
        # credentials intentionally EXCLUDED
    }


def _serialize_log(lg) -> dict:
    """Convert SyncLog to dict."""
    return {
        "id": str(lg.id),
        "connector_id": str(lg.connector_id),
        "direction": lg.direction.value if hasattr(lg.direction, "value") else lg.direction,
        "status": lg.status.value if hasattr(lg.status, "value") else lg.status,
        "records_processed": lg.records_processed,
        "records_succeeded": lg.records_succeeded,
        "records_failed": lg.records_failed,
        "error_summary": lg.error_summary,
        "started_at": lg.started_at.isoformat(),
        "completed_at": lg.completed_at.isoformat() if lg.completed_at else None,
        "duration_ms": lg.duration_ms,
    }
