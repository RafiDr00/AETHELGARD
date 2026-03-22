"""
Aethelgard — Diagnosis Agent

Root cause analysis agent that investigates detected anomalies.
Uses RAG-augmented reasoning to query the knowledge base for
similar incidents and known failure modes.

Subscribes to: anomaly.detected
Publishes: diagnosis.complete
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

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
            knowledge_results = context.get("knowledge_results", [])

            anomaly_data = context.get("anomaly", {})
            llm_diagnosis = await self.generate_llm_diagnosis(
                metrics=anomaly_data.get("metrics", []),
                anomaly={
                    "service_name": context.get("service_name"),
                    "anomaly_type": context.get("anomaly_type"),
                    "severity": context.get("severity"),
                    "description": anomaly_data.get("description"),
                },
                rag_context=knowledge_results,
            )

            root_cause = {
                "cause": "llm_diagnosis",
                "description": llm_diagnosis.get("root_cause", "Unknown root cause"),
                "confidence": llm_diagnosis.get("confidence", 0.0),
                "category": "llm_inferred",
                "recommended_actions": [
                    llm_diagnosis.get("remediation_strategy", "Manual investigation required")
                ],
                "reasoning": llm_diagnosis.get("reasoning", ""),
            }

            if root_cause["confidence"] < self._confidence_threshold:
                rule_based = self._select_root_cause(pattern_matches, context)
                if rule_based.get("confidence", 0.0) >= root_cause["confidence"]:
                    root_cause = rule_based

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

    async def generate_llm_diagnosis(
        self,
        metrics: List[Dict[str, Any]],
        anomaly: Dict[str, Any],
        rag_context: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate diagnosis using configured LLM provider (OpenAI/Ollama).

        Returns JSON shape:
        {
          root_cause: string,
          reasoning: string,
          remediation_strategy: string,
          confidence: number
        }
        Falls back to rule-based diagnosis when LLM is unavailable.
        """
        settings = get_settings()
        llm_cfg = settings.llm
        provider = (llm_cfg.provider or "openai").strip().lower()

        prompt = self._build_llm_diagnosis_prompt(metrics, anomaly, rag_context)

        try:
            if provider == "ollama":
                content = await self._call_ollama(prompt)
            else:
                content = await self._call_openai(prompt)

            parsed = self._parse_llm_diagnosis_json(content)
            return {
                "root_cause": str(parsed.get("root_cause", "Unknown root cause")),
                "reasoning": str(parsed.get("reasoning", "Insufficient reasoning provided")),
                "remediation_strategy": str(
                    parsed.get("remediation_strategy", "Manual investigation required")
                ),
                "confidence": self._normalize_confidence(parsed.get("confidence", 0.0)),
            }
        except Exception as exc:
            logger.warning(
                "llm_diagnosis_fallback",
                error=str(exc),
                provider=provider,
                anomaly_type=anomaly.get("anomaly_type"),
            )
            return self._generate_rule_based_llm_fallback(metrics, anomaly)

    def _build_llm_diagnosis_prompt(
        self,
        metrics: List[Dict[str, Any]],
        anomaly: Dict[str, Any],
        rag_context: List[Dict[str, Any]],
    ) -> str:
        metrics_summary = []
        for metric in metrics[:10]:
            name = metric.get("metric_name", "unknown")
            value = metric.get("value", "n/a")
            unit = metric.get("unit", "")
            metrics_summary.append(f"- {name}: {value}{unit}")

        anomaly_description = (
            f"service={anomaly.get('service_name', 'unknown')}; "
            f"type={anomaly.get('anomaly_type', 'unknown')}; "
            f"severity={anomaly.get('severity', 'unknown')}; "
            f"description={anomaly.get('description', 'n/a')}"
        )

        rag_snippets = []
        for item in rag_context[:5]:
            source = item.get("source", "unknown")
            content = str(item.get("content", "")).strip()
            if content:
                rag_snippets.append(f"- [{source}] {content[:500]}")

        return (
            "You are a senior SRE assistant. Diagnose the production anomaly using provided context. "
            "Return ONLY strict JSON with keys: root_cause, reasoning, remediation_strategy, confidence. "
            "confidence must be a number between 0 and 1.\n\n"
            f"Metrics summary:\n{chr(10).join(metrics_summary) if metrics_summary else '- none provided'}\n\n"
            f"Anomaly description:\n- {anomaly_description}\n\n"
            f"RAG playbook snippets:\n{chr(10).join(rag_snippets) if rag_snippets else '- none provided'}"
        )

    async def _call_openai(self, prompt: str) -> str:
        settings = get_settings()
        llm_cfg = settings.llm

        if not llm_cfg.api_key or llm_cfg.api_key == "not-set":
            raise RuntimeError("OpenAI API key not configured")

        payload = {
            "model": llm_cfg.model,
            "temperature": llm_cfg.temperature,
            "max_tokens": llm_cfg.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a precise incident diagnosis assistant."},
                {"role": "user", "content": prompt},
            ],
        }

        timeout = httpx.Timeout(llm_cfg.request_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm_cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"]

    async def _call_ollama(self, prompt: str) -> str:
        settings = get_settings()
        llm_cfg = settings.llm

        payload = {
            "model": llm_cfg.ollama_model,
            "messages": [
                {"role": "system", "content": "You are a precise incident diagnosis assistant."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
        }

        timeout = httpx.Timeout(llm_cfg.request_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{llm_cfg.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        return str(message.get("content", ""))

    def _parse_llm_diagnosis_json(self, content: str) -> Dict[str, Any]:
        text = content.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM response")

        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON response is not an object")
        return parsed

    def _normalize_confidence(self, value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))

    def _generate_rule_based_llm_fallback(
        self,
        metrics: List[Dict[str, Any]],
        anomaly: Dict[str, Any],
    ) -> Dict[str, Any]:
        anomaly_type = str(anomaly.get("anomaly_type", "unknown"))
        context = {
            "anomaly": {
                "metrics": metrics,
            }
        }
        pattern_matches = self._match_patterns(anomaly_type, context)
        best = self._select_root_cause(pattern_matches, context)

        remediation_actions = best.get("recommended_actions", [])
        remediation_strategy = remediation_actions[0] if remediation_actions else "Manual investigation required"

        return {
            "root_cause": best.get("description", "Unable to determine root cause"),
            "reasoning": (
                f"Rule-based fallback selected pattern '{best.get('cause', 'unknown')}' "
                f"for anomaly type '{anomaly_type}'."
            ),
            "remediation_strategy": remediation_strategy,
            "confidence": self._normalize_confidence(best.get("confidence", 0.0)),
        }

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
