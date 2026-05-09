"""
PrescpHealth Backend — Cursor-Based Pagination.

Implements cursor-based pagination for all list endpoints.
Cursor pagination is preferred over offset pagination because:
- Consistent results even when data is inserted/deleted between pages
- O(1) performance regardless of page depth (offset gets slower as you go deeper)
- No "skipped items" problem when new records are inserted

How it works:
    1. Client requests: GET /patients?page_size=25
    2. Server returns 25 results + a cursor (opaque string encoding the last item's sort key)
    3. Client requests next page: GET /patients?page_size=25&cursor=abc123
    4. Server decodes cursor, fetches next 25 items after that position

Cursor encoding:
    The cursor is a base64-encoded JSON object containing the sort field value
    and direction. This is opaque to the client — they just pass it back.

Per API design steering rule:
    - Default page size: 25
    - Maximum page size: 100
    - Response includes meta.pagination.cursor and meta.pagination.has_more
"""

import base64
import json
from dataclasses import dataclass

from fastapi import Query


# ---------------------------------------------------------------------------
# Pagination Parameters (FastAPI dependency)
# ---------------------------------------------------------------------------
@dataclass
class PaginationParams:
    """
    Pagination parameters extracted from query string.

    Used as a FastAPI dependency in list endpoints:
        @router.get("/patients")
        async def list_patients(pagination: PaginationParams = Depends(get_pagination)):
            ...

    Attributes:
        page_size: Number of items per page (1-100, default 25)
        cursor: Opaque cursor string from previous response (None for first page)
    """

    page_size: int
    cursor: str | None


def get_pagination(
    page_size: int = Query(default=25, ge=1, le=100, description="Items per page (max 100)"),
    cursor: str | None = Query(default=None, description="Pagination cursor from previous response"),
) -> PaginationParams:
    """
    FastAPI dependency that extracts and validates pagination parameters.

    Args:
        page_size: Number of items to return (1-100, default 25).
        cursor: Opaque cursor from previous page response.

    Returns:
        PaginationParams with validated page_size and decoded cursor.
    """
    return PaginationParams(page_size=page_size, cursor=cursor)


# ---------------------------------------------------------------------------
# Cursor Encoding/Decoding
# ---------------------------------------------------------------------------
def encode_cursor(sort_field: str, sort_value: str, direction: str = "desc") -> str:
    """
    Encode pagination state into an opaque cursor string.

    The cursor contains the sort field, its value at the last item,
    and the sort direction. This allows the next query to pick up
    exactly where the previous page left off.

    Args:
        sort_field: The column being sorted on (e.g., "created_at")
        sort_value: The value of that column on the last item returned
        direction: Sort direction ("asc" or "desc")

    Returns:
        Base64-encoded cursor string (opaque to the client).
    """
    payload = json.dumps({
        "field": sort_field,
        "value": sort_value,
        "dir": direction,
    })
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> dict | None:
    """
    Decode an opaque cursor string back into pagination state.

    Returns None if the cursor is invalid (malformed, tampered with).
    Invalid cursors are treated as "start from beginning" — we don't
    error out because the client might have a stale cursor.

    Args:
        cursor: The opaque cursor string from the client.

    Returns:
        Dict with 'field', 'value', 'dir' keys, or None if invalid.
    """
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(payload)
        # Validate expected keys exist
        if all(k in data for k in ("field", "value", "dir")):
            return data
        return None
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Pagination Response Builder
# ---------------------------------------------------------------------------
@dataclass
class PaginatedResponse:
    """
    Wrapper for paginated list responses.

    Provides the data items plus pagination metadata matching
    the API design steering rule response envelope.

    Attributes:
        items: The list of items for this page.
        cursor: Cursor for the next page (None if no more pages).
        has_more: Whether there are more items after this page.
    """

    items: list
    cursor: str | None
    has_more: bool

    def to_meta(self) -> dict:
        """
        Generate the pagination section of the response meta.

        Returns:
            Dict matching the API envelope: {"cursor": "...", "has_more": true/false}
        """
        return {
            "cursor": self.cursor,
            "has_more": self.has_more,
        }
