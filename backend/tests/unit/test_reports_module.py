"""
Tests for app.modules.reports — exceptions, schemas, CSV exporter,
PDF builder, and report service.

All tests use synthetic data only. No real PHI. DB is mocked.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

from app.modules.reports.exceptions import (
    ReportError,
    ReportNotFoundError,
    ReportGenerationError,
    ExportError,
)


def test_report_error_base():
    """ReportError stores message and is an Exception."""
    err = ReportError("synthetic report error")
    assert err.message == "synthetic report error"
    assert isinstance(err, Exception)


def test_report_not_found_error():
    """ReportNotFoundError is a ReportError subclass."""
    err = ReportNotFoundError("task not found")
    assert isinstance(err, ReportError)
    assert "task not found" in str(err)


def test_report_generation_error():
    """ReportGenerationError is a ReportError subclass."""
    err = ReportGenerationError("pdf generation failed")
    assert isinstance(err, ReportError)
    assert "pdf generation failed" in str(err)


def test_export_error():
    """ExportError is a ReportError subclass."""
    err = ExportError("csv export failed")
    assert isinstance(err, ReportError)
    assert "csv export failed" in str(err)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

from app.modules.reports.schemas import (
    ReportRequest,
    ReferralRequest,
    ReportTaskResponse,
    CSVExportMeta,
)


def test_report_request_default_sections():
    """ReportRequest uses default section list when none provided."""
    patient_id = uuid.uuid4()
    req = ReportRequest(patient_id=patient_id)
    assert req.patient_id == patient_id
    assert "demographics" in req.include_sections
    assert "medications" in req.include_sections
    assert "risk_scores" in req.include_sections
    assert "alerts" in req.include_sections


def test_report_request_custom_sections():
    """ReportRequest accepts custom sections list."""
    req = ReportRequest(
        patient_id=uuid.uuid4(),
        include_sections=["demographics", "alerts"],
    )
    assert req.include_sections == ["demographics", "alerts"]


def test_report_request_invalid_patient_id():
    """ReportRequest rejects non-UUID patient_id."""
    with pytest.raises(ValidationError):
        ReportRequest(patient_id="not-a-uuid")


def test_referral_request_valid():
    """ReferralRequest accepts valid referral data."""
    req = ReferralRequest(
        patient_id=uuid.uuid4(),
        referring_physician="Dr. Synth",
        referral_reason="Synthetic cardiology referral for QA testing",
    )
    assert req.referring_physician == "Dr. Synth"
    assert "QA testing" in req.referral_reason


def test_referral_request_empty_physician():
    """ReferralRequest rejects empty referring_physician (min_length=1)."""
    with pytest.raises(ValidationError):
        ReferralRequest(
            patient_id=uuid.uuid4(),
            referring_physician="",
            referral_reason="Reason text",
        )


def test_referral_request_reason_too_long():
    """ReferralRequest rejects referral_reason exceeding 1000 characters."""
    with pytest.raises(ValidationError):
        ReferralRequest(
            patient_id=uuid.uuid4(),
            referring_physician="Dr. Synth",
            referral_reason="x" * 1001,
        )


def test_referral_request_missing_reason():
    """ReferralRequest rejects missing referral_reason."""
    with pytest.raises(ValidationError):
        ReferralRequest(
            patient_id=uuid.uuid4(),
            referring_physician="Dr. Synth",
        )


def test_report_task_response_structure():
    """ReportTaskResponse has success=True and data/meta dicts."""
    resp = ReportTaskResponse(
        data={"task_id": str(uuid.uuid4()), "estimated_seconds": 30},
        meta={"request_id": "test-request"},
    )
    assert resp.success is True
    assert "task_id" in resp.data


def test_csv_export_meta_structure():
    """CSVExportMeta has success=True and meta dict."""
    resp = CSVExportMeta(
        meta={"row_count": 100, "exported_at": datetime.now(timezone.utc).isoformat()},
    )
    assert resp.success is True
    assert resp.meta["row_count"] == 100


# ---------------------------------------------------------------------------
# CSV Exporter
# ---------------------------------------------------------------------------

from app.modules.reports.csv_exporter import CSVExporter


@pytest.mark.asyncio
async def test_export_measurements_yields_header():
    """export_measurements yields CSV header as first row."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    # Mock scalars to raise an ImportError-style path so we hit the fallback
    mock_db.scalars = AsyncMock(side_effect=Exception("no measurements table"))

    exporter = CSVExporter(db=mock_db, tenant_id=tenant_id)
    gen = exporter.export_measurements(patient_id=patient_id)

    rows = []
    async for row in gen:
        rows.append(row)

    assert len(rows) >= 1
    assert "date" in rows[0]
    assert "measurement_type" in rows[0]
    assert "value" in rows[0]


@pytest.mark.asyncio
async def test_export_measurements_header_only_on_empty():
    """export_measurements yields only header when no measurement rows exist."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    exporter = CSVExporter(db=mock_db, tenant_id=tenant_id)

    # The measurements model import may fail in test env — that's OK; we test header only
    rows = []
    async for row in exporter.export_measurements(patient_id=patient_id):
        rows.append(row)

    assert rows[0].strip() == "date,measurement_type,value,unit,validated"


@pytest.mark.asyncio
async def test_export_population_yields_header():
    """export_population yields CSV header as first row."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_db.scalars = AsyncMock(side_effect=Exception("no risk_scores table"))

    exporter = CSVExporter(db=mock_db, tenant_id=tenant_id)
    gen = exporter.export_population(tenant_id=tenant_id)

    rows = []
    async for row in gen:
        rows.append(row)

    assert len(rows) >= 1
    assert "patient_id" in rows[0]
    assert "disease" in rows[0]
    assert "score" in rows[0]


@pytest.mark.asyncio
async def test_export_population_header_only_on_empty():
    """export_population yields only header when no risk score rows exist."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    exporter = CSVExporter(db=mock_db, tenant_id=tenant_id)

    rows = []
    async for row in exporter.export_population(tenant_id=tenant_id):
        rows.append(row)

    assert rows[0].strip() == "patient_id,disease,score,stratum,computed_at"


# ---------------------------------------------------------------------------
# PDF Builder
# ---------------------------------------------------------------------------

from app.modules.reports.pdf_builder import PDFBuilder, REPORTLAB_AVAILABLE


@pytest.mark.asyncio
async def test_build_clinical_pdf_returns_bytes():
    """build_clinical_pdf returns bytes (placeholder or real PDF)."""
    builder = PDFBuilder(tenant_id=uuid.uuid4(), request_id="test-req-001")
    result = await builder.build_clinical_pdf(
        patient_id=uuid.uuid4(),
        sections=["demographics", "medications"],
    )
    assert isinstance(result, bytes)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_build_clinical_pdf_placeholder_when_no_reportlab():
    """build_clinical_pdf returns placeholder bytes when reportlab is unavailable."""
    builder = PDFBuilder(tenant_id=uuid.uuid4(), request_id="test-req-002")
    with patch("app.modules.reports.pdf_builder.REPORTLAB_AVAILABLE", False):
        result = await builder.build_clinical_pdf(
            patient_id=uuid.uuid4(),
            sections=["demographics"],
        )
    assert result == b"PDF_PLACEHOLDER: reportlab not installed"


@pytest.mark.asyncio
async def test_build_referral_pdf_returns_bytes():
    """build_referral_pdf returns bytes (placeholder or real PDF)."""
    builder = PDFBuilder(tenant_id=uuid.uuid4(), request_id="test-req-003")
    result = await builder.build_referral_pdf(
        patient_id=uuid.uuid4(),
        referring_physician="Dr. Synth",
        referral_reason="Synthetic cardiology referral",
    )
    assert isinstance(result, bytes)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_build_referral_pdf_placeholder_when_no_reportlab():
    """build_referral_pdf returns placeholder bytes when reportlab is unavailable."""
    builder = PDFBuilder(tenant_id=uuid.uuid4(), request_id="test-req-004")
    with patch("app.modules.reports.pdf_builder.REPORTLAB_AVAILABLE", False):
        result = await builder.build_referral_pdf(
            patient_id=uuid.uuid4(),
            referring_physician="Dr. Synth",
            referral_reason="Synthetic referral reason",
        )
    assert result == b"PDF_PLACEHOLDER: reportlab not installed"


@pytest.mark.asyncio
async def test_build_clinical_pdf_multiple_sections():
    """build_clinical_pdf processes all requested sections."""
    builder = PDFBuilder(tenant_id=uuid.uuid4(), request_id="test-req-005")
    result = await builder.build_clinical_pdf(
        patient_id=uuid.uuid4(),
        sections=["demographics", "medications", "risk_scores", "alerts"],
    )
    assert isinstance(result, bytes)


def test_pdf_builder_attributes():
    """PDFBuilder stores tenant_id and request_id on construction."""
    tenant_id = uuid.uuid4()
    builder = PDFBuilder(tenant_id=tenant_id, request_id="req-abc")
    assert builder.tenant_id == tenant_id
    assert builder.request_id == "req-abc"


# ---------------------------------------------------------------------------
# Report Service
# ---------------------------------------------------------------------------

from app.modules.reports.service import ReportService


def _make_report_service(mock_db=None, tenant_id=None, user_id=None):
    """Helper: build a ReportService with mock dependencies."""
    return ReportService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-report-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_request_clinical_report_returns_task_id():
    """request_clinical_report returns a task_id string UUID."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    expected_task_id = str(uuid.uuid4())

    with patch("app.modules.reports.service.BackgroundTaskTracker") as mock_tracker_cls:
        mock_tracker = AsyncMock()
        mock_tracker.create_task = AsyncMock(return_value=expected_task_id)
        mock_tracker_cls.return_value = mock_tracker

        with patch("app.modules.reports.tasks.generate_clinical_pdf_task") as mock_task:
            mock_task.delay = MagicMock()

            svc = _make_report_service(mock_db=mock_db, tenant_id=tenant_id)
            result = await svc.request_clinical_report(
                patient_id=patient_id,
                sections=["demographics", "medications"],
            )

        assert result == expected_task_id
        mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_request_referral_report_returns_task_id():
    """request_referral_report returns a task_id string UUID."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    expected_task_id = str(uuid.uuid4())

    with patch("app.modules.reports.service.BackgroundTaskTracker") as mock_tracker_cls:
        mock_tracker = AsyncMock()
        mock_tracker.create_task = AsyncMock(return_value=expected_task_id)
        mock_tracker_cls.return_value = mock_tracker

        with patch("app.modules.reports.tasks.generate_referral_pdf_task") as mock_task:
            mock_task.delay = MagicMock()

            svc = _make_report_service(mock_db=mock_db, tenant_id=tenant_id)
            result = await svc.request_referral_report(
                patient_id=patient_id,
                referring_physician="Dr. Synth",
                referral_reason="Synthetic referral for cardiology",
            )

        assert result == expected_task_id
        mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_stream_measurements_csv_returns_generator():
    """stream_measurements_csv returns an async generator."""
    import inspect

    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_db.scalars = AsyncMock(side_effect=Exception("no table"))

    svc = _make_report_service(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.stream_measurements_csv(patient_id=patient_id)

    assert inspect.isasyncgen(result)


@pytest.mark.asyncio
async def test_stream_population_csv_returns_generator():
    """stream_population_csv returns an async generator."""
    import inspect

    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_db.scalars = AsyncMock(side_effect=Exception("no table"))

    svc = _make_report_service(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.stream_population_csv()

    assert inspect.isasyncgen(result)


@pytest.mark.asyncio
async def test_stream_measurements_csv_audit_logged():
    """stream_measurements_csv logs an audit event for export action."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_db.scalars = AsyncMock(side_effect=Exception("no table"))

    svc = ReportService(
        db=mock_db,
        audit_service=mock_audit,
        request_id="test",
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
    )
    await svc.stream_measurements_csv(patient_id=patient_id)

    mock_audit.log_audit.assert_called_once()
    call_kwargs = mock_audit.log_audit.call_args.kwargs
    assert call_kwargs["action"] == "measurements_exported"


@pytest.mark.asyncio
async def test_stream_population_csv_audit_logged():
    """stream_population_csv logs an audit event for population export."""
    mock_db = AsyncMock()
    mock_audit = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_db.scalars = AsyncMock(side_effect=Exception("no table"))

    svc = ReportService(
        db=mock_db,
        audit_service=mock_audit,
        request_id="test",
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
    )
    await svc.stream_population_csv()

    mock_audit.log_audit.assert_called_once()
    call_kwargs = mock_audit.log_audit.call_args.kwargs
    assert call_kwargs["action"] == "population_exported"
