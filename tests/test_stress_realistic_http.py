from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List, Optional, Set, Tuple

import httpx
import pytest

psutil = pytest.importorskip("psutil")

BASE_URL = os.environ.get("AETHELGARD_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("AETHELGARD_API_KEY", "dev-aethelgard-key-changeme")
SCENARIO = os.environ.get("AETHELGARD_STRESS_SCENARIO", "payment_latency_spike")

TERMINAL_STATUSES: Set[str] = {"completed", "failed"}


def _headers() -> Dict[str, str]:
    return {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }


def _server_pid_by_port(port: int = 8000) -> Optional[int]:
    for conn in psutil.net_connections(kind="tcp"):
        laddr = getattr(conn, "laddr", None)
        if not laddr:
            continue
        if getattr(laddr, "port", None) == port and conn.status == psutil.CONN_LISTEN:
            return conn.pid
    return None


def _rss_bytes(pid: int) -> int:
    return int(psutil.Process(pid).memory_info().rss)


async def _post_pipeline_run(client: httpx.AsyncClient) -> Tuple[int, float, Optional[str]]:
    start = time.perf_counter()
    response = await client.post(
        "/pipeline/run",
        params={"scenario": SCENARIO},
        headers=_headers(),
        json={},
    )
    latency_ms = (time.perf_counter() - start) * 1000.0

    job_id: Optional[str] = None
    if response.status_code == 202:
        payload = response.json()
        job_id = payload.get("job_id")

    return response.status_code, latency_ms, job_id


async def _poll_jobs_terminal(
    client: httpx.AsyncClient,
    job_ids: List[str],
    timeout_seconds: float,
) -> Dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    terminal: Dict[str, str] = {}

    while time.monotonic() < deadline and len(terminal) < len(job_ids):
        pending = [job_id for job_id in job_ids if job_id not in terminal]

        async def _check(job_id: str) -> Tuple[str, Optional[str]]:
            try:
                response = await client.get(f"/pipeline/jobs/{job_id}", headers=_headers())
                if response.status_code == 200:
                    status = str(response.json().get("status", ""))
                    return job_id, status
                return job_id, None
            except Exception:
                return job_id, None

        results = await asyncio.gather(*[_check(job_id) for job_id in pending])
        for job_id, status in results:
            if status in TERMINAL_STATUSES:
                terminal[job_id] = status

        await asyncio.sleep(0.5)

    return terminal


@pytest.mark.asyncio
async def test_realistic_200_plus_concurrent_pipeline_run_requests():
    limits = httpx.Limits(max_connections=600, max_keepalive_connections=200)
    timeout = httpx.Timeout(30.0, connect=10.0)

    status_codes: List[int] = []
    latencies_ms: List[float] = []
    job_ids: List[str] = []

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        health = await client.get("/health")
        assert health.status_code == 200

        tasks = [_post_pipeline_run(client) for _ in range(220)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            status_code, latency_ms, job_id = result
            status_codes.append(status_code)
            latencies_ms.append(latency_ms)
            if job_id:
                job_ids.append(job_id)

        assert len(status_codes) >= 200

        accepted = sum(1 for code in status_codes if code == 202)
        failure_rate = 1.0 - (accepted / max(1, len(status_codes)))

        sorted_latencies = sorted(latencies_ms)
        p95_index = max(0, int(0.95 * len(sorted_latencies)) - 1)
        p95_latency_ms = sorted_latencies[p95_index]

        terminal = await _poll_jobs_terminal(client, job_ids, timeout_seconds=180.0)
        completion_consistency = len(terminal) / max(1, len(job_ids))

        metrics = {
            "requests_total": len(status_codes),
            "accepted": accepted,
            "failure_rate": failure_rate,
            "latency_p95_ms": p95_latency_ms,
            "job_completion_consistency": completion_consistency,
        }

        assert metrics["requests_total"] >= 200
        assert metrics["job_completion_consistency"] >= 0.95


@pytest.mark.asyncio
async def test_realistic_overload_returns_429_when_saturated():
    limits = httpx.Limits(max_connections=1200, max_keepalive_connections=200)
    timeout = httpx.Timeout(20.0, connect=8.0)

    status_codes: List[int] = []

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        health = await client.get("/health")
        assert health.status_code == 200

        async def _flood_worker(until_ts: float):
            while time.monotonic() < until_ts:
                try:
                    status_code, _, _ = await _post_pipeline_run(client)
                    status_codes.append(status_code)
                except Exception:
                    status_codes.append(599)

        end_ts = time.monotonic() + 25.0
        flooders = [asyncio.create_task(_flood_worker(end_ts)) for _ in range(80)]

        burst_results = await asyncio.gather(*[_post_pipeline_run(client) for _ in range(500)], return_exceptions=True)
        for result in burst_results:
            if isinstance(result, Exception):
                status_codes.append(599)
            else:
                status_code, _, _ = result
                status_codes.append(status_code)

        await asyncio.gather(*flooders)

        overload_429_count = sum(1 for code in status_codes if code == 429)
        assert overload_429_count > 0


@pytest.mark.asyncio
async def test_realistic_sustained_60s_load_memory_and_clean_job_outcomes():
    server_pid = _server_pid_by_port(8000)
    assert server_pid is not None

    rss_before = _rss_bytes(server_pid)

    limits = httpx.Limits(max_connections=800, max_keepalive_connections=200)
    timeout = httpx.Timeout(20.0, connect=8.0)

    status_codes: List[int] = []
    latencies_ms: List[float] = []
    job_ids: List[str] = []
    health_failures: List[str] = []

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        health = await client.get("/health")
        assert health.status_code == 200

        stop_ts = time.monotonic() + 65.0

        async def _health_monitor():
            while time.monotonic() < stop_ts:
                try:
                    response = await client.get("/health")
                    if response.status_code != 200:
                        health_failures.append(f"status={response.status_code}")
                except Exception as exc:
                    health_failures.append(str(exc))
                await asyncio.sleep(2.0)

        async def _load_worker():
            while time.monotonic() < stop_ts:
                try:
                    status_code, latency_ms, job_id = await _post_pipeline_run(client)
                    status_codes.append(status_code)
                    latencies_ms.append(latency_ms)
                    if job_id:
                        job_ids.append(job_id)
                except Exception:
                    status_codes.append(599)
                await asyncio.sleep(0.03)

        monitor_task = asyncio.create_task(_health_monitor())
        workers = [asyncio.create_task(_load_worker()) for _ in range(50)]
        await asyncio.gather(*workers)
        await monitor_task

        health_after = await client.get("/health")
        assert health_after.status_code == 200

        poll_subset = job_ids[-300:] if len(job_ids) > 300 else job_ids
        terminal = await _poll_jobs_terminal(client, poll_subset, timeout_seconds=240.0)

    rss_after = _rss_bytes(server_pid)

    accepted = sum(1 for code in status_codes if code == 202)
    failure_rate = 1.0 - (accepted / max(1, len(status_codes)))

    sorted_latencies = sorted(latencies_ms) if latencies_ms else [0.0]
    p95_index = max(0, int(0.95 * len(sorted_latencies)) - 1)
    p95_latency_ms = sorted_latencies[p95_index]

    completion_consistency = len(terminal) / max(1, len(poll_subset))

    memory_delta_bytes = max(0, rss_after - rss_before)
    memory_growth_ratio = rss_after / max(1, rss_before)

    metrics = {
        "requests_total": len(status_codes),
        "accepted": accepted,
        "failure_rate": failure_rate,
        "latency_p95_ms": p95_latency_ms,
        "job_completion_consistency": completion_consistency,
        "health_failures": len(health_failures),
        "memory_before_bytes": rss_before,
        "memory_after_bytes": rss_after,
        "memory_delta_bytes": memory_delta_bytes,
        "memory_growth_ratio": memory_growth_ratio,
    }

    assert metrics["requests_total"] > 0
    assert metrics["health_failures"] == 0
    assert metrics["job_completion_consistency"] >= 0.90
    assert metrics["memory_delta_bytes"] < 300 * 1024 * 1024
    assert metrics["memory_growth_ratio"] < 1.35
