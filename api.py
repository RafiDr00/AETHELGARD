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
import json
import os
import re
import sys
import time
from uuid import uuid4
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, BackgroundTasks, Depends, Security, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

# Load .env file into os.environ before any env-dependent code runs
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on env vars being set externally

from core.config import get_settings
from core.logging_config import get_logger, setup_logging
from core.models import PlatformMetrics
from core.preflight import run_startup_preflight
from services.log_simulator import DEMO_SCENARIOS

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
OPS_CONSOLE_PATH = Path(__file__).parent / "ui" / "ops_console.html"
OPS_CONSOLE_CSS_PATH = Path(__file__).parent / "ui" / "ops_console.css"
OPS_CONSOLE_JS_PATH = Path(__file__).parent / "ui" / "ops_console.js"
UI_ASSETS_DIR = Path(__file__).parent / "ui"

# ─────────────────────────────────────────────
# FIX #5 — API Key Authentication
# ─────────────────────────────────────────────

# API keys are loaded from environment / settings.
# In production: use a vault-backed secret store.
# For development: set AETHELGARD_API_KEY env var.
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def _load_valid_api_keys() -> set:
    """Load valid API keys from environment. Fails hard if none are configured."""
    keys = set()
    # Primary key from env
    primary = os.environ.get("AETHELGARD_API_KEY", "")
    if primary:
        keys.add(primary)
    # Additional comma-separated keys
    extra = os.environ.get("AETHELGARD_API_KEYS", "")
    if extra:
        keys.update(k.strip() for k in extra.split(",") if k.strip())
    # Fail fast — no silent dev fallback in production
    if not keys:
        raise RuntimeError(
            "AETHELGARD_API_KEY environment variable must be set. "
            "No API key is configured — refusing to start with an unsecured endpoint."
        )
    return keys

VALID_API_KEYS: set = _load_valid_api_keys()


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
                       provided_key=x_api_key[:8] + "..." if x_api_key else "none")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key


def _resolve_websocket_api_key(websocket: WebSocket) -> Optional[str]:
    """
    Resolve API key for websocket auth from headers.
    Preferred sources:
      1) X-API-Key header
      2) Authorization: Bearer <token>
      3) Sec-WebSocket-Protocol value `api-key.<token>` (browser-compatible)

    Optional legacy fallback:
      - Query param `token` ONLY when AETHELGARD_ALLOW_LEGACY_WS_QUERY_TOKEN=true
    """
    header_key = (websocket.headers.get("x-api-key") or "").strip()
    if header_key:
        return header_key

    auth_header = (websocket.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()
        if bearer:
            return bearer

    subprotocols = websocket.headers.get("sec-websocket-protocol") or ""
    for item in (p.strip() for p in subprotocols.split(",") if p.strip()):
        if item.startswith("api-key."):
            token = item[len("api-key."):].strip()
            if token:
                return token

    if os.environ.get("AETHELGARD_ALLOW_LEGACY_WS_QUERY_TOKEN", "false").lower() == "true":
        legacy = (websocket.query_params.get("token") or "").strip()
        if legacy:
            logger.warning("websocket_legacy_query_token_used")
            return legacy

    return None


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

    stages = ["detection", "diagnosis", "remediation", "validation", "awaiting_approval", "deployment"]
    if record is None:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "timeline": [
                {
                    "stage": stage,
                    "status": "pending" if stage != "awaiting_approval" else "pending",
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
        "awaiting_approval": record.validation.validated_at,  # same as validation for now
        "deployment": record.deployment.deployed_at,
    }

    details = {
        "detection": f"anomaly detected ({record.anomaly.anomaly_type})",
        "diagnosis": f"diagnosis: {record.diagnosis.root_cause[:96]}",
        "remediation": f"remediation generated ({record.patch.patch_type})",
        "validation": f"validation complete (risk_score={record.validation.risk_score:.2f})",
        "awaiting_approval": "awaiting manual approval to deploy",
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

    # Handle awaiting_approval status
    if record.remediation_status.value == "awaiting_approval":
        approval_idx = stages.index("awaiting_approval")
        for i, item in enumerate(timeline):
            if item["stage"] == "awaiting_approval":
                item["status"] = "running"
            elif i > approval_idx:
                item["status"] = "pending"
                item["timestamp"] = "--:--:--"

    if record.remediation_status.value == "rolled_back":
        for item in timeline:
            if item["stage"] == "deployment":
                item["status"] = "rolled_back"
                break

    if record.failure_stage:
        failure_stage_name = record.failure_stage.value
        failure_idx = stages.index(failure_stage_name) if failure_stage_name in stages else -1
        for i, item in enumerate(timeline):
            if i < failure_idx:
                pass  # stages before failure remain "success"
            elif i == failure_idx:
                item["status"] = "failed"
                if record.failure_reason:
                    item["details"] = f"{item['details']} \u2014 {record.failure_reason}"
            else:
                # Stages after the failure point never ran — mark pending
                item["status"] = "pending"
                item["timestamp"] = "--:--:--"
                item["details"] = f"{item['stage']} did not run"

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


def _map_log_level_to_severity(level: str) -> str:
    normalized = (level or "").upper()
    if normalized in {"WARN", "WARNING"}:
        return "warning"
    if normalized in {"ERROR", "CRITICAL", "FATAL"}:
        return "error"
    if normalized in {"SUCCESS", "OK"}:
        return "success"
    return "info"


def _infer_stage_from_log_message(message: str) -> str:
    text = (message or "").lower()
    if "detect" in text or "anomaly" in text:
        return "detection"
    if "diagnos" in text or "root cause" in text:
        return "diagnosis"
    if "remedi" in text or "patch" in text:
        return "remediation"
    if "validat" in text or "risk" in text or "health" in text:
        return "validation"
    if "deploy" in text or "release" in text:
        return "deployment"
    return "detection"


def _sse_log_payload(log_entry) -> Dict[str, Any]:
    return {
        "id": log_entry.id,
        "timestamp": log_entry.timestamp.isoformat(),
        "severity": _map_log_level_to_severity(log_entry.level),
        "stage": _infer_stage_from_log_message(log_entry.message),
        "service": log_entry.service_name,
        "message": log_entry.message,
        "trace_id": log_entry.trace_id,
        "span_id": log_entry.span_id,
    }


# ─────────────────────────────────────────────
# Application Setup
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager — always initialises all services unconditionally."""
    logger.info("api_starting")
    run_startup_preflight(settings)

    from knowledge.rag_engine import RAGEngine
    from sandbox.sandbox_executor import SandboxExecutor
    # FIX #2: Use AgentOrchestrator directly — OTel is embedded inside it.
    # The previous wrapper approach was removed because background jobs bypassed tracing.
    from agents.orchestrator import AgentOrchestrator
    from services.log_simulator import LogSimulator
    from listener.real_metrics import RealLogListener  # FIX #1

    knowledge = RAGEngine()
    sandbox = SandboxExecutor()

    orchestrator = AgentOrchestrator(
        knowledge_engine=knowledge,
        sandbox_executor=sandbox,
    )

    app.state.startup_error = None

    async def _initialize_dependencies() -> None:
        try:
            await knowledge.initialize()

            playbooks_dir = Path(__file__).parent / "knowledge" / "playbooks"
            if playbooks_dir.exists():
                for pb in sorted(playbooks_dir.glob("*.md")):
                    await knowledge.ingest_playbook(str(pb))
            logger.info("knowledge_loaded",
                        docs=knowledge.document_count,
                        backend=knowledge.embedding_backend)

            await sandbox.initialize()
            await orchestrator.initialize()
        except Exception as exc:
            app.state.startup_error = str(exc)
            logger.exception("startup_initialization_failed", error=str(exc))

    app.state.startup_task = asyncio.create_task(_initialize_dependencies())
    logger.info("ORCHESTRATOR_INSTANCE", id=id(orchestrator), stage="startup")

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
    startup_task = getattr(app.state, "startup_task", None)
    if startup_task and not startup_task.done():
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    if hasattr(app.state, "orchestrator"):
        await app.state.orchestrator.shutdown()
    if hasattr(app.state, "real_listener"):
        await app.state.real_listener.stop()
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
        "http://localhost:8000"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,   # FIX: was True — incompatible with allow_origins="*"
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    request_id = request.headers.get("x-request-id") or str(uuid4())
    try:
        response = await call_next(request)
    except Exception:
        duration = round((time.time() - start) * 1000, 2)
        logger.exception(
            "http_request_failed",
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            duration_ms=duration,
        )
        raise
    duration = round((time.time() - start) * 1000, 2)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration,
        request_id=request_id,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
        error=str(exc),
    )
    return JSONResponse(status_code=503, content={"error": "service_unavailable"})


# ─────────────────────────────────────────────
# Defensive state accessors
# ─────────────────────────────────────────────
# All app.state.* objects are accessed through _get_state() so that any
# endpoint that fires before the lifespan completes (or in tests that don't
# run the full lifespan) gets a clean HTTP 503 instead of a raw AttributeError.
def _get_state(key: str):
    """Return app.state.<key>, raising HTTP 503 with a clear message if absent."""
    obj = getattr(app.state, key, None)
    if obj is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Service not ready — '{key}' has not been initialized. "
                "The application startup may still be in progress. "
                "Retry in a moment."
            ),
        )
    return obj


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


@app.get("/ops", include_in_schema=False)
async def ops_console():
    if not OPS_CONSOLE_PATH.exists():
        raise HTTPException(status_code=404, detail="Ops console not found")
    return FileResponse(OPS_CONSOLE_PATH)


@app.get("/ui/ops_console.css", include_in_schema=False)
async def ops_console_css():
    if not OPS_CONSOLE_CSS_PATH.exists():
        raise HTTPException(status_code=404, detail="Ops console stylesheet not found")
    return FileResponse(OPS_CONSOLE_CSS_PATH, media_type="text/css")


@app.get("/ui/ops_console.js", include_in_schema=False)
async def ops_console_js():
    if not OPS_CONSOLE_JS_PATH.exists():
        raise HTTPException(status_code=404, detail="Ops console script not found")
    return FileResponse(OPS_CONSOLE_JS_PATH, media_type="application/javascript")


@app.get("/ui/{asset_path:path}", include_in_schema=False)
async def ui_assets(asset_path: str):
    candidate = (UI_ASSETS_DIR / asset_path).resolve()
    root = UI_ASSETS_DIR.resolve()
    if root not in candidate.parents or not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="UI asset not found")

    media_type = None
    if candidate.suffix == ".css":
        media_type = "text/css"
    elif candidate.suffix == ".js":
        media_type = "application/javascript"

    return FileResponse(candidate, media_type=media_type)


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


@app.get("/metrics", tags=["Observability"], include_in_schema=False)
async def prometheus_metrics_legacy():
    """Backward-compatible alias for legacy scrapers expecting /metrics."""
    return await prometheus_metrics()


@app.get("/ready", tags=["Health"])
async def readiness_check():
    orchestrator = getattr(app.state, "orchestrator", None)
    startup_error = getattr(app.state, "startup_error", None)
    if startup_error:
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "startup_failed",
                "error": startup_error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    if orchestrator is None:
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "orchestrator_missing",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    if not getattr(orchestrator, "ready", False):
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "orchestrator_not_ready",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    redis_client = getattr(orchestrator, "_redis", None)
    if redis_client is None:
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "redis_not_connected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    try:
        await redis_client.ping()
    except Exception as exc:
        logger.exception("readiness_redis_ping_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "redis_ping_failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    worker_task = getattr(orchestrator, "_job_worker_task", None)
    if worker_task is None or worker_task.done():
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "worker_not_running",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    return {"ready": True, "timestamp": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# API v1 Router — all business routes versioned under /api/v1
# ─────────────────────────────────────────────────────────────────────────────
v1_router = APIRouter(prefix="/api/v1")


@v1_router.get("/metrics", response_model=PlatformMetrics, tags=["Metrics"])
async def get_metrics():
    return _get_state("orchestrator").get_metrics()


@v1_router.get("/metrics/ops", response_model=OperationsMetricsResponse, tags=["Observability"])
async def get_operations_metrics():
    """Pre-aggregated operations metrics response."""
    orchestrator = _get_state("orchestrator")
    platform_metrics = orchestrator.get_metrics()
    metrics_text = generate_latest().decode("utf-8", errors="replace")

    active_pipelines = _extract_prom_metric_value(metrics_text, "aethelgard_active_pipeline_jobs")
    dedup_ratio = _extract_prom_metric_value(metrics_text, "aethelgard_dedup_suppression_ratio")

    recent = orchestrator.get_recent_remediations(limit=200)
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


@v1_router.get("/metrics/history", tags=["Metrics"])
async def get_metrics_history(limit: int = Query(50, ge=1, le=500)):
    records = _get_state("orchestrator").get_recent_remediations(limit=limit)
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


@v1_router.get("/scenarios", tags=["Simulation"])
async def list_scenarios():
    from services.log_simulator import DEMO_SCENARIOS
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


@v1_router.get("/knowledge/stats", tags=["Knowledge"])
async def knowledge_stats():
    engine = _get_state("knowledge_engine")
    return {
        "total_documents": engine.document_count,
        "categories": engine.categories,
        "embedding_backend": engine.embedding_backend,
    }


@v1_router.get("/knowledge/search", tags=["Knowledge"])
async def search_knowledge(
    query: str,
    top_k: int = Query(5, ge=1, le=20),
    category: Optional[str] = None,
):
    engine = _get_state("knowledge_engine")
    results = await engine.query(query, top_k=top_k, category=category)
    return {"query": query, "results": results, "count": len(results)}


# ─────────────────────────────────────────────
# Write/Action Endpoints (FIX #5: API key required)
# ─────────────────────────────────────────────

@v1_router.post("/inject", tags=["Simulation"])
async def inject_anomaly(
    request: InjectAnomalyRequest,
    _api_key: str = Depends(require_api_key),
):
    """
    Inject an anomaly scenario into the simulation.

    **Requires X-API-Key header.**
    """
    simulator = _get_state("simulator")
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


@v1_router.post(
    "/pipeline/run",
    response_model=PipelineJobResponse,
    status_code=202,
    tags=["Pipeline"],
)
async def run_pipeline(
    background_tasks: BackgroundTasks,
    scenario: str = Query("payment_latency_spike"),
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
    try:
        _get_state("simulator")
        orchestrator = getattr(app.state, "orchestrator", None)
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Service unavailable — orchestrator is not initialized.")
        if not getattr(orchestrator, "ready", False):
            raise HTTPException(status_code=429, detail="Service not ready — orchestrator restore is still in progress.")

        if scenario not in DEMO_SCENARIOS:
            raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario}")

        job = await orchestrator.create_job(scenario=scenario)

        logger.info("pipeline_job_accepted", job_id=job.job_id, scenario=scenario)

        return PipelineJobResponse(
            job_id=job.job_id,
            status="pending",
            scenario=scenario,
            poll_url=f"/api/v1/pipeline/jobs/{job.job_id}",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("pipeline_run_failed", error=str(exc), scenario=scenario)
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})


@app.post(
    "/pipeline/run",
    response_model=PipelineJobResponse,
    status_code=202,
    tags=["Pipeline"],
)
async def run_pipeline_legacy(
    background_tasks: BackgroundTasks,
    scenario: str = Query("payment_latency_spike"),
    _api_key: str = Depends(require_api_key),
):
    """Backward-compatible alias for clients still using /pipeline/run."""
    return await run_pipeline(
        background_tasks=background_tasks,
        scenario=scenario,
        _api_key=_api_key,
    )


@v1_router.get("/pipeline/jobs/{job_id}", response_model=PipelineJobStatus, tags=["Pipeline"])
async def get_pipeline_job(
    job_id: str,
    _api_key: str = Depends(require_api_key),
):
    """
    Get the status of a background pipeline job.

    Returns current status: pending | running | completed | failed | awaiting_approval
    When completed, includes full remediation results.
    """
    try:
        orchestrator = _get_state("orchestrator")
        logger.info("ORCHESTRATOR_INSTANCE", id=id(orchestrator), stage="api")
        job = await orchestrator.get_job(job_id)
        logger.info("API_LOOKUP", requested=job_id, exists=job is not None)

        if not job:
            redis_client = getattr(orchestrator, "_redis", None)
            job_prefix = getattr(orchestrator, "_REDIS_JOB_PREFIX", "aethelgard:job:")
            if redis_client:
                try:
                    raw_payload = await redis_client.get(f"{job_prefix}{job_id}")
                except Exception as exc:
                    logger.exception("pipeline_job_redis_lookup_failed", job_id=job_id, error=str(exc))
                    return JSONResponse(status_code=503, content={"error": "service_unavailable"})
                if raw_payload:
                    payload = json.loads(raw_payload)
                    started_at = payload.get("started_at")
                    finished_at = payload.get("finished_at")
                    duration_seconds = None
                    if isinstance(started_at, (int, float)) and isinstance(finished_at, (int, float)):
                        duration_seconds = round(finished_at - started_at, 3)

                    return PipelineJobStatus(
                       commit
                        job_id=str(payload.get("job_id", job_id)),
                        status=str(payload.get("status", "pending")),
                        scenario=str(payload.get("scenario", "unknown")),
                        duration_seconds=duration_seconds,
                        error=payload.get("error"),
                        remediation_status=payload.get("remediation_status"),
                        failure_stage=payload.get("failure_stage"),
                        failure_reason=payload.get("failure_reason"),
                    )

            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

        response = PipelineJobStatus(
            job_id=job.job_id,
            status=job.status,
            scenario=job.scenario,
            duration_seconds=job.duration_seconds,
            error=job.error,
            remediation_status=job.remediation_status,
            failure_stage=job.failure_stage,
            failure_reason=job.failure_reason,
        )

        if job.record and job.status == "completed":
            record = job.record
            response.anomaly_detected = True
            if getattr(record, "anomaly", None):
                response.service = record.anomaly.service_name
                response.anomaly_type = record.anomaly.anomaly_type
            if getattr(record, "diagnosis", None):
                response.root_cause = record.diagnosis.root_cause
            if getattr(record, "patch", None):
                response.patch_type = record.patch.patch_type
            if getattr(record, "remediation_status", None):
                response.remediation_status = record.remediation_status.value
            response.failure_stage = record.failure_stage.value if getattr(record, "failure_stage", None) else None
            response.failure_reason = getattr(record, "failure_reason", None)
            if getattr(record, "validation", None):
                response.risk_score = record.validation.risk_score
            response.deployed = getattr(record, "was_successful", None)
            if getattr(record, "mttd_seconds", None) is not None:
                response.mttd_seconds = round(record.mttd_seconds, 3)
            if getattr(record, "mttr_seconds", None) is not None:
                response.mttr_seconds = round(record.mttr_seconds, 2)

        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("pipeline_job_status_failed", job_id=job_id, error=str(exc))
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})


@app.get(
    "/pipeline/jobs/{job_id}",
    response_model=PipelineJobStatus,
    tags=["Pipeline"],
    include_in_schema=False,
)
async def get_pipeline_job_legacy(
    job_id: str,
    _api_key: str = Depends(require_api_key),
):
    """Backward-compatible alias for clients still using /pipeline/jobs/{job_id}."""
    return await get_pipeline_job(job_id=job_id, _api_key=_api_key)


@v1_router.post("/pipeline/{job_id}/approve", status_code=202, tags=["Pipeline"])
async def approve_deployment(
    job_id: str,
    background_tasks: BackgroundTasks,
    _api_key: str = Depends(require_api_key),
):
    """
    Approve a pending deployment that is awaiting manual approval.

    **Requires X-API-Key header.**

    Returns 202 Accepted. The deployment will resume in the background.
    Poll GET /pipeline/jobs/{job_id} to monitor progress.
    """
    orchestrator = _get_state("orchestrator")
    job = await orchestrator.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if not job.awaiting_approval:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is not awaiting approval. Current status: {job.status}",
        )

    logger.info("deployment_approval_requested", job_id=job_id)

    async def _resume_deployment():
        """Resume deployment in background task."""
        await orchestrator.approve_deployment(job_id)

    background_tasks.add_task(_resume_deployment)

    return {
        "status": "approval_accepted",
        "job_id": job_id,
        "message": "Deployment approval submitted. Deployment will resume in background.",
    }


@v1_router.get("/remediation/{job_id}/timeline", tags=["Pipeline"])
async def remediation_timeline(
    job_id: str,
    _api_key: str = Depends(require_api_key),
):
    orchestrator = _get_state("orchestrator")
    job = await orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _build_timeline_payload(job, job.record)


@v1_router.get("/log-stream", tags=["Observability"])
async def log_stream(
    request: Request,
    burst: int = Query(1, ge=0, le=200),
    interval_ms: int = Query(1000, ge=10, le=5000),
):
    simulator = _get_state("simulator")

    async def event_generator():
        # Bounded memory queue with drop-oldest behavior
        log_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=1000)
        last_heartbeat = time.time()

        try:
            while not await request.is_disconnected():
                now = time.time()
                
                # Simulation: generate burst of logs
                if burst > 0:
                    for log_entry in simulator.generate_logs(count=burst):
                        payload = _sse_log_payload(log_entry)
                        # Ensure span_id is present for front-end correlation
                        if not payload.get("span_id"):
                            payload["span_id"] = f"span-{payload.get('stage', 'detection')}"

                        if log_queue.full():
                            try:
                                log_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        log_queue.put_nowait(payload)

                # Drain and yield all pending events
                sent_any = False
                while not log_queue.empty():
                    event = log_queue.get_nowait()
                    event_id = str(event.get("id", "")) or f"evt-{int(time.time() * 1000)}"
                    
                    # Production SSE framing: id, retry, data
                    yield f"id: {event_id}\n"
                    yield "retry: 3000\n"
                    yield f"data: {json.dumps(event)}\n\n"
                    sent_any = True

                # Heartbeat management (10-15s)
                if sent_any:
                    last_heartbeat = now
                elif now - last_heartbeat > 12.0:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now

                await asyncio.sleep(interval_ms / 1000.0)
        except asyncio.CancelledError:
            # Generator cancellation (e.g. client disconnect) is expected
            pass
        finally:
            logger.info("sse_log_stream_closed", client=str(request.client if hasattr(request, "client") else "unknown"))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@v1_router.websocket("/remediation/{job_id}/timeline/ws")
async def remediation_timeline_ws(websocket: WebSocket, job_id: str):
    ws_api_key = _resolve_websocket_api_key(websocket)
    if not ws_api_key or ws_api_key not in VALID_API_KEYS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    orchestrator = getattr(app.state, "orchestrator", None)
    if orchestrator is None:
        await websocket.send_json({"error": "service_not_ready", "detail": "orchestrator not initialized"})
        await websocket.close(code=1011)
        return
    try:
        while True:
            job = await orchestrator.get_job(job_id)
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


@v1_router.websocket("/ops/ws")
async def ops_ws(websocket: WebSocket, limit: int = Query(10, ge=1, le=100)):
    ws_api_key = _resolve_websocket_api_key(websocket)
    if not ws_api_key or ws_api_key not in VALID_API_KEYS:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            orchestrator = getattr(app.state, "orchestrator", None)
            if orchestrator is None:
                await websocket.send_json({"error": "service_not_ready"})
                await asyncio.sleep(1.0)
                continue

            rag_backend = None
            if hasattr(app.state, "knowledge_engine"):
                rag_backend = app.state.knowledge_engine.embedding_backend

            health = {
                "status": "healthy",
                "version": settings.app_version,
                "uptime_seconds": round(time.time() - START_TIME, 1),
                "agents_active": 5,
                "environment": settings.app_env.value,
                "rag_backend": rag_backend,
            }

            platform_metrics = orchestrator.get_metrics()
            metrics_text = generate_latest().decode("utf-8", errors="replace")

            active_pipelines = _extract_prom_metric_value(metrics_text, "aethelgard_active_pipeline_jobs")
            dedup_ratio = _extract_prom_metric_value(metrics_text, "aethelgard_dedup_suppression_ratio")

            recent = orchestrator.get_recent_remediations(limit=200)
            failed_health = sum(
                1
                for r in recent
                if r.failure_stage and r.failure_stage.value == "deployment"
            )

            ops = {
                "activePipelines": int(active_pipelines),
                "dedupRatio": round(dedup_ratio * 100, 2),
                "failedHealth": failed_health,
                "avgLatency": round(platform_metrics.avg_mttr_seconds * 1000, 2),
                "mttdSeconds": round(platform_metrics.avg_mttd_seconds, 3),
                "mttrSeconds": round(platform_metrics.avg_mttr_seconds, 3),
                "autonomousResolutionRate": round(platform_metrics.autonomous_resolution_rate * 100, 2),
            }

            jobs = await orchestrator.list_jobs(limit=limit)
            jobs_payload = [j.to_dict() for j in jobs]

            latest_timeline = None
            latest_spans = None
            if jobs:
                latest_job = jobs[0]
                latest_timeline = _build_timeline_payload(latest_job, latest_job.record)
                latest_spans = _build_span_payload(latest_job, latest_job.record)

            await websocket.send_json(
                {
                    "health": health,
                    "ops": ops,
                    "jobs": jobs_payload,
                    "latest_timeline": latest_timeline,
                    "latest_spans": latest_spans,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return


@v1_router.get("/pipeline/{job_id}/spans", tags=["Pipeline"])
async def pipeline_spans(
    job_id: str,
    _api_key: str = Depends(require_api_key),
):
    orchestrator = _get_state("orchestrator")
    job = await orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _build_span_payload(job, job.record)


@v1_router.get("/pipeline/jobs", tags=["Pipeline"])
async def list_pipeline_jobs(
    limit: int = Query(20, ge=1, le=100),
    _api_key: str = Depends(require_api_key),
):
    """List recent pipeline jobs with their statuses."""
    orchestrator = _get_state("orchestrator")
    jobs = await orchestrator.list_jobs(limit=limit)
    return {
        "count": len(jobs),
        "jobs": [j.to_dict() for j in jobs],
    }


@app.get("/pipeline/jobs", tags=["Pipeline"], include_in_schema=False)
async def list_pipeline_jobs_legacy(
    limit: int = Query(20, ge=1, le=100),
    _api_key: str = Depends(require_api_key),
):
    """Backward-compatible alias for clients still using /pipeline/jobs."""
    return await list_pipeline_jobs(limit=limit, _api_key=_api_key)


# ── Mount versioned router ─────────────────────────────────────────────────────────────────────────
app.include_router(v1_router)
