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

@router.get("/log-stream")
async def log_stream(
    request: Request,
    burst: int = Query(1, ge=0, le=200),
    interval_ms: int = Query(1000, ge=10, le=5000),
):
    simulator = getattr(request.app.state, "simulator", None)
    
    async def event_generator():
        log_queue = asyncio.Queue(maxsize=1000)
        last_heartbeat = time.time()

        try:
            while not await request.is_disconnected():
                now = time.time()
                
                if burst > 0 and simulator:
                    for log_entry in simulator.generate_logs(count=burst):
                        payload = _sse_log_payload(log_entry)
                        
                        if not payload.get("span_id"):
                            payload["span_id"] = f"span-{payload.get('stage', 'detection')}"

                        if log_queue.full():
                            try:
                                log_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        log_queue.put_nowait(payload)

                sent_any = False
                while not log_queue.empty():
                    event = log_queue.get_nowait()
                    event_id = str(event.get("id", "")) or f"evt-{int(time.time() * 1000)}"
                    
                    yield f"id: {event_id}\n"
                    yield "retry: 3000\n"
                    # Default handling for datetime if present
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                    sent_any = True

                if sent_any:
                    last_heartbeat = now
                elif now - last_heartbeat > 12.0:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now

                await asyncio.sleep(interval_ms / 1000.0)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("sse_log_stream_closed", client=str(getattr(request, "client", "unknown")))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
