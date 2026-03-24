import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import get_settings
from core.logging_config import get_logger
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

logger = get_logger("aethelgard.api.health_routes")
router = APIRouter(tags=["Health"])

START_TIME = time.time()
settings = get_settings()

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    agents_active: int
    environment: str
    rag_backend: Optional[str] = None

@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    rag_backend = None
    if hasattr(request.app.state, "knowledge_engine") and request.app.state.knowledge_engine:
        rag_backend = getattr(request.app.state.knowledge_engine, "embedding_backend", None)
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        uptime_seconds=round(time.time() - START_TIME, 1),
        agents_active=5,
        environment=settings.app_env.value,
        rag_backend=rag_backend,
    )

@router.get("/metrics/prometheus", tags=["Observability"], response_class=Response)
async def prometheus_metrics():
    """Prometheus-format metrics scrape endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

@router.get("/metrics", tags=["Observability"], include_in_schema=False)
async def prometheus_metrics_legacy():
    return await prometheus_metrics()

@router.get("/ready")
async def readiness_check(request: Request):
    startup_error = getattr(request.app.state, "startup_error", None)
    if startup_error:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "startup_failed", "error": startup_error})
    
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "orchestrator_missing"})
        
    return {"ready": True, "status": "ok"}
