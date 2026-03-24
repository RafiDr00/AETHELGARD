import json
import time
from typing import Optional, List
import redis.asyncio as aioredis
from core.config import get_settings
from core.logging_config import get_logger
from domain.job import Job

logger = get_logger(__name__)

class JobStore:
    """Persistent storage for orchestrator pipeline jobs."""
    _REDIS_JOB_PREFIX = "aethelgard:job:"
    _REDIS_JOBS_INDEX = "aethelgard:jobs:index"
    _REDIS_MAX_JOBS = 1000

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

    async def create_job(self, scenario: str) -> Job:
        job = Job(scenario=scenario)
        await self._persist_job(job)
        return job

    async def update_state(self, job: Job) -> None:
        await self._persist_job(job)

    async def get_job(self, job_id: str) -> Optional[Job]:
        redis = await self._get_redis()
        key = f"{self._REDIS_JOB_PREFIX}{job_id}"
        try:
            raw = await redis.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            # handle 'status' translation or any other required parsing if needed, pydantic handles it.
            return Job(**data)
        except Exception as e:
            logger.error("job_store_get_failed", job_id=job_id, error=str(e))
            return None

    async def _persist_job(self, job: Job) -> None:
        redis = await self._get_redis()
        payload = job.model_dump()
        payload["updated_at"] = time.time()
        serialized = json.dumps(payload, default=str)
        key = f"{self._REDIS_JOB_PREFIX}{job.id}"
        try:
            await redis.set(key, serialized)
            await redis.lrem(self._REDIS_JOBS_INDEX, 0, job.id)
            await redis.lpush(self._REDIS_JOBS_INDEX, job.id)
            await redis.ltrim(self._REDIS_JOBS_INDEX, 0, self._REDIS_MAX_JOBS - 1)
        except Exception as e:
            logger.error("job_store_persist_failed", job_id=job.id, error=str(e))

    async def list_jobs(self, limit: int = 20) -> List[Job]:
        redis = await self._get_redis()
        try:
            job_ids = await redis.lrange(self._REDIS_JOBS_INDEX, 0, limit - 1)
            jobs = []
            for job_id in job_ids:
                job = await self.get_job(job_id)
                if job:
                    jobs.append(job)
            return jobs
        except Exception as e:
            logger.error("job_store_list_failed", error=str(e))
            return []

class FingerprintStore:
    """Store for anomaly fingerprints to prevent duplicate active remediations."""
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

    async def claim_fingerprint(self, fingerprint: str, ttl_seconds: float = None) -> bool:
        redis = await self._get_redis()
        key = f"aethelgard:fingerprint:{fingerprint}"
        if ttl_seconds is None:
            # Fallback to configured dedup ttl
            ttl_seconds = getattr(self._settings.dedup, "fingerprint_ttl_seconds", 300)
        try:
            result = await redis.set(key, "active", nx=True, ex=int(ttl_seconds))
            return bool(result)
        except Exception as e:
            logger.error("fingerprint_store_claim_failed", fingerprint=fingerprint, error=str(e))
            return False

    async def release_fingerprint(self, fingerprint: str) -> None:
        redis = await self._get_redis()
        key = f"aethelgard:fingerprint:{fingerprint}"
        try:
            await redis.delete(key)
        except Exception as e:
            logger.error("fingerprint_store_release_failed", fingerprint=fingerprint, error=str(e))
