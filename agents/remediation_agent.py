"""
Aethelgard v2 — Remediation Agent

Generates infrastructure patches based on diagnosis results.
Uses RAG-augmented knowledge to produce contextually appropriate fixes
following best practices from the knowledge base.

Subscribes to: diagnosis.complete
Publishes: patch.generated
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.config import get_settings
from core.logging_config import get_logger
from core.models import (
    AgentType,
    Diagnosis,
    EventType,
    Patch,
    PatchStatus,
)

logger = get_logger(__name__)


# Remediation templates organized by root cause category
REMEDIATION_TEMPLATES = {
    "worker_pool_exhaustion": {
        "patch_type": "config_change",
        "description": "Increase async worker pool size to handle current load",
        "code_changes": {
            "config/server.py": textwrap.dedent("""\
                # Aethelgard Auto-Generated Fix
                # Root Cause: Worker pool exhaustion
                # Action: Increase worker pool from {old_workers} to {new_workers}
                
                import uvicorn
                from fastapi import FastAPI
                
                app = FastAPI(title="Service")
                
                if __name__ == "__main__":
                    uvicorn.run(
                        "main:app",
                        host="0.0.0.0",
                        port=8000,
                        workers={new_workers},
                        loop="uvloop",
                        http="httptools",
                        limit_concurrency=1000,
                        timeout_keep_alive=30,
                    )
            """),
        },
        "config_changes": {
            "workers": "{new_workers}",
            "limit_concurrency": 1000,
            "timeout_keep_alive": 30,
            "loop": "uvloop",
        },
        "parameters": {
            "old_workers": 2,
            "new_workers": 8,
        },
    },
    "database_bottleneck": {
        "patch_type": "config_change",
        "description": "Optimize database connection pool and enable query caching",
        "code_changes": {
            "config/database.py": textwrap.dedent("""\
                # Aethelgard Auto-Generated Fix
                # Root Cause: Database bottleneck
                # Action: Increase connection pool and enable caching
                
                from sqlalchemy import create_engine
                from sqlalchemy.pool import QueuePool
                
                engine = create_engine(
                    DATABASE_URL,
                    poolclass=QueuePool,
                    pool_size={pool_size},
                    max_overflow={max_overflow},
                    pool_timeout=30,
                    pool_recycle=1800,
                    pool_pre_ping=True,
                    echo=False,
                )
                
                # Enable query result caching
                QUERY_CACHE_TTL = 300  # 5 minutes
                QUERY_CACHE_MAX_SIZE = 1000
            """),
        },
        "config_changes": {
            "pool_size": "{pool_size}",
            "max_overflow": "{max_overflow}",
            "pool_timeout": 30,
            "pool_recycle": 1800,
        },
        "parameters": {
            "pool_size": 20,
            "max_overflow": 40,
        },
    },
    "memory_pressure": {
        "patch_type": "scaling_action",
        "description": "Increase container memory limits and optimize resource allocation",
        "code_changes": {
            "kubernetes/deployment-patch.yaml": textwrap.dedent("""\
                # Aethelgard Auto-Generated Fix
                # Root Cause: Memory pressure
                # Action: Increase memory limits
                
                apiVersion: apps/v1
                kind: Deployment
                metadata:
                  name: {service_name}
                spec:
                  template:
                    spec:
                      containers:
                      - name: {service_name}
                        resources:
                          requests:
                            memory: "{memory_request}"
                            cpu: "{cpu_request}"
                          limits:
                            memory: "{memory_limit}"
                            cpu: "{cpu_limit}"
            """),
        },
        "config_changes": {
            "memory_request": "{memory_request}",
            "memory_limit": "{memory_limit}",
            "cpu_request": "{cpu_request}",
            "cpu_limit": "{cpu_limit}",
        },
        "parameters": {
            "memory_request": "512Mi",
            "memory_limit": "1Gi",
            "cpu_request": "250m",
            "cpu_limit": "1000m",
        },
    },
    "compute_bound": {
        "patch_type": "scaling_action",
        "description": "Scale service horizontally to distribute CPU load",
        "code_changes": {
            "kubernetes/hpa-patch.yaml": textwrap.dedent("""\
                # Aethelgard Auto-Generated Fix
                # Root Cause: CPU saturation (compute bound)
                # Action: Enable horizontal pod autoscaler
                
                apiVersion: autoscaling/v2
                kind: HorizontalPodAutoscaler
                metadata:
                  name: {service_name}-hpa
                spec:
                  scaleTargetRef:
                    apiVersion: apps/v1
                    kind: Deployment
                    name: {service_name}
                  minReplicas: {min_replicas}
                  maxReplicas: {max_replicas}
                  metrics:
                  - type: Resource
                    resource:
                      name: cpu
                      target:
                        type: Utilization
                        averageUtilization: 70
            """),
        },
        "config_changes": {
            "min_replicas": "{min_replicas}",
            "max_replicas": "{max_replicas}",
            "target_cpu_utilization": 70,
        },
        "parameters": {
            "min_replicas": 3,
            "max_replicas": 10,
        },
    },
    "consumer_lag": {
        "patch_type": "scaling_action",
        "description": "Scale message consumers and increase batch processing size",
        "code_changes": {
            "config/consumer.py": textwrap.dedent("""\
                # Aethelgard Auto-Generated Fix
                # Root Cause: Consumer lag (queue buildup)
                # Action: Scale consumers and increase batch size
                
                CONSUMER_CONFIG = {{
                    "num_consumers": {num_consumers},
                    "batch_size": {batch_size},
                    "max_poll_interval_ms": 300000,
                    "session_timeout_ms": 10000,
                    "auto_offset_reset": "latest",
                    "enable_auto_commit": True,
                    "auto_commit_interval_ms": 5000,
                }}
            """),
        },
        "config_changes": {
            "num_consumers": "{num_consumers}",
            "batch_size": "{batch_size}",
        },
        "parameters": {
            "num_consumers": 5,
            "batch_size": 100,
        },
    },
    "dependency_failure": {
        "patch_type": "code_fix",
        "description": "Implement circuit breaker and fallback for upstream dependency",
        "code_changes": {
            "middleware/circuit_breaker.py": textwrap.dedent("""\
                # Aethelgard Auto-Generated Fix
                # Root Cause: Dependency failure
                # Action: Add circuit breaker with fallback
                
                import asyncio
                from enum import Enum
                from datetime import datetime, timedelta
                
                
                class CircuitState(Enum):
                    CLOSED = "closed"
                    OPEN = "open"
                    HALF_OPEN = "half_open"
                
                
                class CircuitBreaker:
                    def __init__(
                        self,
                        failure_threshold: int = {failure_threshold},
                        recovery_timeout: int = {recovery_timeout},
                        half_open_max_calls: int = 3,
                    ):
                        self.failure_threshold = failure_threshold
                        self.recovery_timeout = timedelta(seconds=recovery_timeout)
                        self.half_open_max_calls = half_open_max_calls
                        self.state = CircuitState.CLOSED
                        self.failure_count = 0
                        self.last_failure_time = None
                        self.half_open_calls = 0
                
                    async def call(self, func, *args, fallback=None, **kwargs):
                        if self.state == CircuitState.OPEN:
                            if self._should_try_reset():
                                self.state = CircuitState.HALF_OPEN
                                self.half_open_calls = 0
                            elif fallback:
                                return await fallback(*args, **kwargs)
                            else:
                                raise Exception("Circuit breaker is OPEN")
                
                        try:
                            result = await func(*args, **kwargs)
                            self._on_success()
                            return result
                        except Exception as e:
                            self._on_failure()
                            if fallback:
                                return await fallback(*args, **kwargs)
                            raise
                
                    def _on_success(self):
                        self.failure_count = 0
                        self.state = CircuitState.CLOSED
                
                    def _on_failure(self):
                        self.failure_count += 1
                        self.last_failure_time = datetime.utcnow()
                        if self.failure_count >= self.failure_threshold:
                            self.state = CircuitState.OPEN
                
                    def _should_try_reset(self) -> bool:
                        if self.last_failure_time is None:
                            return True
                        return datetime.utcnow() - self.last_failure_time > self.recovery_timeout
            """),
        },
        "config_changes": {
            "failure_threshold": "{failure_threshold}",
            "recovery_timeout": "{recovery_timeout}",
        },
        "parameters": {
            "failure_threshold": 5,
            "recovery_timeout": 30,
        },
    },
}


class RemediationAgent(BaseAgent):
    """
    Patch generation agent using templated remediation with RAG augmentation.
    
    Generates infrastructure patches by:
    1. Analyzing the diagnosis and root cause
    2. Querying knowledge base for best practices
    3. Selecting appropriate remediation template
    4. Parameterizing the fix for the specific context
    5. Producing a Patch object with code/config changes
    """

    def __init__(self, knowledge_engine=None):
        super().__init__(AgentType.REMEDIATION)
        self._knowledge_engine = knowledge_engine

    @staticmethod
    def _infer_anomaly_type(diagnosis: Diagnosis, diagnosis_dict: Dict[str, Any]) -> str:
        """Infer a stable anomaly type when diagnosis metadata omits it."""
        explicit = diagnosis_dict.get("anomaly_type")
        if explicit and explicit != "unknown":
            return explicit

        root_cause = (diagnosis.root_cause or "").lower()
        category = (diagnosis.root_cause_category or "").lower()
        actions = " ".join(diagnosis.recommended_actions or []).lower()
        evidence = " ".join([root_cause, category, actions])

        if any(k in evidence for k in ("worker", "latency", "response_time", "uvicorn", "pool")):
            return "latency_spike"
        if any(k in evidence for k in ("dependency", "upstream", "circuit breaker")):
            return "error_rate_increase"
        if any(k in evidence for k in ("cpu", "compute", "replica", "scale")):
            return "cpu_saturation"
        if any(k in evidence for k in ("memory", "gc", "leak")):
            return "memory_pressure"
        if any(k in evidence for k in ("queue", "consumer", "lag")):
            return "queue_buildup"
        return "unknown"

    @staticmethod
    def _fallback_template(context: Dict[str, Any]) -> Dict[str, Any]:
        """Safe fallback template used when no canonical template can be selected."""
        service = (context.get("affected_components") or ["service"])[0]
        return {
            "patch_type": "config_change",
            "description": "Escalation-safe fallback patch: route to manual review with conservative defaults",
            "code_changes": {
                "ops/manual_remediation_required.md": (
                    "# Aethelgard Manual Remediation Required\n"
                    f"- Service: {service}\n"
                    f"- Root cause: {context.get('root_cause', 'unknown')}\n"
                    "- Reason: no matching remediation template\n"
                )
            },
            "config_changes": {
                "manual_intervention_required": True,
                "auto_deploy": False,
            },
            "parameters": {},
        }

    async def _setup_subscriptions(self) -> None:
        """Subscribe to diagnosis completion events."""
        if self._event_bus:
            await self._event_bus.subscribe(
                streams=[EventType.DIAGNOSIS_COMPLETE.value],
                handler=self.handle_event,
                consumer_name=self.agent_id,
            )

    async def generate_patch(self, diagnosis: Diagnosis) -> Patch:
        """
        Generate a remediation patch for a given diagnosis.
        
        Args:
            diagnosis: The completed diagnosis to remediate
            
        Returns:
            Patch object with code and config changes
        """
        # FIX #4 — Include anomaly_type as primary discriminator
        diagnosis_dict = diagnosis.model_dump(mode="json")
        inferred_anomaly_type = self._infer_anomaly_type(diagnosis, diagnosis_dict)
        context = {
            "diagnosis": diagnosis_dict,
            "diagnosis_id": diagnosis.id,
            "anomaly_id": diagnosis.anomaly_id,
            "root_cause": diagnosis.root_cause,
            "root_cause_category": diagnosis.root_cause_category,
            "affected_components": diagnosis.affected_components,
            "recommended_actions": diagnosis.recommended_actions,
            "correlation_id": diagnosis.anomaly_id,
            # Propagate anomaly_type from diagnosis metadata; infer if absent
            "anomaly_type": inferred_anomaly_type,
        }

        result = await self.execute_react_loop(context)
        return result.get("patch")

    async def think(self, context: Dict[str, Any]) -> str:
        """Reason about the appropriate remediation strategy."""
        iteration = context.get("iteration", 1)
        root_cause = context.get("root_cause", "unknown")
        category = context.get("root_cause_category", "unknown")
        actions = context.get("recommended_actions", [])

        if iteration == 1:
            return (
                f"Diagnosis indicates root cause: '{root_cause}' "
                f"(category: {category}). "
                f"Recommended actions: {actions}. "
                f"Need to query knowledge base for best practices and "
                f"select appropriate remediation template."
            )
        elif iteration == 2:
            template_name = context.get("selected_template", "unknown")
            return (
                f"Selected remediation template: '{template_name}'. "
                f"Parameterizing fix for the specific service context. "
                f"Generating code and configuration changes."
            )
        else:
            return "Building final patch object with all changes."

    async def act(self, thought: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remediation actions."""
        iteration = context.get("iteration", 1)

        if iteration == 1:
            # Select template and gather knowledge
            template_name, template = self._select_template(context)

            # Handle escalation: unknown anomaly_type with no template match
            if template_name is None:
                logger.warning(
                    "remediation_escalation",
                    anomaly_type=context.get("anomaly_type"),
                    action="no_safe_template_available"
                )
                # Mark as requiring human intervention, but never return a null template.
                context["requires_escalation"] = True
                template = self._fallback_template(context)
                return {
                    "selected_template": "manual_escalation_fallback",
                    "template": template,
                    "knowledge": [],
                    "escalation_required": True,
                }

            knowledge = await self._query_remediation_knowledge(context)
            return {
                "selected_template": template_name,
                "template": template,
                "knowledge": knowledge,
            }
        elif iteration == 2:
            # Generate parameterized code
            template = context.get("template") or {}
            code_changes = self._generate_code(template, context)
            config_changes = self._generate_config(template, context)

            return {
                "code_changes": code_changes,
                "config_changes": config_changes,
            }
        else:
            # Build patch
            patch = self._build_patch(context)
            return {"patch": patch}

    async def observe(self, action_result: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Observe remediation action results."""
        iteration = context.get("iteration", 1)

        if iteration == 1:
            template_name = action_result.get("selected_template")
            context["selected_template"] = template_name
            context["template"] = action_result.get("template") or {}
            return f"Template '{template_name}' selected with remediation strategy."

        elif iteration == 2:
            code_changes = action_result.get("code_changes", {})
            config_changes = action_result.get("config_changes", {})
            context["code_changes"] = code_changes
            context["config_changes"] = config_changes
            return (
                f"Generated {len(code_changes)} code changes and "
                f"{len(config_changes)} config changes."
            )
        else:
            patch = action_result.get("patch")
            context["patch"] = patch
            return f"Patch {patch.id if patch else 'N/A'} created successfully."

    async def decide(self, context: Dict[str, Any]) -> bool:
        """Complete after building the patch (iteration 3)."""
        return context.get("iteration", 0) >= 3

    async def emit_result(self, context: Dict[str, Any]) -> None:
        """Emit patch generation event."""
        patch = context.get("patch")
        if not patch:
            return

        await self.publish_event(
            EventType.PATCH_GENERATED,
            payload=patch.model_dump(mode="json"),
            correlation_id=context.get("correlation_id"),
        )

        logger.info(
            "patch_generated",
            patch_id=patch.id,
            patch_type=patch.patch_type,
            num_code_changes=len(patch.code_changes),
        )

    # FIX #4 — Anomaly-type-first template routing
    # Each anomaly_type has a canonical primary template.
    # Root cause text is used only to disambiguate within a family.
    # Unknown types return (None, None) → pipeline escalates for human review.

    # Primary routing table: anomaly_type → ordered list of candidate templates
    ANOMALY_TYPE_TEMPLATES = {
        "latency_spike":        ["worker_pool_exhaustion", "database_bottleneck", "memory_pressure"],
        "error_rate_increase":  ["dependency_failure", "worker_pool_exhaustion"],
        "cpu_saturation":       ["compute_bound", "worker_pool_exhaustion"],
        "memory_pressure":      ["memory_pressure", "compute_bound"],
        "queue_buildup":        ["consumer_lag", "worker_pool_exhaustion"],
        "connection_exhaustion":["worker_pool_exhaustion", "database_bottleneck"],
        "disk_saturation":      ["compute_bound"],
        "unknown":              [],  # always escalates
    }

    def _select_template(self, context: Dict[str, Any]) -> tuple:
        """
        FIX #4: Anomaly-type-first template selection.

        Algorithm:
          1. Use anomaly_type to narrow candidate template list
          2. Within candidates, pick best match using root_cause text
          3. If no candidates exist for this anomaly_type → return (None, None)
             so the orchestrator can escalate rather than apply a wrong fix
        """
        diagnosis = context.get("diagnosis", {})
        anomaly_type = context.get("anomaly_type", "unknown")
        root_cause = diagnosis.get("root_cause", "").lower()
        recommended_actions = diagnosis.get("recommended_actions", [])
        root_cause_category = diagnosis.get("root_cause_category", "").lower()

        # Step 1: Get candidates for this anomaly type
        candidates = self.ANOMALY_TYPE_TEMPLATES.get(
            anomaly_type,
            self.ANOMALY_TYPE_TEMPLATES.get("unknown", [])
        )

        if not candidates:
            logger.warning(
                "template_no_candidates",
                anomaly_type=anomaly_type,
                action="escalating_to_human_review"
            )
            return None, None  # Caller must handle escalation

        # Step 2: Score each candidate against root cause evidence
        def score_candidate(template_name: str) -> float:
            score = 0.0
            # Direct template name match in root cause
            if template_name.replace("_", " ") in root_cause:
                score += 1.0
            # Category match
            template = REMEDIATION_TEMPLATES.get(template_name, {})
            template_desc = template.get("description", "").lower()
            for word in root_cause.split():
                if len(word) > 4 and word in template_desc:
                    score += 0.2
            # Recommended action match
            action_keywords = {
                "worker_pool_exhaustion": ["worker", "pool", "async", "uvicorn"],
                "database_bottleneck": ["database", "db", "query", "connection pool"],
                "memory_pressure": ["memory", "limit", "gc", "leak"],
                "compute_bound": ["scale", "replica", "cpu", "horizontal"],
                "consumer_lag": ["consumer", "queue", "batch", "lag"],
                "dependency_failure": ["circuit", "fallback", "upstream", "dependency"],
            }
            keywords = action_keywords.get(template_name, [])
            for action in recommended_actions:
                action_lower = action.lower()
                for kw in keywords:
                    if kw in action_lower:
                        score += 0.3
            return score

        # Pick highest-scoring candidate
        scored = [(name, score_candidate(name)) for name in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_name, best_score = scored[0]

        logger.info(
            "template_selected",
            anomaly_type=anomaly_type,
            template=best_name,
            score=round(best_score, 2),
            candidates=candidates,
        )

        return best_name, REMEDIATION_TEMPLATES[best_name]

    async def _query_remediation_knowledge(self, context: Dict[str, Any]) -> List[Dict]:
        """Query knowledge base for remediation best practices."""
        if self._knowledge_engine:
            try:
                query = (
                    f"remediation {context.get('root_cause_category', '')} "
                    f"{context.get('root_cause', '')}"
                )
                return await self._knowledge_engine.query(query, top_k=3)
            except Exception as e:
                logger.warning("knowledge_query_failed", error=str(e))
        return []

    def _generate_code(self, template: Dict, context: Dict[str, Any]) -> Dict[str, str]:
        """Generate parameterized code changes from template."""
        code_changes = {}
        params = template.get("parameters", {})

        # Add service-specific parameters
        affected = context.get("affected_components", ["service"])
        params["service_name"] = affected[0] if affected else "service"

        for filepath, code_template in template.get("code_changes", {}).items():
            try:
                code = code_template.format(**params)
                code_changes[filepath] = code
            except KeyError as e:
                logger.warning("template_param_missing", param=str(e), file=filepath)
                code_changes[filepath] = code_template

        return code_changes

    def _generate_config(self, template: Dict, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        FIX #6 — Generate configuration changes with REAL typed values.

        Previous bug: value_template.format(**params) always returned a
        string, so `workers: "{new_workers}"` came out as `workers: "8"`
        (a string, not an integer). Downstream systems receiving this config
        would fail on type validation.

        Fix: When a placeholder maps to a numeric value in params,
        return the numeric value directly, not the formatted string.
        """
        config_changes = {}
        params = template.get("parameters", {})

        for key, value_template in template.get("config_changes", {}).items():
            if isinstance(value_template, str):
                # Extract placeholder name, e.g. "{new_workers}" -> "new_workers"
                stripped = value_template.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    param_name = stripped[1:-1]   # pure single placeholder
                    if param_name in params:
                        # Return the actual typed value (int | float | str)
                        config_changes[key] = params[param_name]
                    else:
                        logger.warning("config_param_missing",
                                       key=key, placeholder=param_name)
                        config_changes[key] = value_template  # keep as-is
                elif "{" in stripped:
                    # Mixed string: still use str.format but log the result
                    try:
                        resolved = value_template.format(**params)
                        config_changes[key] = resolved
                        logger.debug("config_mixed_template_resolved",
                                     key=key, result=resolved)
                    except KeyError as e:
                        logger.warning("config_template_error", key=key, error=str(e))
                        config_changes[key] = value_template
                else:
                    # Literal string, no placeholders
                    config_changes[key] = value_template
            else:
                # Already a typed value (int, float, bool, list, dict)
                config_changes[key] = value_template

        return config_changes

    def _build_patch(self, context: Dict[str, Any]) -> Patch:
        """Build the final Patch model."""
        template = context.get("template") or {}
        return Patch(
            diagnosis_id=context.get("diagnosis_id", ""),
            anomaly_id=context.get("anomaly_id", ""),
            patch_type=template.get("patch_type", "config_change"),
            description=template.get("description", "Auto-generated patch"),
            code_changes=context.get("code_changes", {}),
            config_changes=context.get("config_changes", {}),
            status=PatchStatus.GENERATED,
            reasoning_chain=context.get("reasoning_chain", []),
            knowledge_references=[
                r.get("source", "") for r in context.get("knowledge", [])
            ],
        )
