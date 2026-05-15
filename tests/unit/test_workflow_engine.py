"""
Unit tests for WorkflowEngine._execute_pipeline resource-cleanup guarantees.

These tests verify the lock/fingerprint release contract without requiring
a running Redis instance or real agent implementations.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.workflow_engine import WorkflowEngine
from domain.job import JobStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> WorkflowEngine:
    """WorkflowEngine wired with AsyncMock dependencies."""
    return WorkflowEngine(
        job_store=AsyncMock(),
        fingerprint_store=AsyncMock(),
        lock_manager=AsyncMock(),
        agent_coordinator=AsyncMock(),
        metrics_publisher=AsyncMock(),
    )


def _make_mock_job(scenario: str = "payment_latency_spike") -> MagicMock:
    job = MagicMock()
    job.id = "test-job-1"
    job.scenario = scenario
    job.status = JobStatus.PENDING
    return job


@asynccontextmanager
async def _noop_span(*args, **kwargs):
    """Drop-in replacement for pipeline_span that does nothing."""
    yield


# ---------------------------------------------------------------------------
# Lock-release guarantee
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lock_released_on_agent_exception():
    """
    The distributed lock must be released even when an agent raises
    mid-pipeline.  Without this guarantee a stuck lock blocks the scenario
    for up to the full Redis key TTL (30 s by default).
    """
    engine = _make_engine()
    job = _make_mock_job()
    lock_token = "deadbeef"
    fingerprint = "scenario:payment_latency_spike:99999"

    engine.job_store.get_job.return_value = job
    engine.coordinator.run_detection.side_effect = RuntimeError("simulated agent crash")

    with \
            patch("application.workflow_engine.pipeline_span", _noop_span), \
            patch("application.workflow_engine.require_valid_transition"):
        await engine._execute_pipeline(job.id, None, fingerprint, lock_token)

    engine.lock_manager.release.assert_called_once_with(job.scenario, lock_token)


@pytest.mark.asyncio
async def test_lock_released_on_success():
    """Lock is released even when the pipeline completes normally."""
    engine = _make_engine()
    job = _make_mock_job()
    lock_token = "deadbeef"
    fingerprint = "scenario:payment_latency_spike:99999"

    engine.job_store.get_job.return_value = job
    # No anomaly → early-return success path inside the try block.
    engine.coordinator.run_detection.return_value = {"anomaly": None}

    with \
            patch("application.workflow_engine.pipeline_span", _noop_span), \
            patch("application.workflow_engine.require_valid_transition"):
        await engine._execute_pipeline(job.id, None, fingerprint, lock_token)

    engine.lock_manager.release.assert_called_once_with(job.scenario, lock_token)


# ---------------------------------------------------------------------------
# Fingerprint-release semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fingerprint_released_on_failure():
    """
    Fingerprint must be released on pipeline failure so the same scenario
    can be re-triggered within the TTL window after an error — otherwise the
    system silently suppresses the retry as a duplicate.
    """
    engine = _make_engine()
    job = _make_mock_job()
    lock_token = "deadbeef"
    fingerprint = "scenario:payment_latency_spike:99999"

    engine.job_store.get_job.return_value = job
    engine.coordinator.run_detection.side_effect = RuntimeError("simulated agent crash")

    with \
            patch("application.workflow_engine.pipeline_span", _noop_span), \
            patch("application.workflow_engine.require_valid_transition"):
        await engine._execute_pipeline(job.id, None, fingerprint, lock_token)

    engine.fingerprint_store.release_fingerprint.assert_called_once_with(fingerprint)


@pytest.mark.asyncio
async def test_fingerprint_not_released_on_success():
    """
    On a successful run the fingerprint is intentionally left in Redis to
    expire via TTL.  Releasing it immediately would allow a duplicate trigger
    within the same dedup window, defeating the fingerprint guard entirely.
    """
    engine = _make_engine()
    job = _make_mock_job()
    lock_token = "deadbeef"
    fingerprint = "scenario:payment_latency_spike:99999"

    engine.job_store.get_job.return_value = job
    engine.coordinator.run_detection.return_value = {"anomaly": None}

    with \
            patch("application.workflow_engine.pipeline_span", _noop_span), \
            patch("application.workflow_engine.require_valid_transition"):
        await engine._execute_pipeline(job.id, None, fingerprint, lock_token)

    engine.fingerprint_store.release_fingerprint.assert_not_called()
