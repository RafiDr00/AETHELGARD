from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List

import pytest

os.environ.setdefault("AETHELGARD_API_KEY", "stress-test-key")

from agents.orchestrator import AgentOrchestrator, PipelineJob


class _FlakyRedis:
    def __init__(self):
        self.connected = True
        self.failures = 0
        self.kv: Dict[str, str] = {}
        self.list_index: List[str] = []
        self.pipeline_outcomes: Dict[str, str] = {}

    def _ensure_connected(self):
        if not self.connected:
            self.failures += 1
            raise ConnectionError("redis_disconnected")

    async def set(self, key, value):
        self._ensure_connected()
        self.kv[key] = value

    async def lrem(self, key, count, value):
        self._ensure_connected()
        self.list_index = [v for v in self.list_index if v != value]

    async def lpush(self, key, value):
        self._ensure_connected()
        self.list_index.insert(0, value)

    async def ltrim(self, key, start, end):
        self._ensure_connected()
        if end >= 0:
            self.list_index = self.list_index[start:end + 1]

    async def lrange(self, key, start, end):
        self._ensure_connected()
        if end == -1:
            return self.list_index[start:]
        return self.list_index[start:end + 1]

    async def delete(self, key):
        self._ensure_connected()
        self.kv.pop(key, None)

    async def hdel(self, key, field):
        self._ensure_connected()
        self.pipeline_outcomes.pop(field, None)


@pytest.mark.asyncio
async def test_redis_disconnect_reconnect_stress_consistency():
    orchestrator = AgentOrchestrator()
    redis = _FlakyRedis()
    orchestrator._redis = redis

    jobs = [PipelineJob(job_id=f"redis-job-{i:03d}", scenario="payment_latency_spike") for i in range(60)]

    latencies_ms: List[float] = []

    async def persist_one(job: PipelineJob):
        start = time.perf_counter()
        await orchestrator._persist_job_state(job)
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

    await asyncio.gather(*[persist_one(j) for j in jobs[:20]])

    redis.connected = False
    await asyncio.gather(*[persist_one(j) for j in jobs[20:40]])

    redis.connected = True
    await asyncio.gather(*[persist_one(j) for j in jobs[40:]])

    persisted_ids = set(redis.list_index)
    expected_after_reconnect = {j.job_id for j in jobs[:20] + jobs[40:]}

    completion_consistency = len(persisted_ids & expected_after_reconnect) / max(1, len(expected_after_reconnect))
    failure_rate = redis.failures / max(1, len(jobs) * 4)

    sorted_latencies = sorted(latencies_ms)
    p95_index = max(0, int(0.95 * len(sorted_latencies)) - 1)
    p95_latency_ms = sorted_latencies[p95_index]

    metrics = {
        "operations_total": len(jobs),
        "redis_failure_events": redis.failures,
        "failure_rate": failure_rate,
        "latency_p95_ms": p95_latency_ms,
        "job_completion_consistency": completion_consistency,
    }

    assert metrics["operations_total"] == 60
    assert metrics["redis_failure_events"] > 0
    assert metrics["job_completion_consistency"] == 1.0
    assert metrics["latency_p95_ms"] < 1500.0
