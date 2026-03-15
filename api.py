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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, BackgroundTasks, Depends, Security, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
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
                       provided_key=str(x_api_key)[:8] + "..." if x_api_key else "none")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return str(x_api_key)


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
    pipelineLatencyMs: float
    throughputEps: float
    sandboxDurationSeconds: float
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
    from listener.prometheus_scraper import PrometheusScraper
    from tools.docker_client import DockerRemediator

    async def _autonomous_detection_loop(orchestrator, scraper):
        """Periodically check for anomalies in real metrics."""
        logger.info("autonomous_detection_loop_started")
        while True:
            try:
                # Consume metrics from the scraper's buffer
                metrics = await scraper.buffer.read_batch(limit=20)
                if metrics:
                    # Trigger the pipeline — detection stage is first
                    await orchestrator.run_full_pipeline(
                        metrics=metrics,
                        scenario="real_traffic"
                    )
            except Exception as e:
                logger.error("autonomous_loop_iteration_failed", error=str(e))
            await asyncio.sleep(5.0)

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

    docker_remediator = DockerRemediator()

    orchestrator = AgentOrchestrator(
        knowledge_engine=knowledge,
        sandbox_executor=sandbox,
        docker_remediator=docker_remediator,
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

    # Scrape real microservices from Prometheus
    # In Docker: use http://prometheus:9090. Local: http://localhost:9090
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    scraper = PrometheusScraper(prometheus_url=prom_url, scrape_interval=settings.metrics.metrics_export_interval)
    app.state.prom_scraper = scraper
    
    # Start background tasks
    asyncio.create_task(app.state.real_listener.start())
    asyncio.create_task(app.state.prom_scraper.start())
    asyncio.create_task(_autonomous_detection_loop(orchestrator, scraper))

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
    if hasattr(app.state, "prom_scraper"):
        await app.state.prom_scraper.stop()
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
    allow_headers=["Content-Type", "X-API-Key"],
)


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


# ─────────────────────────────────────────────────────────────────────────────
# API v1 Router — all business routes versioned under /api/v1
# ─────────────────────────────────────────────────────────────────────────────
v1_router = APIRouter(prefix="/api/v1")


@v1_router.get("/metrics", response_model=PlatformMetrics, tags=["Metrics"])
async def get_metrics():
    return _get_state("orchestrator").get_metrics()


@v1_router.get("/metrics/ops", response_model=OperationsMetricsResponse, tags=["Observability"])
async def get_operations_metrics():
    """Frontend-oriented, pre-aggregated operations metrics."""
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
        pipelineLatencyMs=round(platform_metrics.avg_pipeline_latency_ms, 2),
        throughputEps=round(platform_metrics.events_per_second, 2),
        sandboxDurationSeconds=round(platform_metrics.avg_sandbox_duration_seconds, 2),
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
    simulator = _get_state("simulator")
    orchestrator = _get_state("orchestrator")

    # Validate scenario exists before accepting job
    try:
        simulator.inject_anomaly(scenario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create and register background job immediately
    job = await orchestrator.create_job(scenario=scenario)

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
        poll_url=f"/api/v1/pipeline/jobs/{job.job_id}",
    )


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
async def get_pipeline_job(job_id: str):
    """
    Get the status of a background pipeline job.

    Returns current status: pending | running | completed | failed | awaiting_approval
    When completed, includes full remediation results.
    """
    orchestrator = _get_state("orchestrator")
    job = await orchestrator.get_job(job_id)

    if not job:
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
        response.service = record.anomaly.service_name
        response.anomaly_type = record.anomaly.anomaly_type
        response.root_cause = record.diagnosis.root_cause
        response.patch_type = record.patch.patch_type
        response.remediation_status = record.remediation_status.value
        response.failure_stage = record.failure_stage.value if record.failure_stage else None
        response.failure_reason = record.failure_reason
        response.risk_score = record.validation.risk_score
        response.deployed = record.was_successful
        response.mttd_seconds = round(record.mttd_seconds, 3)
        response.mttr_seconds = round(record.mttr_seconds, 2)

    return response


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
async def remediation_timeline(job_id: str):
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
async def remediation_timeline_ws(websocket: WebSocket, job_id: str, token: str = Query(...)):
    if token not in VALID_API_KEYS:
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


@v1_router.get("/pipeline/{job_id}/spans", tags=["Pipeline"])
async def pipeline_spans(job_id: str):
    orchestrator = _get_state("orchestrator")
    job = await orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _build_span_payload(job, job.record)


@v1_router.get("/pipeline/jobs", tags=["Pipeline"])
async def list_pipeline_jobs(limit: int = Query(20, ge=1, le=100)):
    """List recent pipeline jobs with their statuses."""
    orchestrator = _get_state("orchestrator")
    jobs = await orchestrator.list_jobs(limit=limit)
    return {
        "count": len(jobs),
        "jobs": [j.to_dict() for j in jobs],
    }


# ── Mount versioned router ─────────────────────────────────────────────────────────────────────────
app.include_router(v1_router)
