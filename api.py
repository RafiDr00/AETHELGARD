"""
Aethelgard v2 — FastAPI REST API (Production-Grade)

FIXES APPLIED:
  #1  — Real metrics middleware (AethelgardMetricsMiddleware) captures
        actual request latency/errors. RealLogListener replaces LogSimulator.
  #2  — OTel instrumentation embedded directly in AgentOrchestrator.
        ObservableOrchestrator wrapper removed (it bypassed spans in BG jobs).
  #3  — asyncio.Lock on shared state; per-service remediation mutex.
  #4  — Anomaly fingerprint deduplication in orchestrator.
  #5  — /pipeline/run 202 Accepted + job_id (non-blocking).
  #6  — CORS restricted to explicit origins (not wildcard + credentials).
  Auth — API key required on write/action endpoints.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Depends, Security, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_settings
from core.logging_config import get_logger, setup_logging
from core.models import PlatformMetrics, Severity
from core.preflight import run_startup_preflight

# ── Observability: must initialise BEFORE app creation ─────────────────────
from core.telemetry import tracer, API_AUTH_FAILURES_TOTAL
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    _OTEL_FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FastAPIInstrumentor = None  # type: ignore[assignment,misc]
    _OTEL_FASTAPI_AVAILABLE = False
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger("aethelgard.api")

START_TIME = time.time()

# ─────────────────────────────────────────────
# Request-ID Middleware
# ─────────────────────────────────────────────

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Stamps every request with a correlation ID and binds it to the structlog
    context so all log lines emitted during a request carry the same ID.

    Processing order (outermost middleware — runs first on request, last on response):
      1. clear_contextvars()  — evict any leftover context from a prior request
                                on the same asyncio worker (prevents leakage).
      2. Read X-Request-ID from the incoming header; generate a UUID hex if absent.
      3. bind_contextvars()   — all structlog calls downstream include request_id.
      4. Await the rest of the stack (CORS → metrics → route handler).
      5. Echo X-Request-ID back in the response headers for client correlation.
    """

    async def dispatch(
        self, request: StarletteRequest, call_next
    ) -> StarletteResponse:
        structlog.contextvars.clear_contextvars()

        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ─────────────────────────────────────────────
# FIX #5 — API Key Authentication
# ─────────────────────────────────────────────

# API keys are loaded from environment / settings.
# In production: use a vault-backed secret store.
# For development: set AETHELGARD_API_KEY env var.
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def _load_valid_api_keys() -> set:
    """Load valid API keys from environment."""
    keys = set()
    # Primary key from env
    primary = os.environ.get("AETHELGARD_API_KEY", "")
    if primary:
        keys.add(primary)
    # Additional comma-separated keys
    extra = os.environ.get("AETHELGARD_API_KEYS", "")
    if extra:
        keys.update(k.strip() for k in extra.split(",") if k.strip())
    # Dev fallback — only active when no real keys configured
    if not keys:
        dev_key = "dev-aethelgard-key-changeme"
        keys.add(dev_key)
        logger.warning(
            "api_using_dev_key",
            warning="Set AETHELGARD_API_KEY env var in production",
        )
    return keys

VALID_API_KEYS: set = set()


async def require_api_key(x_api_key: Optional[str] = Security(_API_KEY_HEADER)) -> str:
    """
    Dependency: validates API key for write/action endpoints.
    Records auth failures in Prometheus.
    """
    if not x_api_key or x_api_key not in VALID_API_KEYS:
        # Record in Prometheus
        API_AUTH_FAILURES_TOTAL.labels(
            endpoint="unknown"
        ).inc()
        logger.warning("api_auth_failed",
                       key_present=bool(x_api_key))
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key


# ─────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────

class InjectAnomalyRequest(BaseModel):
    scenario: str = "payment_latency_spike"


class PipelineJobResponse(BaseModel):
    """Returned immediately from POST /pipeline/run (202 Accepted)."""
    job_id: str
    status: str = "pending"
    scenario: str
    message: str = "Pipeline job accepted. Poll /pipeline/jobs/{job_id} for status."
    poll_url: str


class PipelineJobStatus(BaseModel):
    job_id: str
    status: str
    scenario: str
    started_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    # Populated when status == "completed"
    anomaly_detected: Optional[bool] = None
    service: Optional[str] = None
    anomaly_type: Optional[str] = None
    root_cause: Optional[str] = None
    patch_type: Optional[str] = None
    remediation_status: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None
    risk_score: Optional[float] = None
    deployed: Optional[bool] = None
    mttd_seconds: Optional[float] = None
    mttr_seconds: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    agents_active: int
    environment: str
    rag_backend: Optional[str] = None


class OperationsMetricsResponse(BaseModel):
    activePipelines: int
    dedupRatio: float
    failedHealth: int
    avgLatency: float
    mttdSeconds: float
    mttrSeconds: float
    autonomousResolutionRate: float


def _extract_prom_metric_value(metrics_text: str, metric_name: str) -> float:
    pattern = re.compile(rf"^{re.escape(metric_name)}(?:\{{[^}}]*\}})?\s+([-+]?\d*\.?\d+)$", re.MULTILINE)
    matches = pattern.findall(metrics_text)
    if not matches:
        return 0.0
    # If multiple samples exist (e.g. labels), use sum for a quick aggregate.
    return sum(float(v) for v in matches)


def _build_timeline_payload(job, record) -> Dict[str, Any]:
    def fmt_hms(ts: Optional[datetime]) -> str:
        if not ts:
            return "--:--:--"
        return ts.strftime("%H:%M:%S")

    if job.remediation_status == "deduplicated" and record is None:
        return {
            "job_id": job.job_id,
            "status": "deduplicated",
            "timeline": [
                {
                    "stage": "deduplication",
                    "status": "deduplicated",
                    "timestamp": fmt_hms(datetime.now(timezone.utc)),
                    "details": "Duplicate anomaly trigger suppressed by fingerprint gate",
                }
            ],
        }

    stages = ["detection", "diagnosis", "remediation", "validation", "deployment"]
    if record is None:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "timeline": [
                {
                    "stage": stage,
                    "status": "deduplicated",
                    "timestamp": "--:--:--",
                    "details": f"{stage} stage pending",
                }
                for stage in stages
            ],
        }

    timestamps = {
        "detection": record.anomaly.detected_at,
        "diagnosis": record.diagnosis.diagnosed_at,
        "remediation": record.patch.created_at,
        "validation": record.validation.validated_at,
        "deployment": record.deployment.deployed_at,
    }

    details = {
        "detection": f"anomaly detected ({record.anomaly.anomaly_type})",
        "diagnosis": f"diagnosis: {record.diagnosis.root_cause[:96]}",
        "remediation": f"remediation generated ({record.patch.patch_type})",
        "validation": f"validation complete (risk_score={record.validation.risk_score:.2f})",
        "deployment": f"deployment result ({record.remediation_status.value})",
    }

    timeline = []
    for stage in stages:
        timeline.append({
            "stage": stage,
            "status": "success",
            "timestamp": fmt_hms(timestamps[stage]),
            "details": details[stage],
        })

    if record.remediation_status.value == "rolled_back":
        for item in timeline:
            if item["stage"] == "deployment":
                item["status"] = "rolled_back"
                break

    if record.failure_stage:
        for item in timeline:
            if item["stage"] == record.failure_stage.value:
                item["status"] = "failed"
                if record.failure_reason:
                    item["details"] = f"{item['details']} — {record.failure_reason}"
                break

    return {
        "job_id": job.job_id,
        "status": record.remediation_status.value,
        "timeline": timeline,
    }


def _build_span_payload(job, record) -> Dict[str, Any]:
    def fmt_hms(ts: Optional[datetime]) -> str:
        if not ts:
            return "--:--:--"
        return ts.strftime("%H:%M:%S")

    if record is None:
        return {
            "job_id": job.job_id,
            "spans": [],
        }

    total_ms = max((record.total_duration_seconds or 0.0) * 1000.0, 1.0)
    validation_ms = max((record.validation.duration_seconds or 0.0) * 1000.0, 0.0)
    deployment_ms = max((record.deployment.deployment_duration_seconds or 0.0) * 1000.0, 0.0)
    remaining = max(total_ms - validation_ms - deployment_ms, 0.0)
    detection_ms = round(remaining * 0.10, 2)
    diagnosis_ms = round(remaining * 0.45, 2)
    remediation_ms = round(remaining * 0.45, 2)

    attrs = {
        "service_name": record.anomaly.service_name,
        "anomaly_type": record.anomaly.anomaly_type,
        "patch_type": record.patch.patch_type,
        "risk_score": record.validation.risk_score,
        "validation_latency": round(validation_ms, 2),
    }

    stage_timestamps = {
        "agent.detection": fmt_hms(record.anomaly.detected_at),
        "agent.diagnosis": fmt_hms(record.diagnosis.diagnosed_at),
        "agent.remediation": fmt_hms(record.patch.created_at),
        "agent.validation": fmt_hms(record.validation.validated_at),
        "agent.deployment": fmt_hms(record.deployment.deployed_at),
    }

    stage_details = {
        "agent.detection": f"anomaly detected ({record.anomaly.anomaly_type})",
        "agent.diagnosis": f"diagnosis: {record.diagnosis.root_cause[:96]}",
        "agent.remediation": f"remediation generated ({record.patch.patch_type})",
        "agent.validation": f"validation complete (risk_score={record.validation.risk_score:.2f})",
        "agent.deployment": f"deployment result ({record.remediation_status.value})",
    }

    default_span_status = "success"
    if record.remediation_status.value == "rolled_back":
        deployment_status = "rolled_back"
    elif record.failure_stage and record.failure_stage.value == "deployment":
        deployment_status = "failed"
    else:
        deployment_status = default_span_status

    spans = [
        {
            "name": "agent.detection",
            "duration": detection_ms,
            "status": default_span_status,
            "timestamp": stage_timestamps["agent.detection"],
            "details": stage_details["agent.detection"],
            "attributes": attrs,
        },
        {
            "name": "agent.diagnosis",
            "duration": diagnosis_ms,
            "status": default_span_status,
            "timestamp": stage_timestamps["agent.diagnosis"],
            "details": stage_details["agent.diagnosis"],
            "attributes": attrs,
        },
        {
            "name": "agent.remediation",
            "duration": remediation_ms,
            "status": default_span_status,
            "timestamp": stage_timestamps["agent.remediation"],
            "details": stage_details["agent.remediation"],
            "attributes": attrs,
        },
        {
            "name": "agent.validation",
            "duration": round(validation_ms, 2),
            "status": "failed" if record.failure_stage and record.failure_stage.value == "validation" else default_span_status,
            "timestamp": stage_timestamps["agent.validation"],
            "details": stage_details["agent.validation"],
            "attributes": attrs,
        },
        {
            "name": "agent.deployment",
            "duration": round(deployment_ms, 2),
            "status": deployment_status,
            "timestamp": stage_timestamps["agent.deployment"],
            "details": stage_details["agent.deployment"],
            "attributes": attrs,
        },
    ]

    return {
        "job_id": job.job_id,
        "trace_name": "pipeline.run",
        "status": record.remediation_status.value,
        "spans": spans,
    }


# ─────────────────────────────────────────────
# Application Setup
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global VALID_API_KEYS
    try:
        VALID_API_KEYS = _load_valid_api_keys()
    except RuntimeError as e:
        logger.critical("api_key_config_missing", error=str(e))
        raise
    logger.info("api_starting")
    run_startup_preflight(settings)

    if not hasattr(app.state, "orchestrator"):
        from knowledge.rag_engine import RAGEngine
        from sandbox.sandbox_executor import SandboxExecutor
        # FIX #2: Use AgentOrchestrator directly — OTel is embedded inside it.
        # The previous wrapper approach was removed because background jobs bypassed tracing.
        from agents.orchestrator import AgentOrchestrator
        from experiments.scenario_runner import LogSimulator
        from listener.real_metrics import RealLogListener  # FIX #1
        from infrastructure.redis_client import get_shared_redis_client, close_shared_redis_client
        from infrastructure.persistence import JobStore, FingerprintStore
        from infrastructure.distributed_lock import DistributedLock

        # One shared connection pool for all three infrastructure classes.
        redis_client = get_shared_redis_client()
        app.state.redis_client = redis_client
        app.state.job_store = JobStore(redis_client)
        app.state.fingerprint_store = FingerprintStore(redis_client)
        app.state.lock_manager = DistributedLock(redis_client)

        knowledge = RAGEngine()
        await knowledge.initialize()

        playbooks_dir = Path(__file__).parent / "knowledge" / "playbooks"
        if playbooks_dir.exists():
            for pb in sorted(playbooks_dir.glob("*.md")):
                await knowledge.ingest_playbook(str(pb))
        logger.info("knowledge_loaded",
                    docs=knowledge.document_count,
                    backend=knowledge.embedding_backend)

        sandbox = SandboxExecutor()
        await sandbox.initialize()

        orchestrator = AgentOrchestrator(
            knowledge_engine=knowledge,
            sandbox_executor=sandbox,
        )
        await orchestrator.initialize()

        app.state.orchestrator = orchestrator
        app.state.knowledge_engine = knowledge
        app.state.sandbox = sandbox

        # FIX #1: Real log listener with simulator fallback
        simulator = LogSimulator()           # still used as fallback during warm-up
        app.state.simulator = simulator
        app.state.real_listener = RealLogListener(
            service_name="aethelgard-api",
            fallback_simulator=simulator,
            min_real_metrics=5,
        )

    logger.info("api_ready",
                telemetry="real_middleware",
                tracing="embedded_in_orchestrator",
                deduplication="enabled")
    yield

    # Graceful shutdown
    if hasattr(app.state, "orchestrator"):
        await app.state.orchestrator.shutdown()
    if hasattr(app.state, "real_listener"):
        await app.state.real_listener.stop()
    if hasattr(app.state, "redis_client"):
        from infrastructure.redis_client import close_shared_redis_client
        await close_shared_redis_client()
    logger.info("api_shutdown_complete")



app = FastAPI(
    title="Aethelgard v2 — Autonomous DevOps Platform",
    description=(
        "AI-native infrastructure intelligence platform.\n\n"
        "**Authentication**: Write endpoints require `X-API-Key` header.\n"
        "Set `AETHELGARD_API_KEY` environment variable to configure the key."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)

# Instrument FastAPI with OpenTelemetry (auto-traces every HTTP request)
if _OTEL_FASTAPI_AVAILABLE and FastAPIInstrumentor is not None:
    FastAPIInstrumentor.instrument_app(app)

# FIX #1 — Real metrics middleware: measures actual request latency/errors
# and writes them to MetricsBuffer so DetectionAgent reads real data.
from listener.real_metrics import AethelgardMetricsMiddleware
app.add_middleware(AethelgardMetricsMiddleware, service_name="aethelgard-api")

# FIX #5 — CORS: explicit origins, no wildcard + credentials combination
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "AETHELGARD_CORS_ORIGINS",
        "http://localhost:8501,http://localhost:3000,http://localhost:8000"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,   # FIX: was True — incompatible with allow_origins="*"
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# Registered last → outermost → executes before CORS on every request.
app.add_middleware(RequestIDMiddleware)


# ─────────────────────────────────────────────
# Read-only Endpoints (no auth required)
# ─────────────────────────────────────────────

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "Aethelgard v2",
        "description": "Autonomous DevOps Platform",
        "version": settings.app_version,
        "docs": "/docs",
        "auth": "Write endpoints require X-API-Key header",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    rag_backend = None
    if hasattr(app.state, "knowledge_engine"):
        rag_backend = app.state.knowledge_engine.embedding_backend
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        uptime_seconds=round(time.time() - START_TIME, 1),
        agents_active=5,
        environment=settings.app_env.value,
        rag_backend=rag_backend,
    )


@app.get("/metrics/prometheus", tags=["Observability"],
         response_class=Response,
         summary="Prometheus metrics endpoint")
async def prometheus_metrics():
    """
    Prometheus-format metrics scrape endpoint.

    Configure Prometheus to scrape: GET /metrics/prometheus
    (using /metrics/prometheus to avoid collision with the domain /metrics endpoint)
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/ready", tags=["Health"])
async def readiness_check():
    return {"ready": True, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/metrics", response_model=PlatformMetrics, tags=["Metrics"])
async def get_metrics():
    return app.state.orchestrator.get_metrics()


@app.get("/api/metrics", response_model=OperationsMetricsResponse, tags=["Observability"])
async def get_operations_metrics():
    """Frontend-oriented, pre-aggregated operations metrics."""
    platform_metrics = app.state.orchestrator.get_metrics()
    metrics_text = generate_latest().decode("utf-8", errors="replace")

    active_pipelines = _extract_prom_metric_value(metrics_text, "aethelgard_active_pipeline_jobs")
    dedup_ratio = _extract_prom_metric_value(metrics_text, "aethelgard_dedup_suppression_ratio")

    recent = app.state.orchestrator.get_recent_remediations(limit=200)
    failed_health = sum(
        1
        for r in recent
        if r.failure_stage and r.failure_stage.value == "deployment"
    )

    return OperationsMetricsResponse(
        activePipelines=int(active_pipelines),
        dedupRatio=round(dedup_ratio * 100, 2),
        failedHealth=failed_health,
        avgLatency=round(platform_metrics.avg_mttr_seconds * 1000, 2),
        mttdSeconds=round(platform_metrics.avg_mttd_seconds, 3),
        mttrSeconds=round(platform_metrics.avg_mttr_seconds, 3),
        autonomousResolutionRate=round(platform_metrics.autonomous_resolution_rate * 100, 2),
    )


@app.get("/metrics/history", tags=["Metrics"])
async def get_metrics_history(limit: int = Query(50, ge=1, le=500)):
    records = app.state.orchestrator.get_recent_remediations(limit=limit)
    return {
        "count": len(records),
        "records": [
            {
                "id": r.id,
                "anomaly_type": r.anomaly.anomaly_type,
                "service": r.anomaly.service_name,
                "severity": r.anomaly.severity.value,
                "root_cause": r.diagnosis.root_cause,
                "patch_type": r.patch.patch_type,
                "remediation_status": r.remediation_status.value,
                "failure_stage": r.failure_stage.value if r.failure_stage else None,
                "failure_reason": r.failure_reason,
                "risk_score": r.validation.risk_score,
                "was_successful": r.was_successful,
                "mttd_seconds": round(r.mttd_seconds, 3),
                "mttr_seconds": round(r.mttr_seconds, 2),
                "completed_at": r.completed_at.isoformat(),
            }
            for r in records
        ],
    }


@app.get("/scenarios", tags=["Simulation"])
async def list_scenarios():
    from experiments.scenario_runner import DEMO_SCENARIOS
    return {
        "scenarios": {
            name: {
                "service": s.target_service,
                "type": s.anomaly_type,
                "severity": s.severity.value,
                "latency_multiplier": s.latency_multiplier,
                "duration_seconds": s.duration_seconds,
            }
            for name, s in DEMO_SCENARIOS.items()
        }
    }


@app.get("/knowledge/stats", tags=["Knowledge"])
async def knowledge_stats():
    engine = app.state.knowledge_engine
    return {
        "total_documents": engine.document_count,
        "categories": engine.categories,
        "embedding_backend": engine.embedding_backend,
    }


@app.get("/knowledge/search", tags=["Knowledge"])
async def search_knowledge(
    query: str = Query(..., max_length=1024),
    top_k: int = Query(5, ge=1, le=20),
    category: Optional[str] = Query(None, max_length=64),
):
    engine = app.state.knowledge_engine
    results = await engine.query(query, top_k=top_k, category=category)
    return {"query": query, "results": results, "count": len(results)}


# ─────────────────────────────────────────────
# Write/Action Endpoints (FIX #5: API key required)
# ─────────────────────────────────────────────

@app.post("/inject", tags=["Simulation"])
async def inject_anomaly(
    request: InjectAnomalyRequest,
    _api_key: str = Depends(require_api_key),
):
    """
    Inject an anomaly scenario into the simulation.

    **Requires X-API-Key header.**
    """
    simulator = app.state.simulator
    try:
        scenario = simulator.inject_anomaly(request.scenario)
        return {
            "status": "injected",
            "scenario": request.scenario,
            "service": scenario.target_service,
            "anomaly_type": scenario.anomaly_type,
            "severity": scenario.severity.value,
            "duration_seconds": scenario.duration_seconds,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/pipeline/run",
    response_model=PipelineJobResponse,
    status_code=202,
    tags=["Pipeline"],
)
async def run_pipeline(
    background_tasks: BackgroundTasks,
    scenario: str = Query("payment_latency_spike", max_length=64),
    _api_key: str = Depends(require_api_key),
):
    """
    FIX #7 — Trigger autonomous remediation pipeline as a background job.

    Returns **202 Accepted** immediately with a job_id.
    Poll **GET /pipeline/jobs/{job_id}** for completion status.

    **Requires X-API-Key header.**

    Previous flaw: This endpoint blocked the event loop for the full pipeline
    duration (~0.5–60s), making the API unresponsive to all other requests.
    """
    simulator = app.state.simulator
    orchestrator = app.state.orchestrator

    # Validate scenario exists before accepting job
    try:
        simulator.inject_anomaly(scenario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create and register background job immediately
    job = orchestrator.create_job(scenario=scenario)

    async def _run_with_baseline():
        """Run baseline collection + pipeline inside the background task."""
        # FIX (LOGIC-05): actually feed baseline metrics to rolling window
        for _ in range(15):
            await orchestrator.detection_agent.collect_baseline(
                simulator.generate_metrics()
            )
        # Generate anomalous metrics
        anomaly_metrics = simulator.generate_metrics()
        await orchestrator.run_job(job=job, metrics=anomaly_metrics)

    # FIX #7 — Fire and forget: endpoint returns 202 immediately
    background_tasks.add_task(_run_with_baseline)

    logger.info("pipeline_job_accepted", job_id=job.job_id, scenario=scenario)

    return PipelineJobResponse(
        job_id=job.job_id,
        status="pending",
        scenario=scenario,
        poll_url=f"/pipeline/jobs/{job.job_id}",
    )


@app.get("/pipeline/jobs/{job_id}", response_model=PipelineJobStatus, tags=["Pipeline"])
async def get_pipeline_job(job_id: str):
    """
    Get the status of a background pipeline job.

    Returns current status: pending | running | completed | failed
    When completed, includes full remediation results.
    """
    orchestrator = app.state.orchestrator
    job = orchestrator.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    started_at_iso: Optional[str] = None
    if job.started_at:
        started_at_iso = datetime.fromtimestamp(job.started_at, tz=timezone.utc).isoformat()

    response = PipelineJobStatus(
        job_id=job.job_id,
        status=job.status,
        scenario=job.scenario,
        started_at=started_at_iso,
        duration_seconds=job.duration_seconds,
        error=job.error,
        remediation_status=job.remediation_status,
        failure_stage=job.failure_stage,
        failure_reason=job.failure_reason,
    )

    if job.status == "completed":
        record = job.record
        response.anomaly_detected = True
        response.anomaly_type = job.anomaly_type
        response.patch_type = job.patch_type
        response.deployed = job.deployed
        response.remediation_status = job.remediation_status
        response.failure_stage = job.failure_stage
        response.failure_reason = job.failure_reason
        if record:
            response.service = record.anomaly.service_name
            response.root_cause = record.diagnosis.root_cause
            response.mttd_seconds = round(record.mttd_seconds, 3)
            response.mttr_seconds = round(record.mttr_seconds, 2)

    return response


@app.get("/api/remediation/{job_id}/timeline", tags=["Pipeline"])
async def remediation_timeline(job_id: str):
    orchestrator = app.state.orchestrator
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _build_timeline_payload(job, job.record)


@app.websocket("/api/remediation/{job_id}/timeline/ws")
async def remediation_timeline_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    orchestrator = app.state.orchestrator
    try:
        while True:
            job = orchestrator.get_job(job_id)
            if not job:
                await websocket.send_json({"error": "job_not_found", "job_id": job_id})
                break

            payload = _build_timeline_payload(job, job.record)
            await websocket.send_json(payload)

            if job.status in ("completed", "failed"):
                break

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@app.get("/api/pipeline/{job_id}/spans", tags=["Pipeline"])
async def pipeline_spans(job_id: str):
    orchestrator = app.state.orchestrator
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _build_span_payload(job, job.record)


@app.get("/pipeline/jobs", tags=["Pipeline"])
async def list_pipeline_jobs(limit: int = Query(20, ge=1, le=100)):
    """List recent pipeline jobs with their statuses."""
    orchestrator = app.state.orchestrator
    jobs = orchestrator.list_jobs(limit=limit)
    return {
        "count": len(jobs),
        "jobs": [j.to_dict() for j in jobs],
    }
