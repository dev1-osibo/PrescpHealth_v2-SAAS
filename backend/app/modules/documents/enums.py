"""
Documents Module — Enumerations
=================================
Clinical document type classifications accepted by the system.
"""

from enum import Enum


class DocumentType(str, Enum):
    """Classification of clinical document types."""

    LAB_REPORT = "lab_report"
    RADIOLOGY = "radiology"
    DISCHARGE_SUMMARY = "discharge_summary"
    CONSENT_FORM = "consent_form"
    REFERRAL_LETTER = "referral_letter"
    CLINICAL_NOTE = "clinical_note"
    IMAGING = "imaging"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Allowed MIME types (enforced at service layer before storage write)
# ---------------------------------------------------------------------------
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "application/dicom",
    ]
)

# ---------------------------------------------------------------------------
# Maximum permitted file size in bytes (25 MiB)
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_BYTES: int = 25 * 1024 * 1024
