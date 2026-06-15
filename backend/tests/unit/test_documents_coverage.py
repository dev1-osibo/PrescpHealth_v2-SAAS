"""
Coverage tests: Documents Module — uncovered service paths, storage backends,
schemas, enums, and exceptions.

Targets paths not exercised by test_documents_unit.py:
  - DocumentService.get_document (happy path + not-found)
  - DocumentService.download_document
  - LocalStorageBackend.save / get / delete
  - S3StorageBackend raises NotImplementedError
  - get_storage_backend factory
  - Pydantic schemas
  - Custom exceptions
  - Enum value completeness
"""

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.documents.enums import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
    DocumentType,
)
from app.modules.documents.exceptions import (
    DocumentNotFoundError,
    FileSizeExceededError,
    InvalidMimeTypeError,
    StorageError,
)
from app.modules.documents.schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadMeta,
)
from app.modules.documents.storage import (
    LocalStorageBackend,
    S3StorageBackend,
    get_storage_backend,
)

# ---------------------------------------------------------------------------
# Shared mock audit
# ---------------------------------------------------------------------------
_mock_audit = MagicMock()
_mock_audit.log_action = AsyncMock()


def _make_document(**kw):
    """Return a mock Document ORM object with sensible defaults."""
    doc = MagicMock()
    doc.id = kw.get("id", uuid.uuid4())
    doc.tenant_id = kw.get("tenant_id", uuid.uuid4())
    doc.patient_id = kw.get("patient_id", uuid.uuid4())
    doc.encounter_id = kw.get("encounter_id", None)
    doc.document_type = kw.get("document_type", DocumentType.LAB_REPORT)
    doc.title = kw.get("title", "Test Lab Report")
    doc.description = kw.get("description", None)
    doc.file_name = kw.get("file_name", "report.pdf")
    doc.mime_type = kw.get("mime_type", "application/pdf")
    doc.file_size_bytes = kw.get("file_size_bytes", 1024)
    doc.storage_path = kw.get("storage_path", "tenant/doc/report.pdf")
    doc.storage_backend = kw.get("storage_backend", "local")
    doc.is_encrypted = kw.get("is_encrypted", True)
    doc.uploaded_by = kw.get("uploaded_by", uuid.uuid4())
    doc.uploaded_at = kw.get("uploaded_at", datetime.now(timezone.utc))
    doc.doc_metadata = kw.get("doc_metadata", None)
    doc.created_at = kw.get("created_at", datetime.now(timezone.utc))
    return doc


def _mock_db_returning(doc):
    """Return mock AsyncSession that returns given doc from execute."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = doc
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# DocumentService.get_document
# ===========================================================================
class TestGetDocument:
    """Verify document metadata retrieval."""

    @pytest.mark.asyncio
    async def test_get_document_returns_doc(self):
        """get_document returns the document ORM object when found."""
        from app.modules.documents.service import DocumentService

        doc = _make_document()
        db = _mock_db_returning(doc)
        svc = DocumentService()

        result = await svc.get_document(db=db, document_id=doc.id)

        assert result is doc

    @pytest.mark.asyncio
    async def test_get_document_not_found_raises(self):
        """get_document raises DocumentNotFoundError when UUID not in DB."""
        from app.modules.documents.service import DocumentService

        db = _mock_db_returning(None)
        svc = DocumentService()

        with pytest.raises(DocumentNotFoundError):
            await svc.get_document(db=db, document_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_document_not_found_stores_id(self):
        """DocumentNotFoundError stores the document_id that was queried."""
        from app.modules.documents.service import DocumentService

        db = _mock_db_returning(None)
        svc = DocumentService()
        target_id = uuid.uuid4()

        with pytest.raises(DocumentNotFoundError) as exc:
            await svc.get_document(db=db, document_id=target_id)

        assert str(target_id) in str(exc.value)


# ===========================================================================
# DocumentService.download_document
# ===========================================================================
class TestDownloadDocument:
    """Verify download_document returns metadata and bytes together."""

    @pytest.mark.asyncio
    async def test_download_returns_doc_and_bytes(self):
        """download_document returns (Document, bytes) tuple."""
        from app.modules.documents.service import DocumentService

        doc = _make_document(storage_path="tenant/doc/report.pdf")
        db = _mock_db_returning(doc)

        storage = AsyncMock()
        storage.save = AsyncMock(return_value="/fake/path")
        storage.get = AsyncMock(return_value=b"PDF content bytes")

        svc = DocumentService(storage=storage)

        with patch("app.modules.documents.service._audit", _mock_audit):
            result_doc, result_bytes = await svc.download_document(
                db=db, document_id=doc.id
            )

        assert result_doc is doc
        assert result_bytes == b"PDF content bytes"
        storage.get.assert_called_once_with(doc.storage_path)

    @pytest.mark.asyncio
    async def test_download_not_found_raises(self):
        """download_document raises DocumentNotFoundError when doc not in DB."""
        from app.modules.documents.service import DocumentService

        db = _mock_db_returning(None)
        storage = AsyncMock()
        svc = DocumentService(storage=storage)

        with pytest.raises(DocumentNotFoundError):
            await svc.download_document(db=db, document_id=uuid.uuid4())


# ===========================================================================
# LocalStorageBackend
# ===========================================================================
class TestLocalStorageBackend:
    """Verify local filesystem storage operations using a temp directory."""

    @pytest.mark.asyncio
    async def test_save_creates_file(self):
        """save() writes bytes to disk and returns the resolved path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(base_dir=Path(tmpdir))
            path = "synth-tenant/synth-doc/report.pdf"
            data = b"synthetic PDF content"

            resolved = await backend.save(path, data)

            full = Path(tmpdir) / path
            assert full.exists()
            assert full.read_bytes() == data
            assert resolved == str(full)

    @pytest.mark.asyncio
    async def test_get_returns_bytes(self):
        """get() returns exact bytes previously written by save()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(base_dir=Path(tmpdir))
            path = "synth-tenant/synth-doc/lab.pdf"
            data = b"lab report bytes"

            await backend.save(path, data)
            retrieved = await backend.get(path)

            assert retrieved == data

    @pytest.mark.asyncio
    async def test_delete_removes_file(self):
        """delete() removes the file from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(base_dir=Path(tmpdir))
            path = "synth-tenant/synth-doc/consent.pdf"
            data = b"consent form content"

            await backend.save(path, data)
            full = Path(tmpdir) / path
            assert full.exists()

            await backend.delete(path)

            assert not full.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self):
        """delete() on a non-existent path does not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(base_dir=Path(tmpdir))
            # Should not raise
            await backend.delete("synth-tenant/missing/file.pdf")

    @pytest.mark.asyncio
    async def test_save_creates_parent_dirs(self):
        """save() creates nested parent directories automatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(base_dir=Path(tmpdir))
            deep_path = "level1/level2/level3/document.pdf"

            await backend.save(deep_path, b"nested content")

            assert (Path(tmpdir) / deep_path).exists()


# ===========================================================================
# S3StorageBackend
# ===========================================================================
class TestS3StorageBackend:
    """Verify S3 backend raises NotImplementedError on all operations."""

    @pytest.mark.asyncio
    async def test_save_raises_not_implemented(self):
        """S3StorageBackend.save raises NotImplementedError."""
        backend = S3StorageBackend()
        with pytest.raises(NotImplementedError):
            await backend.save("tenant/doc.pdf", b"data")

    @pytest.mark.asyncio
    async def test_get_raises_not_implemented(self):
        """S3StorageBackend.get raises NotImplementedError."""
        backend = S3StorageBackend()
        with pytest.raises(NotImplementedError):
            await backend.get("tenant/doc.pdf")

    @pytest.mark.asyncio
    async def test_delete_raises_not_implemented(self):
        """S3StorageBackend.delete raises NotImplementedError."""
        backend = S3StorageBackend()
        with pytest.raises(NotImplementedError):
            await backend.delete("tenant/doc.pdf")


# ===========================================================================
# get_storage_backend factory
# ===========================================================================
class TestGetStorageBackendFactory:
    """Verify factory returns correct backend type."""

    def test_local_returns_local_backend(self):
        """get_storage_backend('local') returns LocalStorageBackend."""
        backend = get_storage_backend("local")
        assert isinstance(backend, LocalStorageBackend)

    def test_default_returns_local_backend(self):
        """get_storage_backend() defaults to LocalStorageBackend."""
        backend = get_storage_backend()
        assert isinstance(backend, LocalStorageBackend)

    def test_s3_returns_s3_backend(self):
        """get_storage_backend('s3') returns S3StorageBackend."""
        backend = get_storage_backend("s3")
        assert isinstance(backend, S3StorageBackend)


# ===========================================================================
# Pydantic Schemas
# ===========================================================================
class TestDocumentSchemas:
    """Verify schema validation and serialization."""

    def test_document_upload_meta_valid(self):
        """DocumentUploadMeta accepts a valid upload metadata payload."""
        obj = DocumentUploadMeta(
            patient_id=uuid.uuid4(),
            document_type=DocumentType.LAB_REPORT,
            title="Synth Lab Result",
        )
        assert obj.document_type == DocumentType.LAB_REPORT
        assert obj.encounter_id is None

    def test_document_upload_meta_title_max_length(self):
        """DocumentUploadMeta rejects title longer than 255 chars."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            DocumentUploadMeta(
                patient_id=uuid.uuid4(),
                document_type=DocumentType.CLINICAL_NOTE,
                title="x" * 256,
            )

    def test_document_list_response_valid(self):
        """DocumentListResponse holds list of DocumentResponse items."""
        obj = DocumentListResponse(items=[], total=0, limit=25, offset=0)
        assert obj.total == 0
        assert obj.items == []

    def test_document_type_all_values(self):
        """DocumentType enum covers all expected clinical document types."""
        expected = {
            "lab_report", "radiology", "discharge_summary",
            "consent_form", "referral_letter", "clinical_note",
            "imaging", "other",
        }
        assert {e.value for e in DocumentType} == expected


# ===========================================================================
# Allowed MIME types and size constants
# ===========================================================================
class TestDocumentConstants:
    """Verify MIME type set and size constant are correct."""

    def test_allowed_mime_types_contains_pdf(self):
        """ALLOWED_MIME_TYPES includes application/pdf."""
        assert "application/pdf" in ALLOWED_MIME_TYPES

    def test_allowed_mime_types_contains_dicom(self):
        """ALLOWED_MIME_TYPES includes application/dicom."""
        assert "application/dicom" in ALLOWED_MIME_TYPES

    def test_max_file_size_is_25mb(self):
        """MAX_FILE_SIZE_BYTES equals exactly 25 MiB."""
        assert MAX_FILE_SIZE_BYTES == 25 * 1024 * 1024


# ===========================================================================
# Custom Exceptions
# ===========================================================================
class TestDocumentExceptions:
    """Verify exception constructors and PHI-safe messages."""

    def test_document_not_found_stores_id(self):
        """DocumentNotFoundError stores document_id attribute."""
        doc_id = str(uuid.uuid4())
        err = DocumentNotFoundError(doc_id)
        assert err.document_id == doc_id
        assert doc_id in str(err)
        assert isinstance(err, Exception)

    def test_invalid_mime_type_stores_mime(self):
        """InvalidMimeTypeError stores mime_type attribute."""
        err = InvalidMimeTypeError("application/x-msdownload")
        assert err.mime_type == "application/x-msdownload"
        assert "application/x-msdownload" in str(err)
        assert isinstance(err, Exception)

    def test_file_size_exceeded_stores_sizes(self):
        """FileSizeExceededError stores size_bytes and max_bytes."""
        err = FileSizeExceededError(30_000_000, 25 * 1024 * 1024)
        assert err.size_bytes == 30_000_000
        assert err.max_bytes == 25 * 1024 * 1024
        assert isinstance(err, Exception)

    def test_storage_error_stores_message(self):
        """StorageError stores the safe error message."""
        err = StorageError("Disk full on storage backend")
        assert "Disk full" in str(err)
        assert isinstance(err, Exception)
