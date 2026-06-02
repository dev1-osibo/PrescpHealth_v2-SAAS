"""
PrescpHealth Backend — admin_staging module.

Public API surface for the admin module. Import AdminService, router,
or tenant_router from here rather than reaching into sub-modules directly.
"""
from app.modules.admin_staging.service import AdminService
from app.modules.admin_staging.router import router
from app.modules.admin_staging.router_tenant import tenant_router

__all__ = ["AdminService", "router", "tenant_router"]
