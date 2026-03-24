import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from interfaces.api.dependencies import _resolve_websocket_api_key, VALID_API_KEYS
from core.config import get_settings
from prometheus_client import generate_latest
from core.logging_config import get_logger

logger = get_logger("aethelgard.api.ws_stream")
router = APIRouter(tags=["Observability"])
settings = get_settings()
START_TIME = time.time()

def _extract_prom_metric_value(metrics_text: str, metric_name: str) -> float:
    for line in metrics_text.splitlines():
        if line.startswith(f"{metric_name}{{") or line.startswith(f"{metric_name} "):
            try:
                parts = line.split()
                return float(parts[-1])
            except ValueError:
                return 0.0
    return 0.0

@router.websocket("/remediation/{job_id}/timeline/ws")
async def remediation_timeline_ws(websocket: WebSocket, job_id: str):
    ws_api_key = _resolve_websocket_api_key(websocket)
    if not ws_api_key or ws_api_key not in VALID_API_KEYS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    orchestrator = getattr(websocket.app.state, "orchestrator", None)
    if orchestrator is None:
        await websocket.send_json({"error": "service_not_ready", "detail": "orchestrator not initialized"})
        await websocket.close(code=1011)
        return
    try:
        while True:
            job = await orchestrator.job_store.get_job(job_id)
            if not job:
                await websocket.send_json({"error": "job_not_found", "job_id": job_id})
                break

            await websocket.send_json(job.to_dict())

            if job.status.value in ("completed", "failed"):
                break

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return

@router.websocket("/ops/ws")
async def ops_ws(websocket: WebSocket, limit: int = Query(10, ge=1, le=100)):
    ws_api_key = _resolve_websocket_api_key(websocket)
    if not ws_api_key or ws_api_key not in VALID_API_KEYS:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            orchestrator = getattr(websocket.app.state, "orchestrator", None)
            if orchestrator is None:
                await websocket.send_json({"error": "service_not_ready"})
                await asyncio.sleep(1.0)
                continue

            health = {
                "status": "healthy",
                "version": settings.app_version,
                "uptime_seconds": round(time.time() - START_TIME, 1),
                "agents_active": 5,
                "environment": settings.app_env.value,
            }

            metrics_text = generate_latest().decode("utf-8", errors="replace")
            active_pipelines = _extract_prom_metric_value(metrics_text, "aethelgard_active_pipeline_jobs")
            dedup_ratio = _extract_prom_metric_value(metrics_text, "aethelgard_dedup_suppression_ratio")

            ops = {
                "activePipelines": int(active_pipelines),
                "dedupRatio": round(dedup_ratio * 100, 2),
            }

            jobs = await orchestrator.job_store.list_jobs(limit=limit)
            jobs_payload = [j.to_dict() for j in jobs]

            await websocket.send_json(
                {
                    "health": health,
                    "ops": ops,
                    "jobs": jobs_payload,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
