"""
Property Test: Document Upload Validation (Property 11).

Invariant:
    Document upload is accepted iff MIME type is in the allowed set
    AND file size <= 25 MB (26,214,400 bytes). Any violation is rejected
    with the appropriate domain exception.

Why this matters (Clinical Data Integrity & Security):
    Allowing arbitrary file types could introduce malicious content
    into the clinical document store. Unrestricted file sizes could
    exhaust storage or be used for denial-of-service. The validation
    gate must be airtight regardless of input combination.

Tested service: app.modules.documents.service.DocumentService
Method: upload_document(db, ...)

Allowed MIME types: application/pdf, image/jpeg, image/png,
                    image/tiff, application/dicom
Max size: 25 * 1024 * 1024 = 26,214,400 bytes

**Validates: Requirement — Document upload validation**
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.documents.enums import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
    DocumentType,
)
from app.modules.documents.exceptions import (
    InvalidMimeTypeError,
    FileSizeExceededError,
)

# Import models so SQLAlchemy mappers resolve correctly
import app.modules.documents.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate document upload parameters
# ---------------------------------------------------------------------------

# Valid MIME types (should always be accepted if size is within limit)
valid_mime_strategy = st.sampled_from(sorted(ALLOWED_MIME_TYPES))

# Invalid MIME types (should always be rejected regardless of size)
invalid_mime_strategy = st.sampled_from([
    "application/exe",
    "text/html",
    "video/mp4",
    "application/zip",
    "application/javascript",
    "text/plain",
    "application/octet-stream",
    "image/gif",
    "image/webp",
    "audio/mpeg",
])

# File sizes within the 25 MB limit (use small values for actual allocation,
# but test boundary logic via the service's size check)
valid_size_strategy = st.one_of(
    st.integers(min_value=1, max_value=1024),  # Small files (fast)
    st.just(MAX_FILE_SIZE_BYTES),  # Exact boundary (tested once)
)

# File sizes exceeding the 25 MB limit
invalid_size_strategy = st.just(MAX_FILE_SIZE_BYTES + 1)


# ---------------------------------------------------------------------------
# Property Tests: Document Upload Validation
# ---------------------------------------------------------------------------
class TestDocumentUploadValidation:
    """
    Property-based tests proving document upload validation correctness.

    Core invariants:
    1. Valid MIME + size ≤ 25MB → accepted
    2. Invalid MIME (any size) → rejected with InvalidMimeTypeError
    3. Valid MIME + size > 25MB → rejected with FileSizeExceededError
    """

    @given(
        mime_type=valid_mime_strategy,
        file_size=valid_size_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_valid_mime_and_size_accepted(
        self, mime_type, file_size
    ):
        """
        Property: Upload succeeds when MIME type is in the allowed set
        AND file size is at or below 25 MB.

        The service should persist the document without raising any
        validation exception.
        """
        from app.modules.documents.service import DocumentService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        uploaded_by = uuid.uuid4()

        # Generate synthetic file data of the specified size
        file_data = b"\x00" * file_size

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Mock storage backend to avoid real file I/O
        mock_storage = AsyncMock()
        mock_storage.save.return_value = f"/storage/{tenant_id}/doc.pdf"

        with patch(
            "app.modules.documents.service._audit",
            new_callable=MagicMock,
        ) as mock_audit:
            mock_audit.log_action = AsyncMock()
            service = DocumentService(storage=mock_storage)

            # INVARIANT: No exception raised for valid MIME + valid size
            await service.upload_document(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                uploaded_by=uploaded_by,
                file_data=file_data,
                file_name="test_document.pdf",
                mime_type=mime_type,
                document_type=DocumentType.LAB_REPORT,
                title="Test Document",
            )

        # Verify document was persisted
        assert mock_db.add.called, "Document not added to DB session"

    @given(
        mime_type=invalid_mime_strategy,
        file_size=valid_size_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_invalid_mime_rejected(
        self, mime_type, file_size
    ):
        """
        Property: Upload with a MIME type NOT in the allowed set is
        ALWAYS rejected with InvalidMimeTypeError, regardless of
        file size.

        This prevents potentially dangerous file types from entering
        the clinical document store.
        """
        from app.modules.documents.service import DocumentService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        uploaded_by = uuid.uuid4()
        file_data = b"\x00" * file_size

        mock_db = AsyncMock()
        mock_storage = AsyncMock()

        service = DocumentService(storage=mock_storage)

        # INVARIANT: Must raise InvalidMimeTypeError
        with pytest.raises(InvalidMimeTypeError) as exc_info:
            await service.upload_document(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                uploaded_by=uploaded_by,
                file_data=file_data,
                file_name="malicious_file.exe",
                mime_type=mime_type,
                document_type=DocumentType.OTHER,
                title="Invalid Upload",
            )

        # Verify the error carries the rejected MIME type
        assert exc_info.value.mime_type == mime_type

    @given(
        mime_type=valid_mime_strategy,
        file_size=invalid_size_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_oversized_file_rejected(
        self, mime_type, file_size
    ):
        """
        Property: Upload with a valid MIME type but file size exceeding
        25 MB is ALWAYS rejected with FileSizeExceededError.

        Even legitimate file types must respect the size boundary to
        prevent storage exhaustion and ensure system stability.
        """
        from app.modules.documents.service import DocumentService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        uploaded_by = uuid.uuid4()

        # Generate file data slightly over the limit
        file_data = b"\x00" * file_size

        mock_db = AsyncMock()
        mock_storage = AsyncMock()

        service = DocumentService(storage=mock_storage)

        # INVARIANT: Must raise FileSizeExceededError
        with pytest.raises(FileSizeExceededError) as exc_info:
            await service.upload_document(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                uploaded_by=uploaded_by,
                file_data=file_data,
                file_name="huge_scan.pdf",
                mime_type=mime_type,
                document_type=DocumentType.RADIOLOGY,
                title="Oversized Upload",
            )

        # Verify error carries size details
        assert exc_info.value.size_bytes == file_size
        assert exc_info.value.max_bytes == MAX_FILE_SIZE_BYTES
