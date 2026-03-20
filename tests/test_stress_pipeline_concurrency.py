from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AETHELGARD_API_KEY", "stress-test-key")

import api


@dataclass
class _FakeJob:
    job_id: str
    scenario: str
    status: str = "pending"
    error: str | None = None


class _FakeDetectionAgent:
    async def collect_baseline(self, _metrics):
        return None


class _FakeSimulator:
    def inject_anomaly(self, scenario: str):
        return SimpleNamespace(
            target_service="payment-api",
            anomaly_type=scenario,
            severity=SimpleNamespace(value="high"),
            duration_seconds=5,
        )

    def generate_metrics(self):
        return []


class _FakeOrchestrator:
    def __init__(self):
        self._jobs: Dict[str, _FakeJob] = {}
        self._lock = asyncio.Lock()
        self._counter = 0
        self.detection_agent = _FakeDetectionAgent()

    async def create_job(self, scenario: str):
        async with self._lock:
            self._counter += 1
            job_id = f"job-{self._counter:06d}"
            job = _FakeJob(job_id=job_id, scenario=scenario)
            self._jobs[job_id] = job
            return job

    async def run_job(self, job, metrics):
        async with self._lock:
            tracked = self._jobs[job.job_id]
            tracked.status = "running"
        await asyncio.sleep(0.02)
        async with self._lock:
            tracked = self._jobs[job.job_id]
            tracked.status = "completed"

    async def get_job(self, job_id: str):
        async with self._lock:
            return self._jobs.get(job_id)


@pytest.mark.asyncio
async def test_pipeline_run_100_concurrent_requests_stress():
    orchestrator = _FakeOrchestrator()
    simulator = _FakeSimulator()

    api.app.state.orchestrator = orchestrator
    api.app.state.simulator = simulator

    transport = ASGITransport(app=api.app)

    latencies_ms: List[float] = []
    status_codes: List[int] = []
    accepted_job_ids: List[str] = []

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def submit_once():
            start = time.perf_counter()
            response = await client.post(
                "/api/v1/pipeline/run",
                params={"scenario": "payment_latency_spike"},
                headers={"X-API-Key": "stress-test-key"},
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            latencies_ms.append(latency_ms)
            status_codes.append(response.status_code)
            if response.status_code == 202:
                payload = response.json()
                accepted_job_ids.append(payload["job_id"])

        await asyncio.gather(*[submit_once() for _ in range(100)])

    success_count = sum(1 for code in status_codes if code == 202)
    failure_count = len(status_codes) - success_count
    failure_rate = failure_count / max(1, len(status_codes))

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        completed = 0
        for job_id in accepted_job_ids:
            job = await orchestrator.get_job(job_id)
            if job and job.status == "completed":
                completed += 1
        if completed == len(accepted_job_ids):
            break
        await asyncio.sleep(0.05)

    completed_jobs = 0
    for job_id in accepted_job_ids:
        job = await orchestrator.get_job(job_id)
        if job and job.status == "completed":
            completed_jobs += 1

    completion_consistency = completed_jobs / max(1, len(accepted_job_ids))

    sorted_latencies = sorted(latencies_ms)
    p95_index = max(0, int(0.95 * len(sorted_latencies)) - 1)
    p95_latency_ms = sorted_latencies[p95_index]

    metrics = {
        "requests_total": len(status_codes),
        "requests_success": success_count,
        "failure_rate": failure_rate,
        "latency_p95_ms": p95_latency_ms,
        "completion_consistency": completion_consistency,
    }

    assert metrics["requests_total"] == 100
    assert metrics["failure_rate"] == 0.0
    assert metrics["completion_consistency"] == 1.0
    assert metrics["latency_p95_ms"] < 1500.0
