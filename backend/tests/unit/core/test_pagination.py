"""Unit tests for app.core.pagination (cursor encode/decode + response builder)."""

import json
import base64

import pytest

from app.core.pagination import (
    PaginationParams,
    encode_cursor,
    decode_cursor,
    PaginatedResponse,
)


class TestEncodeCursor:
    def test_returns_string(self):
        result = encode_cursor("created_at", "2026-01-01T00:00:00Z")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_default_direction_desc(self):
        token = encode_cursor("created_at", "v")
        raw = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        assert raw["dir"] == "desc"

    def test_custom_direction_asc(self):
        token = encode_cursor("id", "abc", direction="asc")
        raw = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        assert raw["dir"] == "asc"

    def test_roundtrip(self):
        token = encode_cursor("created_at", "2026-04-01", "desc")
        decoded = decode_cursor(token)
        assert decoded == {"field": "created_at", "value": "2026-04-01", "dir": "desc"}


class TestDecodeCursor:
    def test_invalid_base64_returns_none(self):
        assert decode_cursor("not!valid!base64!!!") is None

    def test_invalid_json_returns_none(self):
        bad = base64.urlsafe_b64encode(b"{notjson").decode()
        assert decode_cursor(bad) is None

    def test_missing_keys_returns_none(self):
        partial = base64.urlsafe_b64encode(json.dumps({"field": "x"}).encode()).decode()
        assert decode_cursor(partial) is None

    def test_extra_keys_still_valid(self):
        payload = json.dumps({"field": "f", "value": "v", "dir": "asc", "extra": 1})
        token = base64.urlsafe_b64encode(payload.encode()).decode()
        result = decode_cursor(token)
        assert result is not None
        assert result["field"] == "f"

    def test_empty_string_returns_none(self):
        assert decode_cursor("") is None


class TestPaginatedResponse:
    def test_to_meta_with_cursor(self):
        r = PaginatedResponse(items=[1, 2, 3], cursor="abc", has_more=True)
        assert r.to_meta() == {"cursor": "abc", "has_more": True}

    def test_to_meta_no_more_pages(self):
        r = PaginatedResponse(items=[1], cursor=None, has_more=False)
        assert r.to_meta() == {"cursor": None, "has_more": False}

    def test_items_preserved(self):
        items = [{"id": 1}, {"id": 2}]
        r = PaginatedResponse(items=items, cursor=None, has_more=False)
        assert r.items == items


class TestPaginationParams:
    def test_construct_with_cursor(self):
        p = PaginationParams(page_size=25, cursor="abc")
        assert p.page_size == 25
        assert p.cursor == "abc"

    def test_construct_without_cursor(self):
        p = PaginationParams(page_size=10, cursor=None)
        assert p.cursor is None
