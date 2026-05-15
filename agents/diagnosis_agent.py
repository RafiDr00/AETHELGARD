"""
Aethelgard v2 — Diagnosis Agent

Root cause analysis agent that investigates detected anomalies.
Uses RAG-augmented reasoning to query the knowledge base for
similar incidents and known failure modes.

Subscribes to: anomaly.detected
Publishes: diagnosis.complete
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.config import get_settings
from core.logging_config import get_logger
from core.models import (
    AgentType,
    Anomaly,
    Diagnosis,
    EventType,
    ReActStep,
    Severity,
)

logger = get_logger(__name__)


# Root cause knowledge patterns (embedded reasoning engine)
ROOT_CAUSE_PATTERNS = {
    "latency_spike": {
        "worker_pool_exhaustion": {
            "indicators": ["response_time_ms > 2000", "cpu_usage < 0.5", "active_connections high"],
            "description": "Worker pool size insufficient for current load. Async workers saturated.",
            "category": "configuration",
            "recommended_actions": [
                "Increase async worker pool size",
                "Enable connection pooling",
                "Review async task queue configuration",
            ],
        },
        "database_bottleneck": {
            "indicators": ["response_time_ms > 1000", "db_query_time high", "connection_pool near_limit"],
            "description": "Database queries taking excessive time due to missing indexes or connection limits.",
            "category": "database",
            "recommended_actions": [
                "Add database indexes for slow queries",
                "Increase connection pool size",
                "Enable query caching",
            ],
        },
        "memory_pressure": {
            "indicators": ["response_time_ms increasing", "memory_usage > 0.9", "gc_pause_time high"],
            "description": "Memory pressure causing GC pauses and increased latency.",
            "category": "resource",
            "recommended_actions": [
                "Increase container memory limits",
                "Profile memory usage for leaks",
                "Implement request-level memory budgets",
            ],
        },
        "network_congestion": {
            "indicators": ["response_time_ms variable", "packet_loss > 0", "tcp_retransmits high"],
            "description": "Network congestion between service instances causing variable latency.",
            "category": "network",
            "recommended_actions": [
                "Review service mesh configuration",
                "Check network bandwidth allocation",
                "Enable circuit breakers",
            ],
        },
    },
    "error_rate_increase": {
        "dependency_failure": {
            "indicators": ["error_rate > 0.1", "upstream_errors high", "circuit_breaker open"],
            "description": "Upstream dependency returning errors, cascading to this service.",
            "category": "dependency",
            "recommended_actions": [
                "Enable circuit breaker for upstream calls",
                "Implement fallback responses",
                "Check upstream service health",
            ],
        },
        "resource_exhaustion": {
            "indicators": ["error_rate > 0.05", "file_descriptors near_limit", "thread_pool exhausted"],
            "description": "Service running out of system resources (file descriptors, threads).",
            "category": "resource",
            "recommended_actions": [
                "Increase resource limits in deployment",
                "Implement connection recycling",
                "Add graceful degradation",
            ],
        },
    },
    "cpu_saturation": {
        "compute_bound": {
            "indicators": ["cpu_usage > 0.95", "request_rate normal", "compute_intensive true"],
            "description": "CPU-bound operations without adequate CPU allocation.",
            "category": "resource",
            "recommended_actions": [
                "Scale horizontally (add replicas)",
                "Increase CPU limits",
                "Optimize hot code paths",
            ],
        },
    },
    "memory_pressure": {
        "memory_leak": {
            "indicators": ["memory_usage monotonically_increasing", "uptime > 24h"],
            "description": "Possible memory leak causing gradual memory exhaustion.",
            "category": "code_defect",
            "recommended_actions": [
                "Profile memory allocations",
                "Implement periodic restart policy",
                "Review object lifecycle management",
            ],
        },
    },
    "queue_buildup": {
        "consumer_lag": {
            "indicators": ["queue_depth increasing", "consumer_rate < producer_rate"],
            "description": "Message consumers cannot keep up with producer rate.",
            "category": "scaling",
            "recommended_actions": [
                "Scale consumer instances",
                "Increase consumer batch size",
                "Implement backpressure signaling",
            ],
        },
    },
}


class DiagnosisAgent(BaseAgent):
    """
    Root cause analysis agent using pattern matching and RAG knowledge retrieval.
    
    Investigates anomalies through a structured reasoning process:
    1. Analyze anomaly characteristics and metrics
    2. Query knowledge base for similar incidents
    3. Match against known root cause patterns
    4. Correlate with service topology
    5. Produce a diagnosis with confidence score
    """

    def __init__(self, knowledge_engine=None):
        super().__init__(AgentType.DIAGNOSIS)
        self._knowledge_engine = knowledge_engine
        self._confidence_threshold = get_settings().agents.diagnosis_confidence_threshold

    async def _setup_subscriptions(self) -> None:
        """Subscribe to anomaly detection events."""
        if self._event_bus:
            await self._event_bus.subscribe(
                streams=[EventType.ANOMALY_DETECTED.value],
                handler=self.handle_event,
                consumer_name=self.agent_id,
            )

    async def diagnose(self, anomaly: Anomaly) -> Diagnosis:
        """
        Primary entry point for diagnosing an anomaly.
        
        Args:
            anomaly: The detected anomaly to diagnose
            
        Returns:
            Diagnosis with root cause, reasoning chain, and recommendations
        """
        context = {
            "anomaly": anomaly.model_dump(mode="json"),
            "anomaly_id": anomaly.id,
            "service_name": anomaly.service_name,
            "anomaly_type": anomaly.anomaly_type,
            "severity": anomaly.severity.value,
            "correlation_id": anomaly.id,
        }

        result = await self.execute_react_loop(context)
        diagnosis = result.get("diagnosis")
        if diagnosis:
            diagnosis.reasoning_chain = result.get("reasoning_chain", diagnosis.reasoning_chain)
        return diagnosis

    async def think(self, context: Dict[str, Any]) -> str:
        """Reason about the anomaly using available evidence."""
        iteration = context.get("iteration", 1)
        anomaly_type = context.get("anomaly_type", "unknown")
        service_name = context.get("service_name", "unknown")
        severity = context.get("severity", "unknown")

        if iteration == 1:
            # First iteration: analyze the anomaly characteristics
            anomaly_data = context.get("anomaly", {})
            metrics_summary = []
            for m in anomaly_data.get("metrics", []):
                metrics_summary.append(f"{m.get('metric_name')}: {m.get('value')}")

            return (
                f"Analyzing anomaly in service '{service_name}': "
                f"type={anomaly_type}, severity={severity}. "
                f"Metrics: {', '.join(metrics_summary) if metrics_summary else 'N/A'}. "
                f"Need to identify the root cause by examining known patterns "
                f"and querying the knowledge base."
            )

        elif iteration == 2:
            # Second iteration: evaluate knowledge base results
            knowledge_results = context.get("knowledge_results", [])
            pattern_matches = context.get("pattern_matches", {})

            return (
                f"Knowledge base returned {len(knowledge_results)} relevant entries. "
                f"Found {len(pattern_matches)} matching root cause patterns. "
                f"Evaluating best match based on confidence and indicator overlap."
            )

        else:
            # Third+ iteration: finalize diagnosis
            return (
                f"Sufficient evidence gathered. Preparing final diagnosis for "
                f"{service_name}/{anomaly_type} with root cause determination."
            )

    async def act(self, thought: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute diagnostic actions based on current reasoning."""
        iteration = context.get("iteration", 1)
        anomaly_type = context.get("anomaly_type", "unknown")

        if iteration == 1:
            # Action 1: Query knowledge base + pattern matching
            knowledge_results = await self._query_knowledge(anomaly_type, context)
            pattern_matches = self._match_patterns(anomaly_type, context)

            return {
                "knowledge_results": knowledge_results,
                "pattern_matches": pattern_matches,
            }

        elif iteration == 2:
            # Action 2: Determine root cause
            pattern_matches = context.get("pattern_matches", {})
            root_cause = self._select_root_cause(pattern_matches, context)

            return {
                "root_cause": root_cause,
                "confidence": root_cause.get("confidence", 0),
            }

        else:
            # Action 3: Build diagnosis object
            root_cause = context.get("root_cause", {})
            diagnosis = self._build_diagnosis(root_cause, context)
            return {"diagnosis": diagnosis}

    async def observe(self, action_result: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Observe results of diagnostic actions."""
        iteration = context.get("iteration", 1)

        if iteration == 1:
            knowledge_count = len(action_result.get("knowledge_results", []))
            pattern_count = len(action_result.get("pattern_matches", {}))
            context["knowledge_results"] = action_result["knowledge_results"]
            context["pattern_matches"] = action_result["pattern_matches"]
            return (
                f"Retrieved {knowledge_count} knowledge entries and "
                f"matched {pattern_count} root cause patterns."
            )

        elif iteration == 2:
            root_cause = action_result.get("root_cause", {})
            confidence = action_result.get("confidence", 0)
            context["root_cause"] = root_cause
            return (
                f"Root cause identified: {root_cause.get('description', 'unknown')} "
                f"(confidence: {confidence:.2f})"
            )

        else:
            diagnosis = action_result.get("diagnosis")
            context["diagnosis"] = diagnosis
            return f"Diagnosis complete: {diagnosis.root_cause if diagnosis else 'unknown'}"

    async def decide(self, context: Dict[str, Any]) -> bool:
        """Complete after building the diagnosis (iteration 3)."""
        return context.get("iteration", 0) >= 3

    async def emit_result(self, context: Dict[str, Any]) -> None:
        """Emit diagnosis result to event bus."""
        diagnosis = context.get("diagnosis")
        if not diagnosis:
            return

        await self.publish_event(
            EventType.DIAGNOSIS_COMPLETE,
            payload=diagnosis.model_dump(mode="json"),
            correlation_id=context.get("correlation_id"),
        )

        logger.info(
            "diagnosis_emitted",
            diagnosis_id=diagnosis.id,
            root_cause=diagnosis.root_cause,
            confidence=diagnosis.confidence,
        )

    async def _query_knowledge(self, anomaly_type: str, context: Dict[str, Any]) -> List[Dict]:
        """Query the RAG knowledge base for relevant remediation knowledge."""
        if self._knowledge_engine:
            try:
                query = f"{anomaly_type} root cause analysis remediation"
                results = await self._knowledge_engine.query(query, top_k=5)
                return results
            except Exception as e:
                logger.warning("knowledge_query_failed", error=str(e))

        # Fallback: return embedded knowledge
        return [
            {
                "source": "embedded_patterns",
                "content": f"Known patterns for {anomaly_type}",
                "relevance": 0.85,
            }
        ]

    def _match_patterns(self, anomaly_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Match anomaly against known root cause patterns."""
        patterns = ROOT_CAUSE_PATTERNS.get(anomaly_type, {})
        if not patterns:
            return {"unknown": {"description": "No matching pattern found", "confidence": 0.3}}

        matches = {}
        anomaly_data = context.get("anomaly", {})
        metrics = {m.get("metric_name"): m.get("value") for m in anomaly_data.get("metrics", [])}

        for cause_name, cause_info in patterns.items():
            # Simple indicator matching for this iteration
            match_score = 0.6  # Base score for type match
            indicators = cause_info.get("indicators", [])

            # Boost score based on metric values
            for indicator in indicators:
                for metric_name, metric_value in metrics.items():
                    if metric_name in indicator:
                        match_score += 0.1

            matches[cause_name] = {
                **cause_info,
                "confidence": min(match_score, 0.95),
            }

        return matches

    def _select_root_cause(self, pattern_matches: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Select the most likely root cause from matched patterns."""
        if not pattern_matches:
            return {
                "cause": "unknown",
                "description": "Unable to determine root cause",
                "confidence": 0.0,
                "category": "unknown",
                "recommended_actions": ["Manual investigation required"],
            }

        # Select highest confidence match
        best_cause = max(
            pattern_matches.items(),
            key=lambda x: x[1].get("confidence", 0),
        )

        return {
            "cause": best_cause[0],
            **best_cause[1],
        }

    def _build_diagnosis(self, root_cause: Dict[str, Any], context: Dict[str, Any]) -> Diagnosis:
        """Build the final Diagnosis model."""
        anomaly_data = context.get("anomaly", {})

        return Diagnosis(
            anomaly_id=context.get("anomaly_id", ""),
            anomaly_type=context.get("anomaly_type", "unknown"),  # FIX #4
            root_cause=root_cause.get("description", "Unknown root cause"),
            root_cause_category=root_cause.get("category", "unknown"),
            affected_components=[context.get("service_name", "unknown")],
            reasoning_chain=context.get("reasoning_chain", []),
            confidence=root_cause.get("confidence", 0.0),
            knowledge_references=[
                r.get("source", "") for r in context.get("knowledge_results", [])
            ],
            recommended_actions=root_cause.get("recommended_actions", []),
        )
