from typing import Any, Dict
from core.telemetry import (
    record_pipeline_run,
    agent_span,
    pipeline_span,
)

class MetricsPublisher:
    """Publishes state transitions and agent decisions for telemetry."""
    
    def record_state_transition(self, job_id: str, old_state: str, new_state: str) -> None:
        """Emits a metric or log for state changes."""
        # Intentionally passing through currently
        pass

    def record_agent_execution(self, agent_type: str, result: Any, duration_ms: float) -> None:
        """Emits metrics about an agent's reasoning iteration."""
        # Intentionally passing through currently
        pass
