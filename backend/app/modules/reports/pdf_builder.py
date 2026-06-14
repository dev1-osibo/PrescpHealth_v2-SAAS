"""
PrescpHealth Backend — PDF Builder.

Constructs clinical summary PDFs and referral letters.
Uses reportlab when available; falls back to a bytes placeholder if not installed.

PHI safety:
  - Logs only patient_id UUID and structural events.
  - Never logs section content, referral reasons, or clinical values.
  - The generated PDF bytes themselves contain PHI and must be handled
    with Cache-Control: no-store at the HTTP layer.

Architecture:
  PDFBuilder is instantiated per-request with tenant_id and request_id
  for correlation. All build methods are async to allow future I/O
  (e.g., fetching section data from the DB) without blocking the event loop.
"""
import io
import uuid
import structlog
from typing import Any

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional reportlab import — graceful degradation if not installed
# ---------------------------------------------------------------------------
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import letter
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class PDFBuilder:
    """
    Builds clinical PDFs using reportlab (or a stub if unavailable).

    Each method is async so callers can await without blocking,
    and future implementations can pull section data from the DB inline.
    """

    def __init__(self, tenant_id: uuid.UUID, request_id: str) -> None:
        """
        Initialize the builder with request-scoped context.

        Args:
            tenant_id: Current tenant UUID for multi-tenancy scoping.
            request_id: Correlation ID propagated from the HTTP request.
        """
        self.tenant_id = tenant_id
        self.request_id = request_id

    async def build_clinical_pdf(
        self,
        patient_id: uuid.UUID,
        sections: list[str],
    ) -> bytes:
        """
        Build a clinical summary PDF for the given patient.

        PHI safety: logs only patient_id UUID — never section content or values.

        Args:
            patient_id: UUID of the patient being reported on.
            sections: Ordered list of section keys to render
                      (e.g. ["demographics", "medications", "risk_scores", "alerts"]).

        Returns:
            PDF as a bytes object. Returns a placeholder if reportlab is unavailable.
        """
        logger.info(
            "pdf_generation_started",
            patient_id=str(patient_id),
            section_count=len(sections),
            request_id=self.request_id,
            tenant_id=str(self.tenant_id),
        )

        if not REPORTLAB_AVAILABLE:
            logger.warning(
                "pdf_generation_reportlab_unavailable",
                patient_id=str(patient_id),
                request_id=self.request_id,
            )
            return b"PDF_PLACEHOLDER: reportlab not installed"

        pdf_bytes = self._build_clinical_with_reportlab(patient_id, sections)

        logger.info(
            "pdf_generation_completed",
            patient_id=str(patient_id),
            bytes_size=len(pdf_bytes),
            request_id=self.request_id,
        )
        return pdf_bytes

    def _build_clinical_with_reportlab(
        self,
        patient_id: uuid.UUID,
        sections: list[str],
    ) -> bytes:
        """
        Internal: construct the PDF document using reportlab Platypus.

        Args:
            patient_id: Patient UUID (used in document header only as UUID).
            sections: Section keys to render.

        Returns:
            Rendered PDF bytes.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story: list[Any] = []

        story.append(Paragraph("Clinical Summary Report", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Patient ID: {patient_id}", styles["Normal"]))
        story.append(Spacer(1, 24))

        for section in sections:
            story.append(Paragraph(section.replace("_", " ").title(), styles["Heading2"]))
            story.append(Spacer(1, 6))
            story.append(
                Paragraph(
                    f"[Section: {section} - data loaded on render]",
                    styles["Normal"],
                )
            )
            if section == "risk_scores":
                story.append(
                    Paragraph(
                        "[Chart: Risk Score Trend - SVG embedded on render]",
                        styles["Normal"],
                    )
                )
            story.append(Spacer(1, 18))

        doc.build(story)
        return buffer.getvalue()

    async def build_referral_pdf(
        self,
        patient_id: uuid.UUID,
        referring_physician: str,
        referral_reason: str,
    ) -> bytes:
        """
        Build a referral letter PDF.

        PHI safety: logs only patient_id UUID.
        referral_reason is included in the PDF body (clinical necessity).

        Args:
            patient_id: UUID of the patient being referred.
            referring_physician: Name/ID of the referring clinician.
            referral_reason: Clinical reason text (included in PDF).

        Returns:
            PDF as bytes. Returns a placeholder if reportlab is unavailable.
        """
        logger.info(
            "referral_pdf_generation_started",
            patient_id=str(patient_id),
            request_id=self.request_id,
            tenant_id=str(self.tenant_id),
        )

        if not REPORTLAB_AVAILABLE:
            logger.warning(
                "referral_pdf_reportlab_unavailable",
                patient_id=str(patient_id),
                request_id=self.request_id,
            )
            return b"PDF_PLACEHOLDER: reportlab not installed"

        pdf_bytes = self._build_referral_with_reportlab(
            patient_id, referring_physician, referral_reason
        )

        logger.info(
            "referral_pdf_generated",
            patient_id=str(patient_id),
            bytes_size=len(pdf_bytes),
            request_id=self.request_id,
        )
        return pdf_bytes

    def _build_referral_with_reportlab(
        self,
        patient_id: uuid.UUID,
        referring_physician: str,
        referral_reason: str,
    ) -> bytes:
        """
        Internal: construct the referral letter using reportlab.

        Args:
            patient_id: Patient UUID.
            referring_physician: Referring clinician identifier.
            referral_reason: Clinical reason text to embed in the letter.

        Returns:
            Rendered PDF bytes.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story: list[Any] = []

        story.append(Paragraph("Referral Letter", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Patient ID: {patient_id}", styles["Normal"]))
        story.append(Paragraph(f"Referring Physician: {referring_physician}", styles["Normal"]))
        story.append(Spacer(1, 24))
        story.append(Paragraph("Reason for Referral", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(referral_reason, styles["Normal"]))
        story.append(Spacer(1, 18))
        story.append(
            Paragraph("[Additional clinical context loaded on render]", styles["Normal"])
        )

        doc.build(story)
        return buffer.getvalue()
