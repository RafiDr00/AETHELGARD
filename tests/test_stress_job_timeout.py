from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("AETHELGARD_API_KEY", "stress-test-key")
os.environ.setdefault("AETHELGARD_JOB_TIMEOUT_SECONDS", "0.1")

from agents.orchestrator import AgentOrchestrator, PipelineJob


@pytest.mark.asyncio
async def test_job_timeout_behavior_under_forced_slow_execution():
    orchestrator = AgentOrchestrator()
    orchestrator._job_execution_semaphore = asyncio.Semaphore(4)
    orchestrator._job_execution_timeout_seconds = 0.1

    async def _slow_run_full_pipeline(*, metrics, correlation_id, scenario):
        await asyncio.sleep(0.35)
        return None

    orchestrator.run_full_pipeline = _slow_run_full_pipeline

    timeout_jobs = []
    latencies_ms = []

    async def run_once(index: int):
        job = PipelineJob(job_id=f"timeout-job-{index:03d}", scenario="payment_latency_spike")
        async with orchestrator._jobs_lock:
            orchestrator._jobs[job.job_id] = job

        start = time.perf_counter()
        await orchestrator.run_job(job=job, metrics=[])
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

        async with orchestrator._jobs_lock:
            timeout_jobs.append(orchestrator._jobs[job.job_id])

    await asyncio.gather(*[run_once(i) for i in range(20)])

    failed = [j for j in timeout_jobs if j.status == "failed"]
    timed_out = [j for j in failed if j.error and "job_execution_timeout_seconds" in j.error]

    failure_rate = 1.0 - (len(timed_out) / max(1, len(timeout_jobs)))
    completion_consistency = len(timed_out) / max(1, len(timeout_jobs))

    sorted_latencies = sorted(latencies_ms)
    p95_index = max(0, int(0.95 * len(sorted_latencies)) - 1)
    p95_latency_ms = sorted_latencies[p95_index]

    metrics = {
        "jobs_total": len(timeout_jobs),
        "timed_out_jobs": len(timed_out),
        "failure_rate": failure_rate,
        "latency_p95_ms": p95_latency_ms,
        "job_completion_consistency": completion_consistency,
    }

    assert metrics["jobs_total"] == 20
    assert metrics["timed_out_jobs"] == 20
    assert metrics["failure_rate"] == 0.0
    assert metrics["job_completion_consistency"] == 1.0
    assert metrics["latency_p95_ms"] < 1500.0
