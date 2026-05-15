import asyncio
import logging
import time
import random
import os
import psutil
from dataclasses import dataclass, field
from typing import Optional
from fastapi import FastAPI, Response, Request, HTTPException, Header, Depends
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)

app = FastAPI(title="Payment Service (Aethelgard Target)")

# --- Prometheus Metrics ---
REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"]
)
MEMORY_USAGE_GAUGE = Gauge("service_memory_usage_bytes", "Service memory usage in bytes")
DB_CONNECTIONS = Gauge("db_connection_pool_active", "Active DB connections")


# --- Fault State Container ---

@dataclass
class FaultState:
    """
    Holds all mutable fault-injection state for one process.

    IMPORTANT — single-worker limitation:
      Each uvicorn/gunicorn worker process holds its own FaultState in memory.
      In a multi-worker deployment, a POST to /fault/latency may hit worker A
      while the next /payment request is served by worker B, which still has
      latency_enabled=False.  Fault injection will appear inconsistent across
      workers.

    TODO: Replace with a Redis-backed implementation so all workers share a
      single source of truth.  Suggested approach:
        - Store FaultState fields in a Redis hash (HSET payment:fault latency 1).
        - Middleware reads state with a cached GET + short TTL (e.g. 1 s) to
          avoid a Redis round-trip on every request.
        - Fault endpoints write through to Redis atomically.
    """
    latency_enabled: bool = False
    error_rate: float = 0.0
    leaked_bytes: int = 0


@app.on_event("startup")
async def startup() -> None:
    app.state.fault_state = FaultState()
    app.state.leak_lock = asyncio.Lock()
    app.state.leak_data: list = []   # holds allocations; grows intentionally
    app.state.fault_key = os.environ.get("PAYMENT_SERVICE_FAULT_KEY", "")
    app.state.app_env = os.environ.get("APP_ENV", "development")
    if not app.state.fault_key:
        _mode = (
            "BLOCKED (production)" if app.state.app_env == "production"
            else "unprotected — set PAYMENT_SERVICE_FAULT_KEY in non-production"
        )
        logger.warning("PAYMENT_SERVICE_FAULT_KEY not set; fault endpoints are %s", _mode)


async def require_fault_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
) -> None:
    """
    Dependency: guard fault injection endpoints with a pre-shared key.

    Behaviour matrix:
      PAYMENT_SERVICE_FAULT_KEY set   → X-API-Key must match; 401 otherwise.
      key not set + APP_ENV=production → always 401 (no unauthenticated fault
                                         injection allowed in production).
      key not set + non-production    → allow (warning logged at startup).
    """
    fault_key: str = request.app.state.fault_key
    app_env: str = request.app.state.app_env
    if fault_key:
        if x_api_key != fault_key:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing X-API-Key for fault injection",
            )
    elif app_env == "production":
        raise HTTPException(
            status_code=401,
            detail="Fault injection requires PAYMENT_SERVICE_FAULT_KEY in production",
        )


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start_time = time.monotonic()
    fault: FaultState = request.app.state.fault_state

    # Simulate DB connection pool saturation under latency fault
    DB_CONNECTIONS.set(random.randint(10, 85 if not fault.latency_enabled else 98))

    # Inject latency
    if fault.latency_enabled:
        await asyncio.sleep(random.uniform(1.5, 3.0))

    # Inject errors
    if random.random() < fault.error_rate:
        response = Response(content="Internal Server Error", status_code=500)
    else:
        response = await call_next(request)

    duration = time.monotonic() - start_time
    status_code = response.status_code
    REQUESTS_TOTAL.labels(method=request.method, endpoint=request.url.path, http_status=status_code).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=request.url.path).observe(duration)

    return response


@app.get("/payment")
async def process_payment():
    await asyncio.sleep(random.uniform(0.01, 0.1))
    return {"status": "success", "transaction_id": random.randint(1000, 9999)}


@app.get("/metrics")
async def metrics():
    process = psutil.Process(os.getpid())
    MEMORY_USAGE_GAUGE.set(process.memory_info().rss)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- Fault Injection Endpoints ---

@app.post("/fault/latency")
async def toggle_latency(
    request: Request,
    enabled: bool,
    _: None = Depends(require_fault_key),
):
    request.app.state.fault_state.latency_enabled = enabled
    return {"status": "ok", "fault_latency": enabled}


@app.post("/fault/error")
async def set_error_rate(
    request: Request,
    rate: float,
    _: None = Depends(require_fault_key),
):
    request.app.state.fault_state.error_rate = rate
    return {"status": "ok", "fault_error_rate": rate}


@app.post("/fault/memory-leak")
async def trigger_memory_leak(
    request: Request,
    bytes: int = 1024 * 1024 * 10,  # 10 MB
    _: None = Depends(require_fault_key),
):
    async with request.app.state.leak_lock:
        request.app.state.leak_data.append(" " * bytes)
        request.app.state.fault_state.leaked_bytes += bytes
    return {"status": "ok", "leaked_bytes": request.app.state.fault_state.leaked_bytes}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
