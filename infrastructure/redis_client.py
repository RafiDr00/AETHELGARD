"""
infrastructure/redis_client.py — process-wide shared Redis connection pool.

All three infrastructure classes (JobStore, FingerprintStore, DistributedLock)
share one pool rather than each holding an independent unbounded connection.
The pool is created on the first call to get_shared_redis_client() and reused
for every subsequent call.  Call close_shared_redis_client() from the app
shutdown hook to drain the pool cleanly.
"""
from typing import Optional

import redis.asyncio as aioredis

from core.config import get_settings
from core.logging_config import get_logger

logger = get_logger(__name__)

_pool: Optional[aioredis.ConnectionPool] = None
_client: Optional[aioredis.Redis] = None


def get_shared_redis_client() -> aioredis.Redis:
    """
    Return the process-wide Redis client backed by a bounded connection pool.

    The pool is created lazily on the first call using settings from
    settings.redis (host, port, db, password, socket_timeout) and bounded to
    settings.redis.connection_pool_size connections.  Every call after the
    first returns the same client instance — no new connections are opened.

    This function is intentionally synchronous: ConnectionPool creation does
    not open network connections (those are established lazily per-operation),
    so no await is needed and the function is safe to call from startup code
    or as a fallback inside async methods.
    """
    global _pool, _client
    if _client is None:
        settings = get_settings()
        _pool = aioredis.ConnectionPool(
            host=settings.redis.host,
            port=settings.redis.port,
            db=settings.redis.db,
            password=settings.redis.password,
            max_connections=settings.redis.connection_pool_size,
            decode_responses=True,
            socket_timeout=settings.redis.socket_timeout,
        )
        _client = aioredis.Redis(connection_pool=_pool)
        logger.info(
            "redis_shared_pool_created",
            host=settings.redis.host,
            port=settings.redis.port,
            max_connections=settings.redis.connection_pool_size,
        )
    return _client


async def close_shared_redis_client() -> None:
    """
    Drain and close the shared connection pool.

    Safe to call even if the pool was never initialised (no-op in that case).
    Call once from the application shutdown hook; do not call between requests.
    """
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("redis_shared_pool_closed")
