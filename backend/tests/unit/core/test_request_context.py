"""
Unit tests for app.core.request_context.

Tests UUID generation, context var get/set, and isolation across async contexts.
"""

import asyncio
import re
import uuid

import pytest

from app.core import request_context


def test_generate_request_id_returns_valid_uuid_string():
    """generate_request_id returns a valid UUID4 string."""
    rid = request_context.generate_request_id()
    assert isinstance(rid, str)
    # Must parse as a UUID
    parsed = uuid.UUID(rid)
    assert parsed.version == 4


def test_generate_request_id_returns_unique_values():
    """Two consecutive calls return different IDs."""
    a = request_context.generate_request_id()
    b = request_context.generate_request_id()
    assert a != b


def test_set_and_get_request_id_in_same_context():
    """set_request_id stores a value that get_request_id returns."""
    rid = request_context.generate_request_id()
    request_context.set_request_id(rid)
    assert request_context.get_request_id() == rid


def test_get_request_id_default_is_empty_string():
    """In a fresh context, get_request_id returns empty string."""
    import contextvars

    # Run inside an isolated copy of the current context so any prior
    # set_request_id calls in other tests don't leak in.
    ctx = contextvars.Context()
    result = ctx.run(request_context.get_request_id)
    assert result == ""


@pytest.mark.asyncio
async def test_request_id_isolated_across_tasks():
    """Two concurrent tasks have isolated request_id values."""
    async def task_with_id(set_id: str) -> str:
        request_context.set_request_id(set_id)
        await asyncio.sleep(0.01)
        return request_context.get_request_id()

    # Each task runs in its own copied context
    results = await asyncio.gather(
        asyncio.create_task(task_with_id("id-A")),
        asyncio.create_task(task_with_id("id-B")),
    )
    # Each task sees its own value
    assert set(results) == {"id-A", "id-B"}
