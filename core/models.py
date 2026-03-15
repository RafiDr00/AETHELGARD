"""
Aethelgard v2 — Core Domain Models

Pydantic models representing the core domain entities across the platform.
These models are used for event serialization, agent communication,
and persistent storage.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================
# Enums
# ============================================

class Severity(str, Enum):
    """Anomaly severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentType(str, Enum):
    """Agent classification."""
    DETECTION = "detection"
    DIAGNOSIS = "diagnosis"
    REMEDIATION = "remediation"
    VALIDATION = "validation"
    DEPLOYMENT = "deployment"


class EventType(str, Enum):
    """Event bus event types."""
    ANOMALY_DETECTED = "anomaly.detected"
    DIAGNOSIS_COMPLETE = "diagnosis.complete"
    PATCH_GENERATED = "patch.generated"
    PATCH_VALIDATED = "patch.validated"
    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_COMPLETE = "deployment.complete"
    DEPLOYMENT_FAILED = "deployment.failed"
    ROLLBACK_INITIATED = "rollback.initiated"
    ROLLBACK_COMPLETE = "rollback.complete"
    LEARNING_STORED = "learning.stored"
    HEALTH_CHECK_PASSED = "health_check.passed"
    HEALTH_CHECK_FAILED = "health_check.failed"


class PatchStatus(str, Enum):
    """Patch lifecycle states."""
    GENERATED = "generated"
    ANALYZING = "analyzing"
    TESTED = "tested"
    VALIDATED = "validated"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ServiceStatus(str, Enum):
    """Microservice health states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """Risk assessment levels."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RemediationStatus(str, Enum):
    """Canonical remediation lifecycle outcomes for telemetry and records."""
    SUCCESS = "success"
    ROLLED_BACK = "rolled_back"
    VALIDATION_FAILED = "validation_failed"
    SANDBOX_FAILED = "sandbox_failed"
    DEDUPLICATED = "deduplicated"
    AWAITING_APPROVAL = "awaiting_approval"


class FailureStage(str, Enum):
    """Pipeline stage at which remediation failed or was blocked."""
    DETECTION = "detection"
    DIAGNOSIS = "diagnosis"
    REMEDIATION = "remediation"
    VALIDATION = "validation"
    DEPLOYMENT = "deployment"
    DEDUPLICATION = "deduplication"
    UNKNOWN = "unknown"


# ============================================
# Core Models
# ============================================

class ServiceMetric(BaseModel):
    """Telemetry data point from a microservice."""
    service_name: str
    metric_name: str
    value: float
    unit: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    labels: Dict[str, str] = Field(default_factory=dict)


class LogEntry(BaseModel):
    """Structured log entry from a microservice."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service_name: str
    level: str = "INFO"
    message: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    span_id: Optional[str] = None


class Anomaly(BaseModel):
    """Detected infrastructure anomaly."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service_name: str
    anomaly_type: str
    description: str
    severity: Severity
    metrics: List[ServiceMetric] = Field(default_factory=list)
    raw_logs: List[LogEntry] = Field(default_factory=list)
    confidence: float = 0.0
    detection_latency_ms: float = 0.0


class ReActStep(BaseModel):
    """Single step in a ReAct reasoning chain."""
    step_number: int
    thought: str
    action: str
    observation: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Diagnosis(BaseModel):
    """Root cause analysis result."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    anomaly_id: str
    diagnosed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    root_cause: str
    root_cause_category: str
    # FIX #4: propagate anomaly_type for downstream template routing
    anomaly_type: str = "unknown"
    affected_components: List[str] = Field(default_factory=list)
    reasoning_chain: List[ReActStep] = Field(default_factory=list)
    confidence: float = 0.0
    knowledge_references: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)


class Patch(BaseModel):
    """Generated infrastructure patch."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    diagnosis_id: str
    anomaly_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    patch_type: str  # config_change, code_fix, scaling_action, restart
    description: str
    code_changes: Dict[str, str] = Field(default_factory=dict)  # filepath: content
    config_changes: Dict[str, Any] = Field(default_factory=dict)
    status: PatchStatus = PatchStatus.GENERATED
    reasoning_chain: List[ReActStep] = Field(default_factory=list)
    knowledge_references: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Sandbox validation outcome."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patch_id: str
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    static_analysis_passed: bool = False
    policy_check_passed: bool = False
    tests_passed: bool = False
    sandbox_execution_passed: bool = False
    risk_score: float = 1.0
    risk_level: RiskLevel = RiskLevel.HIGH
    issues: List[str] = Field(default_factory=list)
    test_results: Dict[str, Any] = Field(default_factory=dict)
    execution_logs: List[str] = Field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def is_safe_for_auto_deploy(self) -> bool:
        return self.risk_score <= 0.3 and all([
            self.static_analysis_passed,
            self.policy_check_passed,
            self.tests_passed,
            self.sandbox_execution_passed,
        ])


class DeploymentRecord(BaseModel):
    """Deployment execution record."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patch_id: str
    validation_id: str
    deployed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target_service: str
    deployment_strategy: str = "rolling"
    status: str = "pending"
    remediation_status: Optional[RemediationStatus] = None
    failure_reason: Optional[str] = None
    failure_stage: Optional[FailureStage] = None
    health_check_passed: bool = False
    rollback_triggered: bool = False
    deployment_duration_seconds: float = 0.0
    image_tag: Optional[str] = None
    previous_image_tag: Optional[str] = None


class RemediationRecord(BaseModel):
    """Complete remediation lifecycle record for learning."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    anomaly: Anomaly
    diagnosis: Diagnosis
    patch: Patch
    validation: ValidationResult
    deployment: DeploymentRecord
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    remediation_status: RemediationStatus = RemediationStatus.SUCCESS
    failure_reason: Optional[str] = None
    failure_stage: Optional[FailureStage] = None
    total_duration_seconds: float = 0.0
    was_successful: bool = False
    manual_intervention_required: bool = False

    @property
    def mttd_seconds(self) -> float:
        """Mean Time to Detect."""
        return self.anomaly.detection_latency_ms / 1000.0

    @property
    def mttr_seconds(self) -> float:
        """Mean Time to Repair."""
        return self.total_duration_seconds


class PlatformMetrics(BaseModel):
    """Aggregated platform performance technical benchmarks."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_anomalies_detected: int = 0
    total_fixes_deployed: int = 0
    total_rollbacks: int = 0
    # Engineering-focused metrics
    avg_pipeline_latency_ms: float = 0.0
    events_per_second: float = 0.0
    avg_sandbox_duration_seconds: float = 0.0
    
    autonomous_resolution_rate: float = 0.0
    active_agents: int = 5
    events_processed: int = 0
    knowledge_base_entries: int = 0


# ============================================
# Event Models (for Event Bus serialization)
# ============================================

class Event(BaseModel):
    """Base event for the event bus."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_agent: AgentType
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None

    def to_stream_data(self) -> Dict[str, str]:
        """Serialize for Redis Streams."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source_agent": self.source_agent.value,
            "payload": self.model_dump_json(),
            "correlation_id": self.correlation_id or "",
            "trace_id": self.trace_id or "",
        }

    @classmethod
    def from_stream_data(cls, data: Dict[str, str]) -> Event:
        """Deserialize from Redis Streams."""
        import json
        payload_data = json.loads(data.get("payload", "{}"))
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            event_type=EventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source_agent=AgentType(data["source_agent"]),
            payload=payload_data if isinstance(payload_data, dict) else json.loads(payload_data).get("payload", {}),
            correlation_id=data.get("correlation_id") or None,
            trace_id=data.get("trace_id") or None,
        )
