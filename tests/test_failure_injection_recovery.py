from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List, Optional, Set, Tuple

import httpx
import pytest

BASE_URL = os.environ.get("AETHELGARD_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("AETHELGARD_API_KEY", "dev-aethelgard-key-changeme")
SCENARIO = os.environ.get("AETHELGARD_STRESS_SCENARIO", "payment_latency_spike")

API_CONTAINER = os.environ.get("AETHELGARD_API_CONTAINER", "aethelgard-api")
REDIS_CONTAINER = os.environ.get("AETHELGARD_REDIS_CONTAINER", "aethelgard-redis")

TERMINAL_STATUSES: Set[str] = {"completed", "failed"}
VALID_LOAD_CODES: Set[int] = {202, 401, 429, 500, 503}


pytestmark = pytest.mark.asyncio


def _headers() -> Dict[str, str]:
    return {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }


async def _run_cmd(*args: str, timeout: float = 90.0) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "", "timeout"
    return proc.returncode, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")


async def _docker_restart(container_name: str, timeout: float = 120.0) -> None:
    code, out, err = await _run_cmd("docker", "restart", container_name, timeout=timeout)
    assert code == 0, f"docker restart failed for {container_name}: {out} {err}"


async def _wait_for_health(client: httpx.AsyncClient, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Optional[str] = None
    while time.monotonic() < deadline:
        try:
            resp = await client.get("/health")
            if resp.status_code == 200:
                return
            last_error = f"status={resp.status_code}"
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(1.0)
    raise AssertionError(f"health did not recover within {timeout_s}s: {last_error}")


async def _submit_pipeline_run(client: httpx.AsyncClient) -> Tuple[int, Optional[str]]:
    try:
        response = await client.post(
            "/pipeline/run",
            params={"scenario": SCENARIO},
            headers=_headers(),
            json={},
        )
        job_id = None
        if response.status_code == 202:
            payload = response.json()
            job_id = payload.get("job_id")
        return response.status_code, job_id
    except httpx.HTTPError:
        return 599, None


async def _active_load(
    client: httpx.AsyncClient,
    duration_s: float,
    concurrency: int,
    sleep_between_s: float,
) -> Tuple[List[int], List[str]]:
    stop_ts = time.monotonic() + duration_s
    status_codes: List[int] = []
    accepted_job_ids: List[str] = []

    async def _worker() -> None:
        while time.monotonic() < stop_ts:
            status, job_id = await _submit_pipeline_run(client)
            status_codes.append(status)
            if job_id:
                accepted_job_ids.append(job_id)
            await asyncio.sleep(sleep_between_s)

    workers = [asyncio.create_task(_worker()) for _ in range(concurrency)]
    await asyncio.gather(*workers)
    return status_codes, accepted_job_ids


async def _ensure_jobs_not_lost(
    client: httpx.AsyncClient,
    job_ids: List[str],
    timeout_s: float = 240.0,
) -> Dict[str, str]:
    deadline = time.monotonic() + timeout_s
    observed: Dict[str, str] = {}
    missing = set(job_ids)

    while time.monotonic() < deadline and missing:
        current_missing = list(missing)

        async def _check(job_id: str) -> Tuple[str, Optional[int], Optional[str]]:
            try:
                resp = await client.get(f"/pipeline/jobs/{job_id}", headers=_headers())
                if resp.status_code == 200:
                    status = str(resp.json().get("status", ""))
                    return job_id, 200, status
                return job_id, resp.status_code, None
            except Exception:
                return job_id, None, None

        results = await asyncio.gather(*[_check(job_id) for job_id in current_missing])
        for job_id, code, status in results:
            if code == 200 and status:
                observed[job_id] = status
                if status in TERMINAL_STATUSES:
                    missing.discard(job_id)
                else:
                    missing.discard(job_id)

        await asyncio.sleep(0.5)

    assert len(observed) == len(job_ids), f"job loss detected: expected={len(job_ids)} observed={len(observed)}"
    return observed


async def _assert_api_responses_valid_after_recovery(client: httpx.AsyncClient) -> None:
    health = await client.get("/health")
    assert health.status_code == 200

    ready = await client.get("/ready")
    assert ready.status_code == 200

    run_status, run_job = await _submit_pipeline_run(client)
    assert run_status in VALID_LOAD_CODES

    if run_status == 202 and run_job:
        lookup = await client.get(f"/pipeline/jobs/{run_job}", headers=_headers())
        assert lookup.status_code == 200


async def _redis_pause_loop(duration_s: float, pause_ms: int = 250) -> None:
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        await _run_cmd(
            "docker",
            "exec",
            REDIS_CONTAINER,
            "redis-cli",
            "CLIENT",
            "PAUSE",
            str(pause_ms),
            "ALL",
            timeout=15.0,
        )
        await asyncio.sleep(0.05)


async def _burst(client: httpx.AsyncClient, count: int) -> Tuple[List[int], List[str]]:
    results = await asyncio.gather(*[_submit_pipeline_run(client) for _ in range(count)])
    status_codes = [status for status, _ in results]
    job_ids = [job_id for _, job_id in results if job_id]
    return status_codes, job_ids


async def test_restart_api_during_active_load_recovery_no_job_loss() -> None:
    limits = httpx.Limits(max_connections=600, max_keepalive_connections=120)
    timeout = httpx.Timeout(25.0, connect=8.0)

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        await _wait_for_health(client, timeout_s=60)

        load_task = asyncio.create_task(_active_load(client, duration_s=30.0, concurrency=40, sleep_between_s=0.03))
        await asyncio.sleep(6.0)
        await _docker_restart(API_CONTAINER)
        await _wait_for_health(client, timeout_s=120)

        status_codes, job_ids = await load_task

        assert len(status_codes) > 0
        assert any(code == 202 for code in status_codes)

        sampled = job_ids[-120:] if len(job_ids) > 120 else job_ids
        observed = await _ensure_jobs_not_lost(client, sampled, timeout_s=240.0)
        assert len(observed) == len(sampled)

        await _assert_api_responses_valid_after_recovery(client)


async def test_restart_redis_during_active_load_recovery_no_job_loss() -> None:
    limits = httpx.Limits(max_connections=700, max_keepalive_connections=120)
    timeout = httpx.Timeout(25.0, connect=8.0)

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        await _wait_for_health(client, timeout_s=60)

        load_task = asyncio.create_task(_active_load(client, duration_s=35.0, concurrency=45, sleep_between_s=0.03))
        await asyncio.sleep(7.0)
        await _docker_restart(REDIS_CONTAINER)
        await asyncio.sleep(4.0)
        await _wait_for_health(client, timeout_s=120)

        status_codes, job_ids = await load_task

        assert len(status_codes) > 0
        assert any(code == 202 for code in status_codes)

        sampled = job_ids[-120:] if len(job_ids) > 120 else job_ids
        observed = await _ensure_jobs_not_lost(client, sampled, timeout_s=300.0)
        assert len(observed) == len(sampled)

        await _assert_api_responses_valid_after_recovery(client)


async def test_simulate_slow_redis_during_active_load_recovery() -> None:
    limits = httpx.Limits(max_connections=700, max_keepalive_connections=120)
    timeout = httpx.Timeout(25.0, connect=8.0)

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        await _wait_for_health(client, timeout_s=60)

        slow_task = asyncio.create_task(_redis_pause_loop(duration_s=30.0, pause_ms=300))
        load_task = asyncio.create_task(_active_load(client, duration_s=30.0, concurrency=35, sleep_between_s=0.035))

        status_codes, job_ids = await load_task
        await slow_task

        assert len(status_codes) > 0
        assert any(code in (202, 429, 500, 503) for code in status_codes)

        await _wait_for_health(client, timeout_s=120)

        sampled = job_ids[-100:] if len(job_ids) > 100 else job_ids
        observed = await _ensure_jobs_not_lost(client, sampled, timeout_s=300.0)
        assert len(observed) == len(sampled)

        await _assert_api_responses_valid_after_recovery(client)


async def test_burst_sustained_burst_pattern_recovery() -> None:
    limits = httpx.Limits(max_connections=900, max_keepalive_connections=150)
    timeout = httpx.Timeout(25.0, connect=8.0)

    all_codes: List[int] = []
    all_jobs: List[str] = []

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        await _wait_for_health(client, timeout_s=60)

        burst1_codes, burst1_jobs = await _burst(client, count=180)
        all_codes.extend(burst1_codes)
        all_jobs.extend(burst1_jobs)

        sustained_codes, sustained_jobs = await _active_load(
            client,
            duration_s=65.0,
            concurrency=30,
            sleep_between_s=0.04,
        )
        all_codes.extend(sustained_codes)
        all_jobs.extend(sustained_jobs)

        burst2_codes, burst2_jobs = await _burst(client, count=220)
        all_codes.extend(burst2_codes)
        all_jobs.extend(burst2_jobs)

        assert len(all_codes) > 0
        assert any(code == 202 for code in all_codes)

        sampled = all_jobs[-180:] if len(all_jobs) > 180 else all_jobs
        observed = await _ensure_jobs_not_lost(client, sampled, timeout_s=360.0)
        assert len(observed) == len(sampled)

        await _assert_api_responses_valid_after_recovery(client)
