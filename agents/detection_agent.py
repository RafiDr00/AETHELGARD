"""
Aethelgard v2 — Detection Agent

Anomaly detection agent that monitors infrastructure metrics and log streams.
Uses statistical analysis and pattern recognition to identify deviations
from baseline performance.

Subscribes to: raw log/metric streams
Publishes: anomaly.detected events
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.config import get_settings
from core.logging_config import get_logger
from core.models import AgentType, Anomaly, EventType, Severity, ServiceMetric

logger = get_logger(__name__)


class DetectionAgent(BaseAgent):
    """
    Anomaly detection agent using statistical deviation analysis.
    
    Maintains rolling windows of service metrics and triggers
    anomaly events when values deviate beyond configurable thresholds.
    
    Detection methods:
    - Z-score deviation (> 2σ from rolling mean)
    - Threshold breach (absolute limits)
    - Rate-of-change spikes
    - Pattern anomaly (unusual metric combinations)
    """

    # Baseline thresholds per metric type
    BASELINE_THRESHOLDS = {
        "response_time_ms": {"warn": 500, "critical": 2000, "unit": "ms"},
        "error_rate": {"warn": 0.05, "critical": 0.15, "unit": "ratio"},
        "cpu_usage": {"warn": 0.80, "critical": 0.95, "unit": "ratio"},
        "memory_usage": {"warn": 0.80, "critical": 0.95, "unit": "ratio"},
        "request_rate": {"warn": 1000, "critical": 5000, "unit": "req/s"},
        "queue_depth": {"warn": 100, "critical": 500, "unit": "messages"},
        "connection_pool": {"warn": 0.85, "critical": 0.95, "unit": "ratio"},
        "disk_io": {"warn": 0.80, "critical": 0.95, "unit": "ratio"},
    }

    ROLLING_WINDOW_SIZE = 60  # Keep last 60 data points
    Z_SCORE_THRESHOLD = 2.5  # Standard deviations for anomaly

    def __init__(self):
        super().__init__(AgentType.DETECTION)
        self._metric_windows: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.ROLLING_WINDOW_SIZE)
        )
        self._detected_anomalies: List[Anomaly] = []
        self._sensitivity = get_settings().agents.detection_sensitivity

    async def _setup_subscriptions(self) -> None:
        """Detection agent doesn't subscribe to events — it receives metrics directly."""
        pass

    async def collect_baseline(self, metrics: List[ServiceMetric]) -> None:
        """
        Collect baseline metrics without running anomaly detection.
        Used during warmup phase to build rolling windows.
        """
        for metric in metrics:
            key = f"{metric.service_name}:{metric.metric_name}"
            self._metric_windows[key].append(metric.value)

    async def analyze_metrics(self, metrics: List[ServiceMetric]) -> Optional[Anomaly]:
        """
        Analyze a batch of metrics for anomalies.
        
        This is the primary entry point for the detection pipeline.
        Metrics are added to rolling windows, and then analyzed for deviations.
        """
        context = {
            "metrics": [m.model_dump() for m in metrics],
            "metric_count": len(metrics),
            "services": list(set(m.service_name for m in metrics)),
        }

        # Update rolling windows
        for metric in metrics:
            key = f"{metric.service_name}:{metric.metric_name}"
            self._metric_windows[key].append(metric.value)
            context[f"window_{key}"] = list(self._metric_windows[key])

        try:
            result = await self.execute_react_loop(context)
            return result.get("anomaly")
        except Exception as e:
            logger.error("detection_analysis_failed", error=str(e))
            return None

    async def think(self, context: Dict[str, Any]) -> str:
        """Analyze current metrics against baselines and statistical norms."""
        metrics = context.get("metrics", [])
        thoughts = []

        for metric_data in metrics:
            service = metric_data.get("service_name", "unknown")
            metric_name = metric_data.get("metric_name", "unknown")
            value = metric_data.get("value", 0)
            key = f"{service}:{metric_name}"
            window = list(self._metric_windows.get(key, []))

            # Check absolute thresholds
            thresholds = self.BASELINE_THRESHOLDS.get(metric_name, {})
            critical_threshold = thresholds.get("critical")
            warn_threshold = thresholds.get("warn")

            if critical_threshold and value > critical_threshold:
                thoughts.append(
                    f"CRITICAL: {service}/{metric_name} = {value} exceeds critical threshold {critical_threshold}"
                )
            elif warn_threshold and value > warn_threshold:
                thoughts.append(
                    f"WARNING: {service}/{metric_name} = {value} exceeds warning threshold {warn_threshold}"
                )

            # Check statistical deviation
            if len(window) >= 10:
                mean = statistics.mean(window[:-1])  # Exclude latest
                stdev = statistics.stdev(window[:-1]) if len(window) > 2 else 0
                if stdev > 0:
                    z_score = (value - mean) / stdev
                    if abs(z_score) > self.Z_SCORE_THRESHOLD:
                        thoughts.append(
                            f"STATISTICAL ANOMALY: {service}/{metric_name} z-score={z_score:.2f} "
                            f"(value={value}, mean={mean:.2f}, σ={stdev:.2f})"
                        )

                # Rate of change
                if len(window) >= 3:
                    recent_change = value - window[-2]
                    avg_change = statistics.mean(
                        [window[i] - window[i-1] for i in range(1, len(window)-1)]
                    ) if len(window) > 2 else 0
                    if avg_change != 0 and abs(recent_change / max(abs(avg_change), 0.001)) > 5:
                        thoughts.append(
                            f"RATE SPIKE: {service}/{metric_name} changed by {recent_change:.2f} "
                            f"(avg change: {avg_change:.2f})"
                        )

        if not thoughts:
            thoughts.append("All metrics within normal operating parameters.")

        return " | ".join(thoughts)

    async def act(self, thought: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify the anomaly and compute severity."""
        is_anomaly = any(keyword in thought for keyword in ["CRITICAL", "STATISTICAL ANOMALY", "RATE SPIKE"])
        is_warning = "WARNING" in thought

        if not is_anomaly and not is_warning:
            return {"is_anomaly": False, "severity": None}

        # Determine severity
        if "CRITICAL" in thought:
            severity = Severity.CRITICAL
        elif "STATISTICAL ANOMALY" in thought:
            severity = Severity.HIGH
        elif "RATE SPIKE" in thought:
            severity = Severity.MEDIUM
        else:
            severity = Severity.LOW

        # Determine anomaly type
        anomaly_type = "unknown"
        if "response_time" in thought.lower():
            anomaly_type = "latency_spike"
        elif "error_rate" in thought.lower():
            anomaly_type = "error_rate_increase"
        elif "cpu" in thought.lower():
            anomaly_type = "cpu_saturation"
        elif "memory" in thought.lower():
            anomaly_type = "memory_pressure"
        elif "queue" in thought.lower():
            anomaly_type = "queue_buildup"
        elif "connection" in thought.lower():
            anomaly_type = "connection_exhaustion"

        # Extract affected service
        metrics = context.get("metrics", [])
        affected_services = list(set(m.get("service_name", "unknown") for m in metrics))

        return {
            "is_anomaly": True,
            "severity": severity,
            "anomaly_type": anomaly_type,
            "affected_services": affected_services,
            "description": thought,
        }

    async def observe(self, action_result: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Generate observation from analysis results."""
        if not action_result.get("is_anomaly"):
            return "No anomaly detected. System operating normally."

        severity = action_result.get("severity", Severity.LOW)
        anomaly_type = action_result.get("anomaly_type", "unknown")
        services = action_result.get("affected_services", [])

        return (
            f"Anomaly confirmed: type={anomaly_type}, severity={severity.value}, "
            f"affected_services={services}. Initiating diagnosis pipeline."
        )

    async def decide(self, context: Dict[str, Any]) -> bool:
        """Detection always completes in one iteration."""
        return True

    async def emit_result(self, context: Dict[str, Any]) -> None:
        """Emit anomaly detection event to the bus."""
        action_result = context.get("last_action_result", {})

        if not action_result.get("is_anomaly"):
            return

        # Build anomaly object
        metrics = context.get("metrics", [])
        service_metrics = [ServiceMetric(**m) for m in metrics] if metrics else []
        
        anomaly = Anomaly(
            service_name=action_result.get("affected_services", ["unknown"])[0],
            anomaly_type=action_result.get("anomaly_type", "unknown"),
            description=action_result.get("description", ""),
            severity=action_result.get("severity", Severity.MEDIUM),
            metrics=service_metrics,
            confidence=self._sensitivity,
            detection_latency_ms=context.get("total_reasoning_time", 0) * 1000,
        )

        self._detected_anomalies.append(anomaly)
        context["anomaly"] = anomaly

        # Publish to event bus
        await self.publish_event(
            EventType.ANOMALY_DETECTED,
            payload=anomaly.model_dump(mode="json"),
            correlation_id=anomaly.id,
        )

        logger.info(
            "anomaly_emitted",
            anomaly_id=anomaly.id,
            service=anomaly.service_name,
            type=anomaly.anomaly_type,
            severity=anomaly.severity.value,
        )
