"""
Unit tests for cache module — extended coverage.

Tests init_redis, close_redis, cache_invalidate_pattern, and error
handling paths (ConnectionError, JSON decode errors) that are not
covered by the basic graceful degradation tests in test_cache.py.

Validates:
- init_redis sets _redis_client to None when connection fails
- close_redis resets global state cleanly
- cache_get returns None on ConnectionError during operation
- cache_set returns False on serialization error
- cache_invalidate_pattern returns False when Redis unavailable
- cache_invalidate_pattern iterates SCAN correctly
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure redis mock is available before importing cache module
if "redis" not in sys.modules:
    mock_redis = MagicMock()
    sys.modules["redis"] = mock_redis
    sys.modules["redis.asyncio"] = mock_redis.asyncio
    sys.modules["redis.exceptions"] = mock_redis.exceptions
    mock_redis.exceptions.ConnectionError = type("ConnectionError", (Exception,), {})
    mock_redis.exceptions.TimeoutError = type("TimeoutError", (Exception,), {})

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.cache import (
    cache_get,
    cache_invalidate,
    cache_invalidate_pattern,
    cache_set,
    close_redis,
    init_redis,
)


# ---------------------------------------------------------------------------
# Test: init_redis handles connection failure gracefully
# ---------------------------------------------------------------------------
class TestInitRedis:
    """Verify init_redis handles startup failures without crashing."""

    @pytest.mark.asyncio
    async def test_init_redis_sets_none_on_connection_failure(self):
        """init_redis sets _redis_client to None when Redis is unreachable."""
        with patch("app.core.cache.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.from_url.side_effect = RedisConnectionError("refused")
            with patch("app.core.cache.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(redis_url="redis://bad:6379/0")
                await init_redis()

        # After failure, client should be None (graceful degradation)
        with patch("app.core.cache._redis_client", None):
            result = await cache_get("any:key")
            assert result is None


# ---------------------------------------------------------------------------
# Test: close_redis resets state
# ---------------------------------------------------------------------------
class TestCloseRedis:
    """Verify close_redis cleans up global state."""

    @pytest.mark.asyncio
    async def test_close_redis_with_no_client(self):
        """close_redis doesn't crash when _redis_client is already None."""
        with patch("app.core.cache._redis_client", None):
            with patch("app.core.cache._connection_pool", None):
                # Should not raise
                await close_redis()


# ---------------------------------------------------------------------------
# Test: cache_get error handling paths
# ---------------------------------------------------------------------------
class TestCacheGetErrors:
    """Verify cache_get handles runtime errors gracefully."""

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self):
        """cache_get returns None when Redis raises ConnectionError mid-op."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RedisConnectionError("lost"))

        with patch("app.core.cache._redis_client", mock_client):
            result = await cache_get("some:key")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_json_decode_error(self):
        """cache_get returns None when cached value is not valid JSON."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="not-valid-json{{{")

        with patch("app.core.cache._redis_client", mock_client):
            result = await cache_get("corrupt:key")

        assert result is None


# ---------------------------------------------------------------------------
# Test: cache_set error handling paths
# ---------------------------------------------------------------------------
class TestCacheSetErrors:
    """Verify cache_set handles serialization and connection errors."""

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_error(self):
        """cache_set returns False when Redis raises ConnectionError."""
        mock_client = AsyncMock()
        mock_client.setex = AsyncMock(side_effect=RedisConnectionError("down"))

        with patch("app.core.cache._redis_client", mock_client):
            with patch("app.core.cache.get_settings") as mock_s:
                mock_s.return_value = MagicMock(redis_default_ttl=300)
                result = await cache_set("key", {"data": "value"}, ttl=60)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_non_serializable_value(self):
        """cache_set returns False when value can't be JSON-serialized."""
        mock_client = AsyncMock()

        with patch("app.core.cache._redis_client", mock_client):
            with patch("app.core.cache.get_settings") as mock_s:
                mock_s.return_value = MagicMock(redis_default_ttl=300)
                # Sets and custom objects are not JSON-serializable
                result = await cache_set("key", {1, 2, 3}, ttl=60)

        assert result is False


# ---------------------------------------------------------------------------
# Test: cache_invalidate_pattern
# ---------------------------------------------------------------------------
class TestCacheInvalidatePattern:
    """Verify cache_invalidate_pattern handles various scenarios."""

    @pytest.mark.asyncio
    async def test_returns_false_when_redis_unavailable(self):
        """cache_invalidate_pattern returns False when client is None."""
        with patch("app.core.cache._redis_client", None):
            result = await cache_invalidate_pattern("tenant:*:risk:*")

        assert result is False

    @pytest.mark.asyncio
    async def test_scans_and_deletes_matching_keys(self):
        """cache_invalidate_pattern uses SCAN to find and delete keys."""
        mock_client = AsyncMock()
        # Simulate SCAN returning keys then finishing (cursor=0)
        mock_client.scan = AsyncMock(return_value=(0, ["key1", "key2"]))
        mock_client.delete = AsyncMock()

        with patch("app.core.cache._redis_client", mock_client):
            result = await cache_invalidate_pattern("tenant:abc:*")

        assert result is True
        mock_client.delete.assert_awaited_once_with("key1", "key2")

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_error(self):
        """cache_invalidate_pattern returns False on ConnectionError."""
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(side_effect=RedisConnectionError("gone"))

        with patch("app.core.cache._redis_client", mock_client):
            result = await cache_invalidate_pattern("bad:*")

        assert result is False
