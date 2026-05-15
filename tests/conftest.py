"""
Shared pytest fixtures for the Aethelgard test suite.

Fixture index
-------------
api_key_env        session, autouse, sync
    Sets AETHELGARD_API_KEY before any test runs so _load_valid_api_keys()
    always returns a known test key.  Restores the previous env state on
    session teardown.

mock_redis_client  function, sync
    AsyncMock of RedisStreamsClient / get_event_bus.  Use in unit tests that
    must not touch a real Redis instance.  Yields the mock so callers can
    assert on publish/subscribe calls or override return values.

http_client        function, async
    httpx.AsyncClient bound to the FastAPI app via ASGI transport (no real
    server).  X-API-Key is pre-set; VALID_API_KEYS is populated directly so
    authenticated endpoints work without running the full lifespan.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# 1. API key — session scope, autouse
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def api_key_env() -> None:
    """
    Guarantee AETHELGARD_API_KEY is set for the entire test session.

    _load_valid_api_keys() falls back to a hardcoded dev key when the env var
    is absent, which logs a noisy warning and makes auth state non-deterministic
    across CI environments.  This fixture sets a known test value up front.

    Session scope means the variable is set once before the first test module
    is imported and cleaned up after the last test in the session completes.
    """
    _prev = os.environ.get("AETHELGARD_API_KEY")
    os.environ["AETHELGARD_API_KEY"] = "test-key-aethelgard"
    yield
    if _prev is None:
        os.environ.pop("AETHELGARD_API_KEY", None)
    else:
        os.environ["AETHELGARD_API_KEY"] = _prev


# ---------------------------------------------------------------------------
# 2. Mock Redis — function scope
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """
    Patch RedisStreamsClient and get_event_bus so unit tests never require a
    live Redis instance.

    Both the source module (event_bus.redis_streams) and the re-export
    namespace (event_bus) are patched so callers that import from either
    location get the mock.  get_event_bus is async, so its patch uses
    new_callable=AsyncMock to ensure ``await get_event_bus()`` works.

    The yielded mock is the *instance* that callers will receive, pre-wired
    with sensible defaults.  Override individual methods inside your test as
    needed::

        async def test_publish_failure(mock_redis_client):
            mock_redis_client.publish.side_effect = RuntimeError("timeout")
            ...
    """
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.publish = AsyncMock(return_value="0-1")
    mock_client.subscribe = AsyncMock()

    with \
        patch("event_bus.redis_streams.RedisStreamsClient", return_value=mock_client), \
        patch(
            "event_bus.redis_streams.get_event_bus",
            new_callable=AsyncMock,
            return_value=mock_client,
        ), \
        patch(
            "event_bus.get_event_bus",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
        yield mock_client


# ---------------------------------------------------------------------------
# 3. Async HTTP client — function scope
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    httpx.AsyncClient wired to the FastAPI app via ASGITransport.

    No network socket is opened; requests traverse the full ASGI middleware
    stack but the lifespan (RAGEngine, orchestrator, Redis) is intentionally
    skipped — this targets route-level integration tests, not full end-to-end.

    VALID_API_KEYS is populated directly on the module so require_api_key()
    accepts the test key without needing the lifespan to run.  The previous
    key set is restored after each test to prevent cross-test pollution.

    The X-API-Key header is pre-set on the client so authenticated endpoints
    work without passing the header on every individual call::

        async def test_health(http_client):
            r = await http_client.get("/health")
            assert r.status_code == 200

        async def test_pipeline_run(http_client):
            r = await http_client.post("/pipeline/run", json={"scenario": "payment_latency_spike"})
            assert r.status_code in (200, 202)
    """
    import api as api_module

    _prev_keys = api_module.VALID_API_KEYS.copy()
    api_module.VALID_API_KEYS = {"test-key-aethelgard"}

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key-aethelgard"},
    ) as client:
        yield client

    api_module.VALID_API_KEYS = _prev_keys
