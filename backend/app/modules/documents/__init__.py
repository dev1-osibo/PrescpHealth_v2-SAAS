"""
Documents Staging Module
=========================
Handles secure upload, storage, retrieval, and metadata management
of clinical documents (PDFs, images, DICOM) for PrescpHealth EMR.

Exports the FastAPI router for inclusion in the main application.
"""

from .router import router  # noqa: F401

__all__ = ["router"]
