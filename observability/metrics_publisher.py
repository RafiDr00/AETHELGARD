from typing import Any, Dict
from core.telemetry import (
    record_pipeline_run,
    agent_span,
    pipeline_span,
)

class MetricsPublisher:
    """Publishes state transitions and agent decisions for telemetry."""

    def record_state_transition(self, job_id: str, old_state: str, new_state: str) -> None:
        # ...existing code...
        pass

    def record_agent_execution(self, agent_type: str, result: Any, duration_ms: float) -> None:
        # ...existing code...
        pass

    async def publish_stage(self, stage: str, status: str, job_id: str) -> None:
        """Publish pipeline stage update. Used by SSE stream to drive the UI."""
        from core.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info(
            "pipeline_stage_update",
            stage=stage,
            status=status,
            job_id=job_id,
        )
        # Store latest stage state in Redis if available
        try:
            import redis.asyncio as aioredis
            from core.config import get_settings
            settings = get_settings()
            r = aioredis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                decode_responses=True,
            )
            await r.setex(
                f"pipeline:stage:{job_id}",
                ttl=300,
                value=f"{stage}:{status}",
            )
            await r.xadd(
                "pipeline:events",
                {"job_id": job_id, "stage": stage, "status": status},
            )
            await r.aclose()
        except Exception:
            pass  # Publisher is non-critical — never crash the pipeline
