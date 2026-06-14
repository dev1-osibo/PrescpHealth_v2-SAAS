"""
Appointments Staging Module
============================
Handles appointment booking, scheduling, waitlist management,
and recurring appointment generation for PrescpHealth EMR.

Exports the FastAPI router for inclusion in the main application.
"""

from .router import router  # noqa: F401

__all__ = ["router"]
