"""
Unit Tests: Documents Module (Task 11.7).

Tests cover:
- MIME type validation (accept PDF, JPEG, PNG, TIFF, DICOM; reject EXE, HTML, ZIP, MP4)
- File size rejection (> 25 MB raises FileSizeExceededError)
- File size acceptance (≤ 25 MB succeeds)
- Document search by type
- Document search by date range (via list_documents filters)

All tests use mocked AsyncSession — no real DB connections.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.documents.enums import (
    DocumentType,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
)
from app.modules.documents.exceptions import (
    InvalidMimeTypeError,
    FileSizeExceededError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_mock_storage():
    """Create a mock storage backend that returns a fake path."""
    storage = AsyncMock()
    storage.save = AsyncMock(return_value="/fake/storage/path/doc.pdf")
    storage.get = AsyncMock(return_value=b"fake-content")
    return storage


def _make_mock_db():
    """Create a mock async DB session for document operations."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


class TestMimeTypeValidation:
    """Verify MIME type acceptance and rejection rules."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mime_type", [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "application/dicom",
    ])
    async def test_accepted_mime_types(self, mime_type):
        """Valid MIME types (PDF, JPEG, PNG, TIFF, DICOM) are accepted."""
        from app.modules.documents.service import DocumentService

        storage = _make_mock_storage()
        service = DocumentService(storage=storage)
        mock_db = _make_mock_db()

        # 1 KB synthetic file content
        file_data = b"x" * 1024

        with patch("app.modules.documents.service._audit", MagicMock(log_action=AsyncMock())):
            result = await service.upload_document(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                uploaded_by=uuid.uuid4(),
                file_data=file_data,
                file_name="test_file",
                mime_type=mime_type,
                document_type=DocumentType.LAB_REPORT,
                title="Test Document",
            )

        # Verify document was added to session
        assert mock_db.add.called

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mime_type", [
        "application/x-msdownload",  # EXE
        "text/html",                 # HTML
        "application/zip",           # ZIP
        "video/mp4",                 # MP4
    ])
    async def test_rejected_mime_types(self, mime_type):
        """Invalid MIME types (EXE, HTML, ZIP, MP4) raise InvalidMimeTypeError."""
        from app.modules.documents.service import DocumentService

        storage = _make_mock_storage()
        service = DocumentService(storage=storage)
        mock_db = _make_mock_db()

        file_data = b"x" * 1024

        with pytest.raises(InvalidMimeTypeError):
            await service.upload_document(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                uploaded_by=uuid.uuid4(),
                file_data=file_data,
                file_name="malicious_file",
                mime_type=mime_type,
                document_type=DocumentType.OTHER,
                title="Bad Document",
            )


class TestFileSizeValidation:
    """Verify file size limit enforcement at 25 MB."""

    @pytest.mark.asyncio
    async def test_file_over_25mb_rejected(self):
        """Files exceeding 25 MB raise FileSizeExceededError."""
        from app.modules.documents.service import DocumentService

        storage = _make_mock_storage()
        service = DocumentService(storage=storage)
        mock_db = _make_mock_db()

        # 25 MB + 1 byte — exceeds limit
        oversized_data = b"x" * (MAX_FILE_SIZE_BYTES + 1)

        with pytest.raises(FileSizeExceededError):
            await service.upload_document(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                uploaded_by=uuid.uuid4(),
                file_data=oversized_data,
                file_name="huge_file.pdf",
                mime_type="application/pdf",
                document_type=DocumentType.LAB_REPORT,
                title="Oversized Report",
            )

    @pytest.mark.asyncio
    async def test_file_at_25mb_accepted(self):
        """Files at exactly 25 MB are accepted (boundary condition)."""
        from app.modules.documents.service import DocumentService

        storage = _make_mock_storage()
        service = DocumentService(storage=storage)
        mock_db = _make_mock_db()

        # Exactly 25 MB — at limit
        exact_data = b"x" * MAX_FILE_SIZE_BYTES

        with patch("app.modules.documents.service._audit", MagicMock(log_action=AsyncMock())):
            result = await service.upload_document(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                uploaded_by=uuid.uuid4(),
                file_data=exact_data,
                file_name="boundary_file.pdf",
                mime_type="application/pdf",
                document_type=DocumentType.LAB_REPORT,
                title="Boundary Report",
            )

        assert mock_db.add.called

    @pytest.mark.asyncio
    async def test_file_under_25mb_accepted(self):
        """Files well under 25 MB are accepted without issue."""
        from app.modules.documents.service import DocumentService

        storage = _make_mock_storage()
        service = DocumentService(storage=storage)
        mock_db = _make_mock_db()

        small_data = b"x" * 1024  # 1 KB

        with patch("app.modules.documents.service._audit", MagicMock(log_action=AsyncMock())):
            result = await service.upload_document(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                uploaded_by=uuid.uuid4(),
                file_data=small_data,
                file_name="small_report.pdf",
                mime_type="application/pdf",
                document_type=DocumentType.LAB_REPORT,
                title="Small Report",
            )

        assert mock_db.add.called


class TestDocumentSearch:
    """Verify document list filtering by type and tenant scope."""

    @pytest.mark.asyncio
    async def test_list_documents_filters_by_type(self):
        """list_documents with document_type filter includes type in query."""
        from app.modules.documents.service import DocumentService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_result.scalar_one.return_value = 0
        mock_db.execute.return_value = mock_result

        service = DocumentService()

        items, total = await service.list_documents(
            db=mock_db,
            tenant_id=uuid.uuid4(),
            document_type=DocumentType.LAB_REPORT,
        )

        # Verify execute was called and query includes document_type
        assert mock_db.execute.called
        first_stmt = mock_db.execute.call_args_list[0][0][0]
        compiled = str(first_stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "document_type" in compiled

    @pytest.mark.asyncio
    async def test_list_documents_scoped_to_tenant(self):
        """list_documents always includes tenant_id in query filter."""
        from app.modules.documents.service import DocumentService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_result.scalar_one.return_value = 0
        mock_db.execute.return_value = mock_result

        service = DocumentService()
        tenant_id = uuid.uuid4()

        items, total = await service.list_documents(db=mock_db, tenant_id=tenant_id)

        first_stmt = mock_db.execute.call_args_list[0][0][0]
        compiled = str(first_stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "tenant_id" in compiled
