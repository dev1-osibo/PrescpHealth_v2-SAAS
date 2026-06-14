"""
Referrals Staging Module
=========================
Manages specialist referrals including status transitions,
clinical summaries, and specialist findings for PrescpHealth EMR.

Exports the FastAPI router for inclusion in the main application.
"""

from .router import router  # noqa: F401

__all__ = ["router"]
