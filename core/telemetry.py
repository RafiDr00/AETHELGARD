"""
Aethelgard — Observability Layer
=====================================

Architecture:
─────────────────────────────────────────────────────────────
  FastAPI App
    │
    ├── OpenTelemetry SDK (tracing)
    │     ├── ConsoleSpanExporter  (dev/debug)
    │     └── OTLPSpanExporter     (Jaeger / Tempo in prod)
    │
    ├── PrometheusMetrics          (via /metrics endpoint)
    │     ├── Counters
    │     ├── Histograms
    │     └── Gauges
    │
    └── Structured Logs (structlog)
          └── trace_id / span_id injected into every log line

Usage:
    from core.telemetry import (
        tracer, metrics,
        traced_agent_stage, record_pipeline_run,
    )
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import functools
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable, Dict, Optional

# ─────────────────────────────────────────────────────────────
# OpenTelemetry — Tracer Setup
# ─────────────────────────────────────────────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry import propagate
import os

_SERVICE_NAME = "aethelgard-v2"
_OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")

# Build tracer provider
_resource = Resource.create({
    SERVICE_NAME: _SERVICE_NAME,
    "service.version": "2.0.0",
    "deployment.environment": os.environ.get("APP_ENV", "development"),
})
_provider = TracerProvider(resource=_resource)

# Exporters
if _OTEL_ENDPOINT:
    # Production: send to Jaeger / Grafana Tempo via OTLP
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        _otlp_exporter = OTLPSpanExporter(endpoint=_OTEL_ENDPOINT, insecure=True)
        _provider.add_span_processor(BatchSpanProcessor(_otlp_exporter))
    except Exception as e:
        print(f"[OTEL] OTLP exporter failed: {e} — falling back to console")
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
else:
    # Development: print to console (disabled in test mode)
    if os.environ.get("OTEL_CONSOLE_EXPORT", "false").lower() == "true":
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(_provider)

# Module-level tracer — import this in every agent
tracer: trace.Tracer = trace.get_tracer(_SERVICE_NAME, "2.0.0")

# ─────────────────────────────────────────────────────────────
# Prometheus — Metrics Registry
# ─────────────────────────────────────────────────────────────
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Summary,
    CollectorRegistry,
    REGISTRY,
    generate_latest,
)

# Use default registry — exposed via /metrics endpoint
_REG = REGISTRY

# ── Pipeline Counters ──────────────────────────────────────

PIPELINE_RUNS_TOTAL = Counter(
    "aethelgard_pipeline_runs_total",
    "Total number of pipeline executions",
    ["scenario", "status"],
    # scenario values MUST be allowlisted in orchestrator._safe_scenario_label()
    # to prevent cardinality explosion (FIX #5).
    # status: success | rolled_back | validation_failed | sandbox_failed | deduplicated
    registry=_REG,
)

ANOMALIES_DETECTED_TOTAL = Counter(
    "aethelgard_anomalies_detected_total",
    "Total anomalies detected by the detection agent",
    ["anomaly_type", "severity", "service"],
    registry=_REG,
)

REMEDIATIONS_TOTAL = Counter(
    "aethelgard_remediations_total",
    "Total remediation attempts",
    ["patch_type", "status"],         # status: success | rolled_back | validation_failed | sandbox_failed | deduplicated
    registry=_REG,
)

SANDBOX_VALIDATIONS_TOTAL = Counter(
    "aethelgard_sandbox_validations_total",
    "Sandbox execution outcomes",
    ["result", "reason"],             # result: passed | failed | blocked | timeout
    registry=_REG,
)

VALIDATION_FAILURES_TOTAL = Counter(
    "aethelgard_validation_failures_total",
    "Validation failures that block autonomous deployment",
    ["reason"],                    # sandbox | policy | static_analysis | risk_threshold
    registry=_REG,
)

POLICY_VIOLATIONS_TOTAL = Counter(
    "aethelgard_policy_violations_total",
    "Security policy violations caught by AST analysis",
    ["violation_type", "severity"],
    registry=_REG,
)

LEARNING_STORES_TOTAL = Counter(
    "aethelgard_learning_stores_total",
    "Documents written to RAG knowledge base",
    ["category"],
    registry=_REG,
)

API_AUTH_FAILURES_TOTAL = Counter(
    "aethelgard_api_auth_failures_total",
    "API authentication failures",
    ["endpoint"],
    registry=_REG,
)

DEPLOYMENT_GUARDRAIL_BLOCKS_TOTAL = Counter(
    "aethelgard_deployment_guardrail_blocks_total",
    "Deployment operations blocked by safety guardrails",
    ["reason"],
    registry=_REG,
)

# ── Pipeline Histograms (latency distributions) ─────────────

PIPELINE_DURATION_SECONDS = Histogram(
    "aethelgard_pipeline_duration_seconds",
    "End-to-end autonomous remediation pipeline duration",
    ["scenario"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    registry=_REG,
)

AGENT_STAGE_DURATION_SECONDS = Histogram(
    "aethelgard_agent_stage_duration_seconds",
    "Duration of each agent stage within the pipeline",
    ["agent_type"],                   # detection | diagnosis | remediation | validation | deployment
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=_REG,
)

AGENT_LATENCY_SECONDS = Histogram(
    "aethelgard_agent_latency_seconds",
    "Latency distribution for agent stage execution",
    ["agent_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=_REG,
)

MTTD_SECONDS = Histogram(
    "aethelgard_mttd_seconds",
    "Mean Time to Detect — from anomaly onset to detection",
    ["anomaly_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0],
    registry=_REG,
)

MTTR_SECONDS = Histogram(
    "aethelgard_mttr_seconds",
    "Mean Time to Repair — full pipeline duration for successful remediations",
    ["anomaly_type"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
    registry=_REG,
)

DIAGNOSIS_CONFIDENCE = Histogram(
    "aethelgard_diagnosis_confidence",
    "Distribution of diagnosis confidence scores",
    ["root_cause_category"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=_REG,
)

RISK_SCORE_DISTRIBUTION = Histogram(
    "aethelgard_validation_risk_score",
    "Distribution of validation risk scores",
    ["patch_type"],
    buckets=[0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=_REG,
)

SANDBOX_DURATION_SECONDS = Histogram(
    "aethelgard_sandbox_duration_seconds",
    "Time taken for sandbox execution",
    ["mode"],                         # subprocess | docker
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 30.0],
    registry=_REG,
)

RAG_QUERY_DURATION_SECONDS = Histogram(
    "aethelgard_rag_query_duration_seconds",
    "Time taken for RAG knowledge base queries",
    ["backend"],                      # sentence_transformers | tfidf | hash | unknown
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
    registry=_REG,
)

# ── FIX #8 — ReAct Loop Telemetry ──────────────────────────────────

REACT_ITERATIONS = Histogram(
    "aethelgard_react_iterations_total",
    "Number of ReAct loop iterations before termination, per agent type. "
    "Peaks near max_iterations indicate agents struggling to decide.",
    ["agent_type", "outcome"],        # outcome: decided | timeout | error | exhausted
    buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20],
    registry=_REG,
)

REACT_TIMEOUTS_TOTAL = Counter(
    "aethelgard_react_timeouts_total",
    "ReAct loops terminated by timeout (agent took too long to decide)",
    ["agent_type"],
    registry=_REG,
)

# ── Gauges (current state) ──────────────────────────────────

ACTIVE_PIPELINE_JOBS = Gauge(
    "aethelgard_active_pipeline_jobs",
    "Number of pipeline jobs currently running",
    registry=_REG,
)

KNOWLEDGE_BASE_DOCUMENTS = Gauge(
    "aethelgard_knowledge_base_documents",
    "Total documents in RAG knowledge base",
    ["category"],
    registry=_REG,
)

AUTONOMOUS_RESOLUTION_RATE = Gauge(
    "aethelgard_autonomous_resolution_rate",
    "Fraction of incidents resolved autonomously (0.0–1.0)",
    registry=_REG,
)

ENGINEERING_HOURS_SAVED = Gauge(
    "aethelgard_engineering_hours_saved_total",
    "Cumulative engineering hours saved by autonomous remediation",
    registry=_REG,
)

ROI_DOLLARS = Gauge(
    "aethelgard_roi_dollars_total",
    "Cumulative ROI in USD from autonomous remediations",
    registry=_REG,
)

DEDUP_SUPPRESSION_RATIO = Gauge(
    "aethelgard_dedup_suppression_ratio",
    "Fraction of triggers suppressed by deduplication (deduplicated / total)",
    registry=_REG,
)


def telemetry_health_status() -> tuple[bool, str]:
    """Validate core telemetry primitives required for production operation."""
    if tracer is None:
        return False, "tracer_uninitialized"

    try:
        scrape = generate_latest().decode("utf-8")
    except Exception as exc:
        return False, f"prometheus_registry_unavailable:{exc}"

    required = (
        "aethelgard_pipeline_runs_total",
        "aethelgard_dedup_suppression_ratio",
        "aethelgard_agent_stage_duration_seconds",
    )
    for metric_name in required:
        if metric_name not in scrape:
            return False, f"missing_metric:{metric_name}"

    return True, "ok"

# ─────────────────────────────────────────────────────────────
# Tracing Utilities
# ─────────────────────────────────────────────────────────────

@contextmanager
def agent_span(agent_type: str, operation: str, attributes: Dict[str, Any] = None):
    """
    Context manager that creates an OTel span for an agent operation.

    Usage:
        with agent_span("detection", "analyze_metrics", {"metric_count": 12}):
            result = await self.detection_agent.analyze_metrics(metrics)
    """
    with tracer.start_as_current_span(
        f"agent.{agent_type}.{operation}",
        attributes={
            "agent.type": agent_type,
            "agent.operation": operation,
            **(attributes or {}),
        },
    ) as span:
        start_time = time.time()
        try:
            yield span
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
        finally:
            duration = time.time() - start_time
            span.set_attribute("agent.duration_ms", round(duration * 1000, 2))
            # Record in Prometheus histogram
            AGENT_STAGE_DURATION_SECONDS.labels(agent_type=agent_type).observe(duration)
            AGENT_LATENCY_SECONDS.labels(agent_type=agent_type).observe(duration)


@asynccontextmanager
async def pipeline_span(correlation_id: str, scenario: str = "unknown"):
    """
    Async context manager for the full pipeline span.

    Sets the root trace for all child agent spans via context propagation.
    """
    with tracer.start_as_current_span(
        "pipeline.run",
        attributes={
            "pipeline.correlation_id": correlation_id,
            "pipeline.scenario": scenario,
        },
    ) as span:
        ACTIVE_PIPELINE_JOBS.inc()
        start_time = time.time()
        try:
            yield span
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            PIPELINE_RUNS_TOTAL.labels(scenario=scenario, status="validation_failed").inc()
            raise
        finally:
            duration = time.time() - start_time
            ACTIVE_PIPELINE_JOBS.dec()
            span.set_attribute("pipeline.duration_ms", round(duration * 1000, 2))


def get_trace_context() -> Dict[str, str]:
    """Extract current trace context for injection into logs / events."""
    ctx: Dict[str, str] = {}
    propagate.inject(ctx)
    return ctx


def get_current_trace_id() -> str:
    """Get current trace ID as hex string for log correlation."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return ""


def get_current_span_id() -> str:
    """Get current span ID as hex string."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.is_valid:
        return format(ctx.span_id, "016x")
    return ""


# ─────────────────────────────────────────────────────────────
# Record Pipeline Run Metrics (call from orchestrator)
# ─────────────────────────────────────────────────────────────

def record_pipeline_run(
    record,          # RemediationRecord
    scenario: str = "unknown",
) -> None:
    """
    Record all Prometheus metrics for a completed pipeline run.
    Called once per completed RemediationRecord from the orchestrator.
    """
    anomaly = record.anomaly
    diagnosis = record.diagnosis
    patch = record.patch
    validation = record.validation
    deployment = record.deployment

    status = record.remediation_status.value

    # ── Counters ─────────────────────────────────────────────
    PIPELINE_RUNS_TOTAL.labels(scenario=scenario, status=status).inc()

    ANOMALIES_DETECTED_TOTAL.labels(
        anomaly_type=anomaly.anomaly_type,
        severity=anomaly.severity.value,
        service=anomaly.service_name,
    ).inc()

    REMEDIATIONS_TOTAL.labels(
        patch_type=patch.patch_type,
        status=status,
    ).inc()

    # ── Histograms ────────────────────────────────────────────
    PIPELINE_DURATION_SECONDS.labels(scenario=scenario).observe(
        record.total_duration_seconds
    )

    MTTD_SECONDS.labels(
        anomaly_type=anomaly.anomaly_type
    ).observe(record.mttd_seconds)

    if record.was_successful:
        MTTR_SECONDS.labels(
            anomaly_type=anomaly.anomaly_type
        ).observe(record.mttr_seconds)

    DIAGNOSIS_CONFIDENCE.labels(
        root_cause_category=diagnosis.root_cause_category
    ).observe(diagnosis.confidence)

    RISK_SCORE_DISTRIBUTION.labels(
        patch_type=patch.patch_type
    ).observe(validation.risk_score)

    # ── Gauges ────────────────────────────────────────────────
    # Note: AUTONOMOUS_RESOLUTION_RATE, ENGINEERING_HOURS_SAVED, ROI_DOLLARS
    # are updated by orchestrator._update_metrics_incremental()


def record_sandbox_result(
    passed: bool,
    reason: str,
    duration: float,
    mode: str = "subprocess",
    violations: list = None,
) -> None:
    """Record sandbox validation metrics."""
    result = "passed" if passed else "failed"
    if reason == "critical_security_violations":
        result = "blocked"
    elif reason == "timeout":
        result = "timeout"

    SANDBOX_VALIDATIONS_TOTAL.labels(result=result, reason=reason or "none").inc()
    SANDBOX_DURATION_SECONDS.labels(mode=mode).observe(duration)

    for v in (violations or []):
        POLICY_VIOLATIONS_TOTAL.labels(
            violation_type=v.get("type", "unknown"),
            severity=v.get("severity", "unknown"),
        ).inc()


def record_rag_query(duration: float, backend: str, results_count: int) -> None:
    """Record RAG knowledge query metrics."""
    RAG_QUERY_DURATION_SECONDS.labels(backend=backend).observe(duration)


def record_react_iteration(
    agent_type: str,
    iterations: int,
    outcome: str = "decided",
) -> None:
    """
    FIX #8 — Emit ReAct loop telemetry.

    Call this at the end of every execute_react_loop() invocation.

    Args:
        agent_type: "detection" | "diagnosis" | "remediation" | "validation" | "deployment"
        iterations:  Number of iterations executed before terminating
        outcome:     "decided" | "timeout" | "error" | "exhausted"

    When the histogram consistently peaks near max_iterations, agents are
    failing to reach a decision cleanly — flag for reasoning quality review.
    """
    REACT_ITERATIONS.labels(
        agent_type=agent_type,
        outcome=outcome,
    ).observe(iterations)

    if outcome == "timeout":
        REACT_TIMEOUTS_TOTAL.labels(agent_type=agent_type).inc()


def record_dedup_suppression_ratio(deduplicated_triggers: int, total_triggers: int) -> None:
    """Update dedup suppression ratio gauge."""
    if total_triggers <= 0:
        DEDUP_SUPPRESSION_RATIO.set(0.0)
        return
    DEDUP_SUPPRESSION_RATIO.set(deduplicated_triggers / total_triggers)
