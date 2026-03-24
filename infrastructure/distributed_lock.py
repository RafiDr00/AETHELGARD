import asyncio
from typing import Optional
import redis.asyncio as aioredis
from core.config import get_settings
from core.logging_config import get_logger

logger = get_logger(__name__)

class DistributedLock:
    """Redis-based distributed lock to prevent concurrent remediation on the same resource."""
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self._settings = get_settings()
        
    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = aioredis.Redis(
                host=self._settings.redis.host,
                port=self._settings.redis.port,
                db=self._settings.redis.db,
                password=self._settings.redis.password,
                decode_responses=True,
                socket_timeout=self._settings.redis.socket_timeout,
            )
        return self._redis

    async def acquire(self, resource_id: str, ttl_ms: int = 30000) -> bool:
        redis = await self._get_redis()
        key = f"aethelgard:lock:{resource_id}"
        try:
            result = await redis.set(key, "locked", nx=True, px=ttl_ms)
            return bool(result)
        except Exception as e:
            logger.error("distributed_lock_acquire_failed", resource_id=resource_id, error=str(e))
            return False

    async def release(self, resource_id: str) -> None:
        redis = await self._get_redis()
        key = f"aethelgard:lock:{resource_id}"
        try:
            await redis.delete(key)
        except Exception as e:
            logger.error("distributed_lock_release_failed", resource_id=resource_id, error=str(e))
