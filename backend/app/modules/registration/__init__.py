"""
Registration Staging Module
=============================
Handles patient intake registration, consent capture, and identity
verification workflows for PrescpHealth EMR.

Exports the FastAPI router for inclusion in the main application.
"""

from .router import router  # noqa: F401

__all__ = ["router"]
