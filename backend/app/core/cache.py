"""
PrescpHealth Backend — Redis Connection and Caching Utilities.

Provides async Redis client management and caching helper functions.
Redis serves multiple roles in PrescpHealth:
  1. Cache: Store frequently accessed data (risk scores, patient summaries)
  2. Rate limiting: Track request counts per user per time window
  3. Celery broker: Message queue for background task dispatch
  4. Session data: Refresh token families for rotation detection

Design Principles:
  - Redis is ACCELERATION, not a requirement. If Redis is unavailable,
    the app falls back to database queries (slower but functional).
  - Never cache PHI without application-layer encryption.
  - All cached data has a TTL — nothing lives forever in cache.
  - Cache keys are namespaced by tenant to prevent cross-tenant leakage.

Usage:
    from app.core.cache import get_redis, cache_get, cache_set

    redis = await get_redis()
    await cache_set("risk:patient_123", scores_json, ttl=300)
    cached = await cache_get("risk:patient_123")
"""

import json
from typing import Any

import structlog
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

from app.config import get_settings

# ---------------------------------------------------------------------------
# Module logger — logs cache operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Global Redis client — initialized at startup, shared across requests
# ---------------------------------------------------------------------------
_redis_client: Redis | None = None
_connection_pool: ConnectionPool | None = None


async def init_redis() -> None:
    """
    Initialize the Redis connection pool.

    Called once during application startup (in lifespan handler).
    Creates a connection pool that's shared across all requests.
    Pool connections are lazy — they connect on first use, not at init.

    If Redis is unreachable at startup, we log a warning but don't crash.
    The app will operate in degraded mode (no caching, no rate limiting).
    """
    global _redis_client, _connection_pool

    settings = get_settings()

    try:
        _connection_pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=50,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=2,  # Per performance budget: Redis ops < 2ms target
            retry_on_timeout=True,
        )

        _redis_client = Redis(connection_pool=_connection_pool)

        # Verify connection is alive
        await _redis_client.ping()
        logger.info("redis_initialized", url=settings.redis_url.split("@")[-1])

    except (ConnectionError, TimeoutError, OSError) as e:
        # Redis unavailable at startup — log warning, continue without it.
        # Per error-handling steering rule: Redis is acceleration, not requirement.
        logger.warning(
            "redis_unavailable_at_startup",
            error=str(e),
            impact="App will run without caching and rate limiting",
        )
        _redis_client = None
        _connection_pool = None


async def close_redis() -> None:
    """
    Close Redis connections and release pool resources.

    Called during application shutdown (in lifespan handler).
    """
    global _redis_client, _connection_pool

    if _redis_client is not None:
        await _redis_client.close()
        logger.info("redis_connections_closed")

    if _connection_pool is not None:
        await _connection_pool.disconnect()

    _redis_client = None
    _connection_pool = None


async def get_redis() -> Redis | None:
    """
    Get the Redis client instance.

    Returns None if Redis is unavailable — callers MUST handle this
    gracefully by falling back to database queries.

    Returns:
        Redis | None: The async Redis client, or None if unavailable.
    """
    return _redis_client


async def cache_get(key: str) -> Any | None:
    """
    Get a value from cache by key.

    Returns None if:
    - Key doesn't exist (cache miss)
    - Redis is unavailable (graceful degradation)
    - Value can't be deserialized

    Args:
        key: Cache key (should be namespaced, e.g., "tenant:patient:risk:uuid")

    Returns:
        The cached value (deserialized from JSON), or None on miss/error.
    """
    if _redis_client is None:
        return None

    try:
        raw = await _redis_client.get(key)
        if raw is None:
            return None

        return json.loads(raw)

    except (ConnectionError, TimeoutError) as e:
        # Redis went down mid-request — log and return None (caller falls back to DB)
        logger.warning("cache_get_failed", key=key, error=str(e))
        return None
    except (json.JSONDecodeError, TypeError) as e:
        # Corrupted cache entry — log and return None
        logger.warning("cache_deserialize_failed", key=key, error=str(e))
        return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> bool:
    """
    Set a value in cache with optional TTL.

    Args:
        key: Cache key (should be namespaced by tenant)
        value: Value to cache (must be JSON-serializable)
        ttl: Time-to-live in seconds. Defaults to REDIS_DEFAULT_TTL (300s).
             All cached data MUST have a TTL — nothing lives forever.

    Returns:
        True if cached successfully, False if Redis unavailable or error.
    """
    if _redis_client is None:
        return False

    settings = get_settings()
    effective_ttl = ttl if ttl is not None else settings.redis_default_ttl

    try:
        serialized = json.dumps(value)
        await _redis_client.setex(key, effective_ttl, serialized)
        return True

    except (ConnectionError, TimeoutError) as e:
        # Redis went down — log warning, return False (caller continues without cache)
        logger.warning("cache_set_failed", key=key, error=str(e))
        return False
    except (TypeError, ValueError) as e:
        # Value not serializable — this is a programming error, log as error
        logger.error("cache_serialize_failed", key=key, error=str(e))
        return False


async def cache_invalidate(key: str) -> bool:
    """
    Delete a key from cache (invalidation).

    Used when data changes and the cached version is stale.
    For example: after a new measurement is saved, invalidate
    the cached risk scores for that patient.

    Args:
        key: Cache key to delete.

    Returns:
        True if deleted (or key didn't exist), False if Redis unavailable.
    """
    if _redis_client is None:
        return False

    try:
        await _redis_client.delete(key)
        return True

    except (ConnectionError, TimeoutError) as e:
        logger.warning("cache_invalidate_failed", key=key, error=str(e))
        return False


async def cache_invalidate_pattern(pattern: str) -> bool:
    """
    Delete all keys matching a pattern (bulk invalidation).

    Useful for invalidating all cached data for a patient when their
    profile changes, or all tenant data when tenant settings change.

    WARNING: SCAN-based — don't use with patterns that match millions of keys.

    Args:
        pattern: Redis glob pattern (e.g., "tenant:abc:patient:123:*")

    Returns:
        True if operation completed, False if Redis unavailable.
    """
    if _redis_client is None:
        return False

    try:
        cursor = 0
        while True:
            cursor, keys = await _redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                await _redis_client.delete(*keys)
            if cursor == 0:
                break
        return True

    except (ConnectionError, TimeoutError) as e:
        logger.warning("cache_invalidate_pattern_failed", pattern=pattern, error=str(e))
        return False
