from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Anomaly(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service_name: str
    anomaly_type: str
    description: str
    severity: Severity
    metrics: List[Any] = Field(default_factory=list)
    raw_logs: List[Any] = Field(default_factory=list)
    confidence: float = 0.0
    detection_latency_ms: float = 0.0
    fingerprint: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
