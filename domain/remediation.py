from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class RemediationAction(BaseModel):
    id: str
    action_type: str  # config_change, code_fix, scaling_action, restart
    parameters: Dict[str, Any] = Field(default_factory=dict)
    expected_outcome: Optional[str] = None
    target_service: str
    description: str
    status: str = "generated"
