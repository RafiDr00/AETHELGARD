import os
import time
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.config import get_settings
from core.logging_config import get_logger
from core.preflight import run_startup_preflight

from interfaces.api.routes import pipeline_routes, health_routes
from interfaces.api.streams import sse_stream, ws_stream

# New Imports
from infrastructure.persistence import JobStore, FingerprintStore
from infrastructure.distributed_lock import DistributedLock
from application.agent_coordinator import AgentCoordinator
from application.workflow_engine import WorkflowEngine
from observability.metrics_publisher import MetricsPublisher

logger = get_logger("aethelgard.api.app")
settings = get_settings()

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    _OTEL_FASTAPI_AVAILABLE = True
except ImportError:
    FastAPIInstrumentor = None
    _OTEL_FASTAPI_AVAILABLE = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_starting_refactored")
    run_startup_preflight(settings)
    
    app.state.startup_error = None
    
    # Domain & Application Setup
    from knowledge.rag_engine import RAGEngine
    from sandbox.sandbox_executor import SandboxExecutor
    import redis.asyncio as redis
    
    redis_client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True
    )
    
    job_store = JobStore(redis_client)
    fingerprint_store = FingerprintStore(redis_client)
    lock_manager = DistributedLock(redis_client)
    metrics_publisher = MetricsPublisher()
    
    knowledge = RAGEngine()
    sandbox = SandboxExecutor()
    
    coordinator = AgentCoordinator(
        knowledge_engine=knowledge,
        sandbox_executor=sandbox,
    )
    
    orchestrator = WorkflowEngine(
        job_store=job_store,
        fingerprint_store=fingerprint_store,
        lock_manager=lock_manager,
        agent_coordinator=coordinator,
        metrics_publisher=metrics_publisher
    )
    
    async def _initialize_dependencies() -> None:
        try:
            await knowledge.initialize()
            await sandbox.initialize()
            await orchestrator.initialize()
        except Exception as exc:
            app.state.startup_error = str(exc)
            logger.exception("startup_initialization_failed", error=str(exc))
            
    import asyncio
    app.state.startup_task = asyncio.create_task(_initialize_dependencies())
    
    app.state.orchestrator = orchestrator # This is now the WorkflowEngine
    app.state.knowledge_engine = knowledge
    app.state.sandbox = sandbox
    
    from experiments.scenario_runner import LogSimulator
    app.state.simulator = LogSimulator()
    
    logger.info("api_ready_refactored")
    yield
    
    if hasattr(app.state, "orchestrator"):
        await app.state.orchestrator.shutdown()
    await redis_client.close()
    logger.info("api_shutdown_complete")

app = FastAPI(
    title="Aethelgard \u2014 Autonomous DevOps Platform",
    description="AI-native infrastructure intelligence platform.",
    version=settings.app_version,
    lifespan=lifespan,
)

if _OTEL_FASTAPI_AVAILABLE and FastAPIInstrumentor is not None:
    FastAPIInstrumentor.instrument_app(app)

_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("AETHELGARD_CORS_ORIGINS", "http://localhost:8000").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    request_id = str(uuid4())
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 2)
    logger.info("http_request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=duration)
    return response

app.include_router(pipeline_routes.router, prefix="/api/v1")
app.include_router(health_routes.router, prefix="/api/v1")
app.include_router(sse_stream.router, prefix="/api/v1")
app.include_router(ws_stream.router, prefix="/api/v1")
app.include_router(health_routes.router)
