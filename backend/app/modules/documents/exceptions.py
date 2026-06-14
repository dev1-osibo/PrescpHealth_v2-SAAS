"""
Documents Module — Custom Exceptions
======================================
Domain-specific exceptions for the documents module.
HTTP layer maps these to appropriate status codes.
"""


class DocumentNotFoundError(Exception):
    """Raised when a requested document UUID does not exist in the tenant scope."""

    def __init__(self, document_id: str) -> None:
        """Initialise with the document UUID (never include PHI)."""
        super().__init__(f"Document not found: {document_id}")
        self.document_id = document_id


class InvalidMimeTypeError(Exception):
    """Raised when an uploaded file has a disallowed MIME type."""

    def __init__(self, mime_type: str) -> None:
        """Initialise with the rejected MIME type."""
        super().__init__(f"MIME type not permitted: {mime_type}")
        self.mime_type = mime_type


class FileSizeExceededError(Exception):
    """Raised when an uploaded file exceeds the maximum permitted size."""

    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        """Initialise with actual and maximum size values."""
        super().__init__(
            f"File size {size_bytes} bytes exceeds maximum {max_bytes} bytes."
        )
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


class StorageError(Exception):
    """Raised when a storage backend operation fails."""

    def __init__(self, message: str) -> None:
        """Initialise with a safe (non-PHI) error message."""
        super().__init__(message)
