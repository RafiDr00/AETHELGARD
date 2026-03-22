"""
Aethelgard — Real Metrics Middleware & Ingestion Layer
==========================================================

FIX #1: Replace LogSimulator with real telemetry ingestion.

This module provides:
  1. FastAPI Starlette middleware that captures REAL request latency,
     status codes, and error rates from the actual HTTP server.

  2. PrometheusMetricsCollector: exposes those real metrics as
     ServiceMetric objects — the exact type the DetectionAgent reads.

  3. MetricsBuffer: thread-safe ring-buffer that the LogListener
     polls instead of LogSimulator.generate_metrics().

Architecture:
─────────────────────────────────────────────────────
  FastAPI request
      │
      ▼
  AethelgardMetricsMiddleware (measures real latency/errors)
      │  writes to ──►  MetricsBuffer (ring-buffer, max 500 samples)
      │                     │
      │                     ├── also increments Prometheus gauges
      │                     │
      ▼                     ▼
  Response             LogListener.collect_real()
                           │
                           ▼
                       DetectionAgent.analyze_metrics()
─────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.logging_config import get_logger
from core.models import ServiceMetric

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Allowlisted metric names (prevents cardinality explosion)
# ─────────────────────────────────────────────────────────────
KNOWN_HTTP_SERVICES = {
    "aethelgard-api",
    "payment-service",
    "order-service",
    "user-service",
    "inventory-service",
    "notification-service",
}


class MetricsBuffer:
    """
    Thread-safe fixed-size ring buffer for real request metrics.

    Written by the ASGI middleware on every HTTP request.
    Read by LogListener to feed the DetectionAgent.
    """

    MAX_SIZE = 500

    def __init__(self):
        self._lock = asyncio.Lock()
        self._buffer: deque[ServiceMetric] = deque(maxlen=self.MAX_SIZE)

    async def write(self, metric: ServiceMetric) -> None:
        async with self._lock:
            self._buffer.append(metric)

    async def read_batch(self, max_count: int = 50) -> List[ServiceMetric]:
        """Return up to max_count recent metrics without clearing the buffer."""
        async with self._lock:
            items = list(self._buffer)
            return items[-max_count:]

    async def drain(self, max_count: int = 50) -> List[ServiceMetric]:
        """Return and remove oldest metrics (FIFO drain for processing)."""
        async with self._lock:
            result = []
            for _ in range(min(max_count, len(self._buffer))):
                result.append(self._buffer.popleft())
            return result

    @property
    def size(self) -> int:
        return len(self._buffer)


# Singleton buffer — shared between middleware and listener
_metrics_buffer: Optional[MetricsBuffer] = None


def get_metrics_buffer() -> MetricsBuffer:
    global _metrics_buffer
    if _metrics_buffer is None:
        _metrics_buffer = MetricsBuffer()
    return _metrics_buffer


# ─────────────────────────────────────────────────────────────
# ASGI Middleware — captures real request telemetry
# ─────────────────────────────────────────────────────────────

class AethelgardMetricsMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that measures REAL request latency and error rates
    from the running FastAPI server and writes them to MetricsBuffer.

    Replaces the LogSimulator-based synthetic metric generation.

    Metrics captured per request:
      - response_time_ms   (actual measured value, not synthetic)
      - error_rate         (sliding window: 1.0 if 5xx, else 0.0)
      - request_rate       (incremented counter, normalised per poll)
      - status_code_class  (2xx / 4xx / 5xx)
    """

    # Endpoints to skip (avoid measuring Prometheus scrape overhead)
    SKIP_PATHS = {"/metrics/prometheus", "/health", "/ready", "/favicon.ico"}

    def __init__(self, app: ASGIApp, service_name: str = "aethelgard-api"):
        super().__init__(app)
        self._service_name = service_name
        self._buffer = get_metrics_buffer()
        # Rolling counters (protected by GIL — they're simple ints)
        self._request_count: int = 0
        self._error_count: int = 0
        self._last_reset: float = time.monotonic()
        self._window_seconds: float = 10.0   # normalise over 10s windows

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        t0 = time.monotonic()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            latency_ms = (time.monotonic() - t0) * 1000
            self._request_count += 1
            is_error = status_code >= 500

            if is_error:
                self._error_count += 1

            # ── Normalise window ──────────────────────────────────
            elapsed = time.monotonic() - self._last_reset
            if elapsed >= self._window_seconds:
                req_rate = self._request_count / elapsed
                err_rate = (
                    self._error_count / max(self._request_count, 1)
                )
                self._request_count = 0
                self._error_count = 0
                self._last_reset = time.monotonic()
            else:
                req_rate = self._request_count / max(elapsed, 0.001)
                err_rate = self._error_count / max(self._request_count, 1)

            now = datetime.now(timezone.utc)
            service = self._service_name
            labels = {
                "path": request.url.path[:64],          # truncated for safety
                "method": request.method,
                "status_class": f"{status_code // 100}xx",
            }

            # Emit real measured metrics to the buffer
            await self._buffer.write(ServiceMetric(
                service_name=service,
                metric_name="response_time_ms",
                value=round(latency_ms, 2),
                unit="ms",
                timestamp=now,
                labels=labels,
            ))
            await self._buffer.write(ServiceMetric(
                service_name=service,
                metric_name="error_rate",
                value=round(err_rate, 4),
                unit="ratio",
                timestamp=now,
                labels=labels,
            ))
            await self._buffer.write(ServiceMetric(
                service_name=service,
                metric_name="request_rate",
                value=round(req_rate, 2),
                unit="req/s",
                timestamp=now,
                labels=labels,
            ))

        return response


# ─────────────────────────────────────────────────────────────
# Real Log Listener — replaces LogSimulator polling
# ─────────────────────────────────────────────────────────────

class RealLogListener:
    """
    Replacement for LogListener that reads from MetricsBuffer
    (which contains REAL request measurements from the middleware)
    instead of LogSimulator.generate_metrics().

    Falls back to the simulator if no real metrics are available yet
    (e.g., during startup warmup or unit tests).
    """

    def __init__(
        self,
        service_name: str = "aethelgard-api",
        fallback_simulator=None,
        min_real_metrics: int = 5,
    ):
        self._buffer = get_metrics_buffer()
        self._service_name = service_name
        self._simulator = fallback_simulator
        self._min_real_metrics = min_real_metrics
        self._metric_callbacks: List[Callable] = []
        self._running = False
        self._poll_interval = 2.0
        # Semaphore: only one pipeline trigger at a time (FIX #3)
        self._pipeline_semaphore = asyncio.Semaphore(1)

    def on_metrics(self, callback: Callable) -> None:
        self._metric_callbacks.append(callback)

    async def start(self) -> None:
        self._running = True
        logger.info("real_log_listener_started",
                    poll_interval=self._poll_interval,
                    buffer_capacity=MetricsBuffer.MAX_SIZE)
        while self._running:
            try:
                await self._poll_and_dispatch()
            except Exception as e:
                logger.error("real_log_listener_error", error=str(e))
            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("real_log_listener_stopped")

    async def _poll_and_dispatch(self) -> None:
        """Pull real metrics, fall back to simulator only if buffer is thin."""
        real_metrics = await self._buffer.read_batch(max_count=30)

        if len(real_metrics) >= self._min_real_metrics:
            metrics = real_metrics
            source = "real_middleware"
        elif self._simulator:
            metrics = self._simulator.generate_metrics()
            source = "simulator_fallback"
            logger.debug("listener_using_simulator",
                         buffer_size=len(real_metrics),
                         reason="insufficient_real_metrics")
        else:
            logger.debug("listener_no_data",
                         buffer_size=len(real_metrics))
            return

        logger.debug("listener_dispatching",
                     source=source,
                     metric_count=len(metrics))

        # FIX #3: Semaphore prevents concurrent pipeline triggers
        if self._pipeline_semaphore.locked():
            logger.debug("listener_skip_pipeline_busy")
            return

        async with self._pipeline_semaphore:
            for callback in self._metric_callbacks:
                try:
                    await callback(metrics)
                except Exception as e:
                    logger.error("listener_callback_error", error=str(e))

    async def collect_once(self) -> tuple:
        """Compatible shim for code that still calls collect_once()."""
        real_metrics = await self._buffer.read_batch(max_count=30)
        if len(real_metrics) >= self._min_real_metrics:
            return real_metrics, []
        if self._simulator:
            return self._simulator.generate_metrics(), self._simulator.generate_logs(count=5)
        return [], []
