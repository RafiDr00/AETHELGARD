import uuid
from typing import Optional
import redis.asyncio as aioredis
from core.logging_config import get_logger
from infrastructure.redis_client import get_shared_redis_client

logger = get_logger(__name__)

RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

class DistributedLock:
    """Redis-based distributed lock to prevent concurrent remediation on the same resource."""
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client

    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = get_shared_redis_client()
        return self._redis

    async def acquire(self, resource_id: str, ttl_ms: int = 30000) -> Optional[str]:
        redis = await self._get_redis()
        key = f"aethelgard:lock:{resource_id}"
        token = uuid.uuid4().hex
        try:
            result = await redis.set(key, token, nx=True, px=ttl_ms)
            return token if result else None
        except Exception as e:
            logger.error("distributed_lock_acquire_failed", resource_id=resource_id, error=str(e))
            return None

    async def release(self, resource_id: str, token: str) -> None:
        redis = await self._get_redis()
        key = f"aethelgard:lock:{resource_id}"
        try:
            await redis.eval(RELEASE_SCRIPT, 1, key, token)
        except Exception as e:
            logger.error("distributed_lock_release_failed", resource_id=resource_id, error=str(e))
