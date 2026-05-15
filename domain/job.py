from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"

class Job(BaseModel):
    id: str = Field(default_factory=lambda: f"job-{uuid.uuid4().hex[:12]}")
    scenario: str
    status: JobStatus = JobStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    anomaly_type: Optional[str] = None
    patch_type: Optional[str] = None
    deployed: bool = False
    remediation_status: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None
    awaiting_approval: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    service: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def job_id(self) -> str:
        return self.id

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 3)
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.id,
            "scenario": self.scenario,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "anomaly_type": self.anomaly_type,
            "patch_type": self.patch_type,
            "deployed": self.deployed,
            "remediation_status": self.remediation_status,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "awaiting_approval": self.awaiting_approval,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
