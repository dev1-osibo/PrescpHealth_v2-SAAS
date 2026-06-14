"""
PrescpHealth Backend — Population Analytics Module.

Provides population-level risk analytics for clinical dashboards:
- Risk distribution across disease/stratum dimensions
- High/Critical watchlist of patients needing immediate attention
- Risk score trend data over configurable time windows
- Cached metrics with 1-hour TTL to reduce DB load

Public API:
    PopulationService — core business logic
    router            — FastAPI router with RBAC-protected endpoints
"""
from app.modules.population.service import PopulationService
from app.modules.population.router import router

__all__ = ["PopulationService", "router"]
