
import asyncio
import json
import time
from typing import Any, Dict
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
from core.logging_config import get_logger

logger = get_logger("aethelgard.api.sse_stream")
router = APIRouter(tags=["Observability"])

def _sse_log_payload(log_entry: Any) -> Dict[str, Any]:
    # Support both object and dict access for flexibility
    if isinstance(log_entry, dict):
        return {
            "id": log_entry.get("id", f"evt-{int(time.time() * 1000)}"),
            "timestamp": log_entry.get("timestamp", time.time()),
            "service": log_entry.get("service_name", "unknown"),
            "level": log_entry.get("level", "INFO"),
            "message": log_entry.get("message", ""),
            "metadata": log_entry.get("metadata", {}),
            "trace_id": log_entry.get("trace_id", ""),
            "span_id": log_entry.get("span_id", "")
        }
    return {
        "id": getattr(log_entry, "id", f"evt-{int(time.time() * 1000)}"),
        "timestamp": getattr(log_entry, "timestamp", time.time()),
        "service": getattr(log_entry, "service_name", "unknown"),
        "level": getattr(log_entry, "level", "INFO"),
        "message": getattr(log_entry, "message", ""),
        "metadata": getattr(log_entry, "metadata", {}),
        "trace_id": getattr(log_entry, "trace_id", ""),
        "span_id": getattr(log_entry, "span_id", "")
    }


# --- Real pipeline event SSE stream ---
@router.get("/events")
async def pipeline_event_stream(request: Request, job_id: str = None):
    async def real_event_generator(request: Request, job_id: str = None):
        import redis.asyncio as aioredis
        from core.config import get_settings
        settings = get_settings()

        r = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
        )
        last_id = "$"
        try:
            while not await request.is_disconnected():
                results = await r.xread(
                    {"pipeline:events": last_id},
                    count=10,
                    block=1000,
                )
                if results:
                    for stream_name, messages in results:
                        for msg_id, data in messages:
                            last_id = msg_id
                            if job_id and data.get("job_id") != job_id:
                                continue
                            payload = {
                                "stage": data.get("stage"),
                                "status": data.get("status"),
                                "job_id": data.get("job_id"),
                            }
                            yield f"data: {json.dumps(payload)}\n\n"
        finally:
            await r.aclose()

    return StreamingResponse(
        real_event_generator(request, job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
