"""
PrescpHealth Backend — Reports Staging Module.

Exposes the two primary public interfaces for this module:
  - ReportService: business logic layer (PDF generation, CSV export)
  - router: FastAPI APIRouter with all report endpoints

Usage in main app:
    from app.modules.reports_staging import router as reports_router
    app.include_router(reports_router)

    from app.modules.reports_staging import ReportService
"""
from app.modules.reports_staging.service import ReportService
from app.modules.reports_staging.router import router

__all__ = ["ReportService", "router"]
