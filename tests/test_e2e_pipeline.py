"""
Integration test: end-to-end pipeline HTTP flow.

Exercises the full request/response path — POST /pipeline/run → poll
/pipeline/jobs/{job_id} — without requiring a live Redis instance, Docker
socket, or LLM API key.

The heavy pipeline logic (run_full_pipeline) is replaced by an AsyncMock so
the job transitions from pending → running → completed in milliseconds, while
every other layer (auth, middleware, route handlers, job registry, response
model serialisation) runs against real code.

Run just this file:
    pytest -q -m integration tests/test_e2e_pipeline.py

Skip in normal test runs (already configured in pyproject.toml markers):
    pytest -q -m "not integration"
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def integration_client(mocker) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    httpx.AsyncClient wired to the FastAPI app via ASGITransport.

    State injected onto app.state before each test:
      - orchestrator: real AgentOrchestrator with run_full_pipeline mocked
        so no LLM/Redis call is made.
      - simulator: real LogSimulator (pure Python, no I/O).

    VALID_API_KEYS is set to a known test value so auth passes without the
    lifespan loading keys from the environment.

    Cleanup removes the injected state so other test modules are not affected.
    """
    import api as api_module
    from agents.orchestrator import AgentOrchestrator
    from experiments.scenario_runner import LogSimulator

    # Build a real orchestrator so create_job / get_job / run_job work as-is.
    orchestrator = AgentOrchestrator()

    # Mock the heavy pipeline: run_full_pipeline returns None immediately.
    # run_job treats a None return as "no anomaly / deduplicated" and still
    # marks the job as "completed", which is the terminal state we assert on.
    mocker.patch.object(
        orchestrator,
        "run_full_pipeline",
        new_callable=AsyncMock,
        return_value=None,
    )

    # Inject state — no lifespan needed.
    api_module.app.state.orchestrator = orchestrator
    api_module.app.state.simulator = LogSimulator()

    _prev_keys = api_module.VALID_API_KEYS.copy()
    api_module.VALID_API_KEYS = {"test-key-aethelgard"}

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key-aethelgard"},
    ) as client:
        yield client

    # Restore previous state.
    api_module.VALID_API_KEYS = _prev_keys
    for attr in ("orchestrator", "simulator"):
        try:
            delattr(api_module.app.state, attr)
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_pipeline_run_returns_202_and_reaches_terminal_state(
    integration_client: httpx.AsyncClient,
) -> None:
    """
    Full happy-path flow:
      1. POST /pipeline/run → 202 with job_id
      2. Poll GET /pipeline/jobs/{job_id} until terminal status
      3. Terminal status is "completed" or "failed" (not "running")
      4. Response body includes started_at (ISO string) and duration_seconds
    """
    # ── Step 1: Submit job ────────────────────────────────────────────────
    response = await integration_client.post(
        "/pipeline/run",
        params={"scenario": "payment_latency_spike"},
    )

    assert response.status_code == 202, (
        f"Expected 202 Accepted; got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert "job_id" in body, f"job_id missing from 202 body: {body}"
    job_id: str = body["job_id"]
    assert job_id, "job_id must not be empty"
    assert body.get("status") == "pending", f"Initial status should be pending; got {body.get('status')}"
    assert body.get("scenario") == "payment_latency_spike"
    assert f"/pipeline/jobs/{job_id}" in body.get("poll_url", ""), "poll_url should reference job_id"

    # ── Steps 2–3: Poll until terminal ───────────────────────────────────
    terminal_statuses = {"completed", "failed"}
    deadline = time.monotonic() + 30.0
    last_data: dict = {}

    while time.monotonic() < deadline:
        poll = await integration_client.get(f"/pipeline/jobs/{job_id}")
        assert poll.status_code == 200, (
            f"Job status endpoint returned {poll.status_code}: {poll.text}"
        )
        last_data = poll.json()

        if last_data.get("status") in terminal_statuses:
            break

        # Intermediate statuses must be valid in-flight states.
        assert last_data.get("status") in {"pending", "running", "awaiting_approval"}, (
            f"Unexpected intermediate status: {last_data.get('status')}"
        )
        await asyncio.sleep(0.5)
    else:
        pytest.fail(
            f"Job {job_id} did not reach a terminal state within 30 s. "
            f"Last observed status: {last_data.get('status')!r}"
        )

    # ── Step 4: Terminal status assertion ─────────────────────────────────
    assert last_data["status"] in terminal_statuses, (
        f"Expected completed/failed; got {last_data['status']!r}"
    )

    # ── Step 5: Timing fields ─────────────────────────────────────────────
    assert last_data.get("started_at") is not None, (
        "started_at must be present in terminal job response"
    )
    # Must be a parseable ISO 8601 string
    from datetime import datetime
    datetime.fromisoformat(last_data["started_at"])  # raises ValueError if malformed

    assert last_data.get("duration_seconds") is not None, (
        "duration_seconds must be present in terminal job response"
    )
    assert last_data["duration_seconds"] >= 0, (
        f"duration_seconds must be non-negative; got {last_data['duration_seconds']}"
    )


@pytest.mark.integration
async def test_pipeline_run_rejects_unknown_scenario(
    integration_client: httpx.AsyncClient,
) -> None:
    """Unknown scenario names must return 400 before any job is created."""
    response = await integration_client.post(
        "/pipeline/run",
        params={"scenario": "this_scenario_does_not_exist_xyz"},
    )
    assert response.status_code == 400, (
        f"Expected 400 for unknown scenario; got {response.status_code}"
    )


@pytest.mark.integration
async def test_pipeline_run_requires_api_key(mocker) -> None:
    """Requests without X-API-Key must be rejected with 401."""
    import api as api_module
    from agents.orchestrator import AgentOrchestrator
    from experiments.scenario_runner import LogSimulator

    orchestrator = AgentOrchestrator()
    mocker.patch.object(orchestrator, "run_full_pipeline", new_callable=AsyncMock, return_value=None)
    api_module.app.state.orchestrator = orchestrator
    api_module.app.state.simulator = LogSimulator()

    _prev_keys = api_module.VALID_API_KEYS.copy()
    api_module.VALID_API_KEYS = {"test-key-aethelgard"}

    transport = httpx.ASGITransport(app=api_module.app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            # No X-API-Key header
        ) as client:
            response = await client.post(
                "/pipeline/run",
                params={"scenario": "payment_latency_spike"},
            )
        assert response.status_code == 401, (
            f"Expected 401 for missing API key; got {response.status_code}"
        )
    finally:
        api_module.VALID_API_KEYS = _prev_keys
        for attr in ("orchestrator", "simulator"):
            try:
                delattr(api_module.app.state, attr)
            except AttributeError:
                pass


@pytest.mark.integration
async def test_get_job_404_for_missing_job(
    integration_client: httpx.AsyncClient,
) -> None:
    """Polling a non-existent job_id must return 404."""
    response = await integration_client.get("/pipeline/jobs/job-nonexistent000")
    assert response.status_code == 404
