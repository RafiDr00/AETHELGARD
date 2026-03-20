from __future__ import annotations

import asyncio
import os
import random
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
NON_TERMINAL_STATUSES: Set[str] = {"pending", "running", "awaiting_approval"}


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
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "", "timeout"
    return proc.returncode, out_b.decode(errors="replace"), err_b.decode(errors="replace")


async def _docker_restart(container_name: str) -> None:
    code, out, err = await _run_cmd("docker", "restart", container_name, timeout=120.0)
    assert code == 0, f"docker restart failed for {container_name}: {out} {err}"


async def _redis_pause_all(ms: int) -> None:
    await _run_cmd(
        "docker",
        "exec",
        REDIS_CONTAINER,
        "redis-cli",
        "CLIENT",
        "PAUSE",
        str(ms),
        "ALL",
        timeout=20.0,
    )


async def _wait_healthy(client: httpx.AsyncClient, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = await client.get("/health")
            if r.status_code == 200:
                return
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.2, 0.8))
    raise AssertionError("server did not recover health in time")


async def _submit_run(client: httpx.AsyncClient) -> Tuple[int, Optional[str]]:
    try:
        response = await client.post(
            "/pipeline/run",
            params={"scenario": SCENARIO},
            headers=_headers(),
            json={},
        )
        if response.status_code == 202:
            return 202, response.json().get("job_id")
        return response.status_code, None
    except httpx.HTTPError:
        return 599, None


async def _burst_submit(client: httpx.AsyncClient, n: int) -> Tuple[List[int], List[str]]:
    results = await asyncio.gather(*[_submit_run(client) for _ in range(n)], return_exceptions=True)
    status_codes: List[int] = []
    job_ids: List[str] = []
    for item in results:
        if isinstance(item, Exception):
            status_codes.append(599)
            continue
        code, job_id = item
        status_codes.append(code)
        if job_id:
            job_ids.append(job_id)
    return status_codes, job_ids


async def _poll_terminal_or_timeout(
    client: httpx.AsyncClient,
    job_ids: List[str],
    per_job_timeout_s: float,
) -> Tuple[Dict[str, str], Set[str]]:
    created_at: Dict[str, float] = {job_id: time.monotonic() for job_id in job_ids}
    terminal: Dict[str, str] = {}
    timed_out: Set[str] = set()

    while len(terminal) + len(timed_out) < len(job_ids):
        pending = [
            jid for jid in job_ids
            if jid not in terminal and jid not in timed_out
        ]
        if not pending:
            break

        async def _check(job_id: str) -> Tuple[str, Optional[str]]:
            try:
                resp = await client.get(f"/pipeline/jobs/{job_id}", headers=_headers())
                if resp.status_code == 200:
                    status = str(resp.json().get("status", ""))
                    return job_id, status
                return job_id, None
            except Exception:
                return job_id, None

        checks = await asyncio.gather(*[_check(jid) for jid in pending])
        now = time.monotonic()

        for job_id, status in checks:
            if status in TERMINAL_STATUSES:
                terminal[job_id] = status
                continue
            if status in NON_TERMINAL_STATUSES or status is None:
                if now - created_at[job_id] > per_job_timeout_s:
                    timed_out.add(job_id)

        await asyncio.sleep(random.uniform(0.25, 0.9))

    return terminal, timed_out


@pytest.mark.asyncio
async def test_chaos_randomized_combined_failures_during_load():
    rng = random.Random()
    rng.seed(int(time.time()))

    limits = httpx.Limits(max_connections=1200, max_keepalive_connections=200)
    timeout = httpx.Timeout(25.0, connect=8.0)

    all_status_codes: List[int] = []
    all_job_ids: List[str] = []

    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=timeout) as client:
        await _wait_healthy(client, timeout_s=90.0)

        stop_ts = time.monotonic() + 80.0

        # Combined failure block: Redis slow + API restart + burst load
        async def combined_failure_block() -> Tuple[List[int], List[str]]:
            await asyncio.sleep(rng.uniform(2.5, 8.5))
            pause_task = asyncio.create_task(_redis_pause_all(rng.randint(600, 1400)))
            restart_task = asyncio.create_task(_docker_restart(API_CONTAINER))
            burst_codes, burst_jobs = await _burst_submit(client, rng.randint(120, 220))
            await asyncio.gather(pause_task, restart_task)
            await _wait_healthy(client, timeout_s=120.0)
            return burst_codes, burst_jobs

        # Randomized kill/restart and Redis slow actions during load
        async def chaos_actor() -> None:
            actions = ["restart_api", "restart_redis", "slow_redis", "burst"]
            while time.monotonic() < stop_ts:
                action = rng.choice(actions)
                if action == "restart_api":
                    await _docker_restart(API_CONTAINER)
                    await _wait_healthy(client, timeout_s=120.0)
                elif action == "restart_redis":
                    await _docker_restart(REDIS_CONTAINER)
                    await asyncio.sleep(rng.uniform(0.4, 1.4))
                elif action == "slow_redis":
                    await _redis_pause_all(rng.randint(200, 900))
                else:
                    codes, jobs = await _burst_submit(client, rng.randint(40, 100))
                    all_status_codes.extend(codes)
                    all_job_ids.extend(jobs)
                await asyncio.sleep(rng.uniform(0.6, 3.5))

        async def load_worker() -> None:
            while time.monotonic() < stop_ts:
                code, job_id = await _submit_run(client)
                all_status_codes.append(code)
                if job_id:
                    all_job_ids.append(job_id)
                await asyncio.sleep(rng.uniform(0.01, 0.09))

        combined_task = asyncio.create_task(combined_failure_block())
        chaos_task = asyncio.create_task(chaos_actor())
        workers = [asyncio.create_task(load_worker()) for _ in range(70)]

        await asyncio.gather(*workers)
        await chaos_task
        combined_codes, combined_jobs = await combined_task
        all_status_codes.extend(combined_codes)
        all_job_ids.extend(combined_jobs)

        await _wait_healthy(client, timeout_s=120.0)

        sampled_job_ids = all_job_ids[-300:] if len(all_job_ids) > 300 else all_job_ids
        terminal, timed_out = await _poll_terminal_or_timeout(
            client,
            sampled_job_ids,
            per_job_timeout_s=240.0,
        )

        assert len(timed_out) == 0

        duplicates = len(all_job_ids) - len(set(all_job_ids))
        assert duplicates == 0

        total_requests = len(all_status_codes)
        error_count = sum(1 for code in all_status_codes if code in (500, 502, 503, 504, 599))
        error_rate = error_count / max(1, total_requests)

        assert total_requests > 0
        assert error_rate < 0.20

        # API returns valid responses after recovery
        health = await client.get("/health")
        assert health.status_code == 200

        readiness = await client.get("/ready")
        assert readiness.status_code == 200

        code, job_id = await _submit_run(client)
        assert code in {202, 429, 503}
        if code == 202 and job_id:
            lookup = await client.get(f"/pipeline/jobs/{job_id}", headers=_headers())
            assert lookup.status_code == 200

        # No sampled job remains in non-terminal state after timeout window
        assert len(terminal) == len(sampled_job_ids)
