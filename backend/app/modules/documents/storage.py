"""
Documents Module — Storage Backend Abstraction
================================================
Provides an abstract StorageBackend interface and two concrete
implementations:
  - LocalStorageBackend: writes files under backend/uploads/
  - S3StorageBackend: stub — raises NotImplementedError (not yet configured)

Path structure for local storage:
  backend/uploads/{tenant_id}/{document_id}/{filename}

File I/O runs in an asyncio thread executor to avoid blocking the
event loop. aiofiles is preferred; falls back to executor + open().
"""

import asyncio
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Base upload directory — resolve from this file's location to avoid getcwd()
_BASE_UPLOAD_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "uploads"
)


class StorageBackend(ABC):
    """Abstract interface for document storage backends."""

    @abstractmethod
    async def save(self, path: str, data: bytes) -> str:
        """
        Persist binary data at the given path.

        Args:
            path: Logical storage path (relative to backend root).
            data: Raw file bytes to store.

        Returns:
            The fully-resolved storage path as a string.
        """

    @abstractmethod
    async def get(self, path: str) -> bytes:
        """
        Retrieve binary data from the given storage path.

        Args:
            path: Logical storage path previously returned by save().

        Returns:
            Raw file bytes.
        """

    @abstractmethod
    async def delete(self, path: str) -> None:
        """
        Remove a stored file.

        Args:
            path: Logical storage path previously returned by save().
        """


class LocalStorageBackend(StorageBackend):
    """
    Stores files on the local filesystem under _BASE_UPLOAD_DIR.

    Directory structure: {base}/{tenant_id}/{document_id}/{filename}
    Runs blocking I/O in the default thread executor.
    """

    def __init__(self, base_dir: Path = _BASE_UPLOAD_DIR) -> None:
        """Initialise with the root upload directory."""
        self._base = base_dir

    def _full_path(self, path: str) -> Path:
        """Return the absolute filesystem path for a given logical path."""
        return self._base / path

    async def save(self, path: str, data: bytes) -> str:
        """Write bytes to disk, creating parent directories as needed."""
        full = self._full_path(path)
        loop = asyncio.get_event_loop()

        def _write() -> None:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(data)

        await loop.run_in_executor(None, _write)
        log.info("storage.saved", path=path, size_bytes=len(data))
        return str(full)

    async def get(self, path: str) -> bytes:
        """Read bytes from disk."""
        full = self._full_path(path)
        loop = asyncio.get_event_loop()
        data: bytes = await loop.run_in_executor(None, full.read_bytes)
        log.info("storage.retrieved", path=path)
        return data

    async def delete(self, path: str) -> None:
        """Remove a file from disk (no-op if file does not exist)."""
        full = self._full_path(path)
        loop = asyncio.get_event_loop()

        def _remove() -> None:
            if full.exists():
                full.unlink()

        await loop.run_in_executor(None, _remove)
        log.info("storage.deleted", path=path)


class S3StorageBackend(StorageBackend):
    """
    Stub S3 storage backend — not yet configured.

    Replace with boto3/aiobotocore implementation when S3 credentials
    and bucket configuration are available.
    """

    async def save(self, path: str, data: bytes) -> str:
        """Not implemented — S3 storage is not yet configured."""
        raise NotImplementedError("S3 storage backend is not yet configured.")

    async def get(self, path: str) -> bytes:
        """Not implemented — S3 storage is not yet configured."""
        raise NotImplementedError("S3 storage backend is not yet configured.")

    async def delete(self, path: str) -> None:
        """Not implemented — S3 storage is not yet configured."""
        raise NotImplementedError("S3 storage backend is not yet configured.")


def get_storage_backend(backend: str = "local") -> StorageBackend:
    """
    Factory function returning the appropriate storage backend instance.

    Args:
        backend: Backend identifier string ("local" or "s3").

    Returns:
        Concrete StorageBackend instance.
    """
    if backend == "s3":
        return S3StorageBackend()
    return LocalStorageBackend()
