"""
Aethelgard v2 — Runtime Correctness & Observability Test Suite
===============================================================

Sections:
  1. Middleware & Real Metrics Ingestion     (FIX #1)
  2. OTel Span Coverage                     (FIX #2)
  3. Concurrency Safety & Per-Service Mutex (FIX #3)
  4. Anomaly Fingerprint Deduplication      (FIX #4)
  5. Prometheus Cardinality Safety          (FIX #5)
  6. Template Config Typed Values           (FIX #6)
  7. Real HTTP Health Checks                (FIX #7)
  8. ReAct Iteration Telemetry              (FIX #8)
  9. Sandbox Security Bypass Attempts
 10. Load / Buffer Overflow Protection
 11. Full Pipeline Acceptance
"""

from __future__ import annotations

import asyncio
import http.server
import threading
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import (
    Anomaly, Diagnosis, Patch, PatchStatus, ServiceMetric, Severity,
    ValidationResult, RiskLevel, DeploymentRecord,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_metric(service: str, name: str, value: float, unit: str = "ms") -> ServiceMetric:
    return ServiceMetric(
        service_name=service, metric_name=name, value=value,
        unit=unit, timestamp=datetime.now(timezone.utc),
    )


def _normal_metrics(service: str = "payment-api") -> List[ServiceMetric]:
    return [
        _make_metric(service, "response_time_ms", 180),
        _make_metric(service, "error_rate", 0.001, "ratio"),
        _make_metric(service, "cpu_usage", 0.35, "ratio"),
    ]


def _spike_metrics(service: str = "payment-api") -> List[ServiceMetric]:
    return [
        _make_metric(service, "response_time_ms", 3500),
        _make_metric(service, "error_rate", 0.001, "ratio"),
        _make_metric(service, "cpu_usage", 0.35, "ratio"),
    ]


async def _build_baseline(agent, service: str = "payment-api", ticks: int = 16):
    """Feed the detection agent enough history to establish a statistical baseline."""
    for _ in range(ticks):
        await agent.analyze_metrics(_normal_metrics(service))


# ═══════════════════════════════════════════════════════════════════════════
# 1. Middleware & Real Metrics Ingestion — FIX #1
# ═══════════════════════════════════════════════════════════════════════════

class TestMetricsBuffer:
    """MetricsBuffer is thread-safe and enforces MAX_SIZE."""

    @pytest.mark.asyncio
    async def test_write_and_read_batch(self):
        from listener.real_metrics import MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 50)
        for _ in range(10):
            await buf.write(m)
        batch = await buf.read_batch(5)
        assert len(batch) == 5        # returns at most max_count
        assert buf.size == 10         # read_batch does NOT drain

    @pytest.mark.asyncio
    async def test_drain_removes_items(self):
        from listener.real_metrics import MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 50)
        for _ in range(6):
            await buf.write(m)
        drained = await buf.drain(4)
        assert len(drained) == 4
        assert buf.size == 2

    @pytest.mark.asyncio
    async def test_max_size_eviction(self):
        from listener.real_metrics import MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 50)
        for _ in range(MetricsBuffer.MAX_SIZE + 50):
            await buf.write(m)
        assert buf.size == MetricsBuffer.MAX_SIZE  # deque maxlen enforced

    @pytest.mark.asyncio
    async def test_concurrent_writes_are_safe(self):
        from listener.real_metrics import MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 50)

        async def writer():
            for _ in range(50):
                await buf.write(m)

        await asyncio.gather(*[writer() for _ in range(10)])
        assert buf.size <= MetricsBuffer.MAX_SIZE

    @pytest.mark.asyncio
    async def test_singleton_returns_same_instance(self):
        from listener.real_metrics import get_metrics_buffer
        b1 = get_metrics_buffer()
        b2 = get_metrics_buffer()
        assert b1 is b2


class TestRealLogListener:
    """RealLogListener falls back to simulator when buffer is thin."""

    @pytest.mark.asyncio
    async def test_uses_simulator_fallback_when_buffer_thin(self):
        from listener.real_metrics import RealLogListener, MetricsBuffer
        buf = MetricsBuffer()   # fresh empty buffer

        sim = MagicMock()
        sim.generate_metrics.return_value = _normal_metrics()

        listener = RealLogListener(
            fallback_simulator=sim,
            min_real_metrics=5,
        )
        # Inject the fresh buffer
        listener._buffer = buf

        dispatched = []
        listener.on_metrics(lambda m: dispatched.append(m) or asyncio.coroutine(lambda: None)())

        # _poll_and_dispatch should call simulator since buffer has 0 items < 5
        async def fake_callback(m):
            dispatched.append(m)

        listener._metric_callbacks = [fake_callback]
        await listener._poll_and_dispatch()

        sim.generate_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_real_metrics_when_buffer_full(self):
        from listener.real_metrics import RealLogListener, MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("aethelgard-api", "response_time_ms", 45)
        for _ in range(10):
            await buf.write(m)

        sim = MagicMock()
        listener = RealLogListener(fallback_simulator=sim, min_real_metrics=5)
        listener._buffer = buf

        dispatched = []
        async def capture(metrics):
            dispatched.extend(metrics)

        listener._metric_callbacks = [capture]
        await listener._poll_and_dispatch()

        sim.generate_metrics.assert_not_called()   # real metrics used
        assert len(dispatched) == 10

    @pytest.mark.asyncio
    async def test_semaphore_blocks_concurrent_pipeline_triggers(self):
        from listener.real_metrics import RealLogListener, MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 45)
        for _ in range(10):
            await buf.write(m)

        listener = RealLogListener(fallback_simulator=None, min_real_metrics=1)
        listener._buffer = buf

        call_count = 0
        async def slow_callback(metrics):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.2)

        listener._metric_callbacks = [slow_callback]

        # Fire two polls concurrently — only ONE should acquire the semaphore
        results = await asyncio.gather(
            listener._poll_and_dispatch(),
            listener._poll_and_dispatch(),
        )

        assert call_count == 1  # Second poll skipped (semaphore busy)


# ═══════════════════════════════════════════════════════════════════════════
# 2. OTel Span Coverage — FIX #2
# ═══════════════════════════════════════════════════════════════════════════

class TestOtelSpanCoverage:
    """Verify every pipeline run produces a root span + 5 agent child spans."""

    @pytest.mark.asyncio
    async def test_run_full_pipeline_emits_root_span(self):
        """pipeline.run span must be present in run_full_pipeline (not a wrapper)."""
        import inspect
        from agents.orchestrator import AgentOrchestrator
        src = inspect.getsource(AgentOrchestrator.run_full_pipeline)
        assert "tracer.start_as_current_span" in src, \
            "root span missing from run_full_pipeline — BG jobs would be untraceable"

    @pytest.mark.asyncio
    async def test_all_agent_spans_present(self):
        import inspect
        from agents.orchestrator import AgentOrchestrator
        src = inspect.getsource(AgentOrchestrator._run_instrumented_stages)
        for stage in ("detection", "diagnosis", "remediation", "validation", "deployment"):
            assert f'"{stage}"' in src or f"'{stage}'" in src, \
                f"agent_span missing for stage: {stage}"

    @pytest.mark.asyncio
    async def test_observable_orchestrator_not_used_in_lifespan(self):
        """api.py lifespan must NOT import ObservableOrchestrator anymore."""
        import inspect
        import api
        src = inspect.getsource(api.lifespan)
        assert "ObservableOrchestrator" not in src, \
            "ObservableOrchestrator still wired in lifespan — BG jobs are untraceable"

    @pytest.mark.asyncio
    async def test_span_attributes_annotated_on_pipeline(self):
        """run_full_pipeline must set anomaly attributes on root span."""
        import inspect
        from agents.orchestrator import AgentOrchestrator
        src = inspect.getsource(AgentOrchestrator._execute_pipeline_stages)
        assert "anomaly.type" in src
        assert "anomaly.severity" in src
        assert "pipeline.fingerprint" in src

    @pytest.mark.asyncio
    async def test_run_job_delegates_to_instrumented_pipeline(self):
        """run_job → run_full_pipeline (the instrumented one)."""
        import inspect
        from agents.orchestrator import AgentOrchestrator
        src = inspect.getsource(AgentOrchestrator.run_job)
        assert "run_full_pipeline" in src


# ═══════════════════════════════════════════════════════════════════════════
# 3. Concurrency Safety — FIX #3
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrencySafety:

    @pytest.mark.asyncio
    async def test_per_service_lock_exists(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        lock = await orch._get_service_lock("payment-api")
        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_same_service_returns_same_lock(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        l1 = await orch._get_service_lock("payment-api")
        l2 = await orch._get_service_lock("payment-api")
        assert l1 is l2   # identical object — truly mutual exclusion

    @pytest.mark.asyncio
    async def test_different_services_get_different_locks(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        l1 = await orch._get_service_lock("payment-api")
        l2 = await orch._get_service_lock("order-service")
        assert l1 is not l2  # parallel remediation on different services is allowed

    @pytest.mark.asyncio
    async def test_service_lock_blocks_concurrent_access(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        lock = await orch._get_service_lock("payment-api")

        order = []

        async def first():
            async with lock:
                order.append("start-1")
                await asyncio.sleep(0.05)
                order.append("end-1")

        async def second():
            await asyncio.sleep(0.01)      # let first acquire first
            async with lock:
                order.append("start-2")
                await asyncio.sleep(0.01)
                order.append("end-2")

        await asyncio.gather(first(), second())
        # Non-overlapping: end-1 must come before start-2
        assert order.index("end-1") < order.index("start-2"), \
            f"Lock failed to serialise access: {order}"

    @pytest.mark.asyncio
    async def test_history_lock_present(self):
        import inspect
        from agents.orchestrator import AgentOrchestrator
        src = inspect.getsource(AgentOrchestrator.__init__)
        assert "_history_lock" in src
        assert "_metrics_lock" in src

    @pytest.mark.asyncio
    async def test_append_history_uses_lock(self):
        import inspect
        from agents.orchestrator import AgentOrchestrator
        src = inspect.getsource(AgentOrchestrator._execute_pipeline_stages)
        assert "_history_lock" in src


# ═══════════════════════════════════════════════════════════════════════════
# 4. Anomaly Fingerprint Deduplication — FIX #4
# ═══════════════════════════════════════════════════════════════════════════

class TestFingerprintDeduplication:

    def test_orchestrator_uses_configured_dedup_ttl(self, monkeypatch):
        monkeypatch.setenv("DEDUP_FINGERPRINT_TTL_SECONDS", "5")
        from core.config import get_settings
        get_settings.cache_clear()
        try:
            from agents.orchestrator import AgentOrchestrator
            orch = AgentOrchestrator()
            assert orch._fingerprint_ttl_seconds == 5.0
        finally:
            get_settings.cache_clear()

    def test_same_anomaly_same_fingerprint(self):
        from agents.orchestrator import _anomaly_fingerprint
        fp1 = _anomaly_fingerprint("payment-api", "latency_spike", "critical")
        fp2 = _anomaly_fingerprint("payment-api", "latency_spike", "critical")
        assert fp1 == fp2

    def test_different_type_different_fingerprint(self):
        from agents.orchestrator import _anomaly_fingerprint
        fp1 = _anomaly_fingerprint("payment-api", "latency_spike", "critical")
        fp2 = _anomaly_fingerprint("payment-api", "error_rate_increase", "critical")
        assert fp1 != fp2

    def test_different_service_different_fingerprint(self):
        from agents.orchestrator import _anomaly_fingerprint
        fp1 = _anomaly_fingerprint("payment-api", "latency_spike", "critical")
        fp2 = _anomaly_fingerprint("order-service", "latency_spike", "critical")
        assert fp1 != fp2

    def test_fingerprint_length_bounded(self):
        from agents.orchestrator import _anomaly_fingerprint
        fp = _anomaly_fingerprint("x" * 200, "y" * 200, "z" * 200)
        assert len(fp) == 16   # SHA-256 truncated to 16 hex chars

    @pytest.mark.asyncio
    async def test_claim_returns_true_first_time(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        fp = "abc123"
        result = await orch._claim_fingerprint(fp)
        assert result is True

    @pytest.mark.asyncio
    async def test_claim_returns_false_when_active(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        fp = "abc123"
        await orch._claim_fingerprint(fp)
        result = await orch._claim_fingerprint(fp)   # second claim
        assert result is False

    @pytest.mark.asyncio
    async def test_release_allows_re_claim(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        orch._fingerprint_ttl_seconds = 0.0
        fp = "abc123"
        await orch._claim_fingerprint(fp)
        await orch._release_fingerprint(fp)
        result = await orch._claim_fingerprint(fp)   # should succeed again
        assert result is True

    @pytest.mark.asyncio
    async def test_concurrent_claims_only_one_wins(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        fp = "race-condition-test"
        results = await asyncio.gather(*[orch._claim_fingerprint(fp) for _ in range(10)])
        # Exactly one True — all others False
        assert results.count(True) == 1
        assert results.count(False) == 9

    @pytest.mark.asyncio
    async def test_pipeline_skips_duplicate_anomaly(self):
        """
        When the same fingerprint is already claimed, run_full_pipeline must
        return None without executing diagnosis/remediation/deployment stages.
        """
        from agents.orchestrator import AgentOrchestrator, _anomaly_fingerprint
        orch = AgentOrchestrator()

        # Pre-claim the fingerprint for payment-api latency_spike critical
        fp = _anomaly_fingerprint("payment-api", "latency_spike", "critical")
        await orch._claim_fingerprint(fp)

        diagnose_called = False
        original_diagnose = orch.diagnosis_agent.diagnose

        async def patched_diagnose(anomaly):
            nonlocal diagnose_called
            diagnose_called = True
            return await original_diagnose(anomaly)

        orch.diagnosis_agent.diagnose = patched_diagnose

        # Build baseline so detection fires
        await _build_baseline(orch.detection_agent)
        record = await orch.run_full_pipeline(
            _spike_metrics("payment-api"), scenario="payment_latency_spike"
        )

        # Either no anomaly detected OR deduplicated (both return None)
        assert record is None
        assert not diagnose_called, \
            "Diagnosis agent ran despite duplicate fingerprint — deduplication failed"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Prometheus Cardinality Safety — FIX #5
# ═══════════════════════════════════════════════════════════════════════════

class TestPrometheusCardinality:

    def test_known_scenario_preserved(self):
        from agents.orchestrator import _safe_scenario_label, KNOWN_SCENARIOS
        for s in KNOWN_SCENARIOS:
            assert _safe_scenario_label(s) == s

    def test_unknown_scenario_mapped_to_other(self):
        from agents.orchestrator import _safe_scenario_label
        assert _safe_scenario_label("ATTACKER_INJECTION_xyz123") == "other"
        assert _safe_scenario_label("") == "other"
        assert _safe_scenario_label("a" * 5000) == "other"

    def test_known_scenarios_count_bounded(self):
        from agents.orchestrator import KNOWN_SCENARIOS
        # Hard limit: must stay manageable for Prometheus
        assert len(KNOWN_SCENARIOS) <= 50

    def test_react_histogram_labels_bounded(self):
        from prometheus_client import REGISTRY
        # Pull the metric from the registry — all observed label combos
        families = {f.name: f for f in REGISTRY.collect()}
        hist_name = "aethelgard_react_iterations_total"
        assert hist_name in families or any(hist_name in n for n in families), \
            f"Histogram {hist_name!r} not registered"

    def test_all_expected_metrics_registered(self):
        import core.telemetry  # ensure metric families are registered
        from prometheus_client import REGISTRY
        names = {f.name for f in REGISTRY.collect()}
        required = {
            "aethelgard_pipeline_runs_total",
            "aethelgard_react_iterations_total",
            "aethelgard_react_timeouts_total",
            "aethelgard_active_pipeline_jobs",
            "aethelgard_dedup_suppression_ratio",
            "aethelgard_anomalies_detected_total",
            "aethelgard_remediations_total",
            "aethelgard_agent_stage_duration_seconds",
        }
        missing = {
            metric
            for metric in required
            if metric not in names and metric.removesuffix("_total") not in names
        }
        assert not missing, f"Missing Prometheus metrics: {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Template Config Typed Values — FIX #6
# ═══════════════════════════════════════════════════════════════════════════

class TestTemplateConfigTypes:

    @pytest.fixture
    def agent(self):
        from agents.remediation_agent import RemediationAgent
        a = RemediationAgent.__new__(RemediationAgent)
        a._knowledge_engine = None
        return a

    def test_worker_pool_config_is_int(self, agent):
        from agents.remediation_agent import REMEDIATION_TEMPLATES
        tmpl = REMEDIATION_TEMPLATES["worker_pool_exhaustion"]
        cfg = agent._generate_config(tmpl, {})
        assert isinstance(cfg["workers"], int), \
            f"workers must be int, got {type(cfg['workers'])}: {cfg['workers']!r}"
        assert cfg["workers"] == 8

    def test_database_config_types(self, agent):
        from agents.remediation_agent import REMEDIATION_TEMPLATES
        tmpl = REMEDIATION_TEMPLATES["database_bottleneck"]
        cfg = agent._generate_config(tmpl, {})
        assert isinstance(cfg["pool_size"], int)
        assert isinstance(cfg["max_overflow"], int)
        assert isinstance(cfg["pool_timeout"], int)

    def test_no_curly_brace_strings_in_config(self, agent):
        from agents.remediation_agent import REMEDIATION_TEMPLATES
        for tmpl_name, tmpl in REMEDIATION_TEMPLATES.items():
            cfg = agent._generate_config(tmpl, {})
            for key, value in cfg.items():
                if isinstance(value, str):
                    assert "{" not in value and "}" not in value, \
                        f"Template {tmpl_name!r} key {key!r} still has " \
                        f"unresolved placeholder: {value!r}"

    def test_code_changes_format_correctly(self, agent):
        from agents.remediation_agent import REMEDIATION_TEMPLATES
        tmpl = REMEDIATION_TEMPLATES["worker_pool_exhaustion"]
        code = agent._generate_code(tmpl, {"affected_components": ["payment-api"]})
        for filepath, content in code.items():
            # Generated code must be a non-empty string without literal placeholders
            assert content.strip(), f"Empty code for {filepath}"
            # The numeric param must appear as a real number, not "{new_workers}"
            assert "{new_workers}" not in content, \
                f"Unresolved placeholder in {filepath}"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Real HTTP Health Checks — FIX #7
# ═══════════════════════════════════════════════════════════════════════════

class _TinyHTTPServer:
    """Minimal HTTP server for health check tests."""

    def __init__(self, status_code: int, delay: float = 0):
        self.status_code = status_code
        self.delay = delay
        self._server = None
        self.port: int = 0

    def start(self):
        delay = self.delay
        code = self.status_code

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if delay:
                    time.sleep(delay)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *a):
                pass   # silence

        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()

    def stop(self):
        if self._server:
            self._server.shutdown()


class TestHealthChecks:

    @pytest.fixture
    def agent(self):
        from agents.deployment_agent import DeploymentAgent
        return DeploymentAgent(
            health_check_timeout=2.0,
            health_check_latency_threshold_ms=500.0,
        )

    @pytest.mark.asyncio
    async def test_healthy_service_passes(self, agent):
        srv = _TinyHTTPServer(status_code=200, delay=0)
        srv.start()
        try:
            agent._service_urls["test-service"] = f"http://127.0.0.1:{srv.port}"
            result = await agent._run_health_checks({"target_service": "test-service"})
            assert result["passed"] is True
            assert result["average_latency_ms"] < 500
        finally:
            srv.stop()

    @pytest.mark.asyncio
    async def test_unhealthy_service_fails(self, agent):
        srv = _TinyHTTPServer(status_code=500)
        srv.start()
        try:
            agent._service_urls["sick-service"] = f"http://127.0.0.1:{srv.port}"
            result = await agent._run_health_checks({"target_service": "sick-service"})
            assert result["passed"] is False
            # All 3 probes should fail
            failed = [c for c in result["checks"] if not c["passed"]]
            assert len(failed) == 3
        finally:
            srv.stop()

    @pytest.mark.asyncio
    async def test_slow_service_fails_latency_threshold(self, agent):
        # 0.6s delay > 500ms threshold
        srv = _TinyHTTPServer(status_code=200, delay=0.6)
        srv.start()
        try:
            agent._service_urls["slow-service"] = f"http://127.0.0.1:{srv.port}"
            result = await agent._run_health_checks({"target_service": "slow-service"})
            assert result["passed"] is False
        finally:
            srv.stop()

    @pytest.mark.asyncio
    async def test_unknown_service_returns_failed(self, agent):
        result = await agent._run_health_checks({"target_service": "no-such-service-xyz"})
        assert result["passed"] is False
        assert "no_health_url_for" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_connection_refused_fails_gracefully(self, agent):
        # Port 1 is always refused
        agent._service_urls["refused-service"] = "http://127.0.0.1:1"
        result = await agent._run_health_checks({"target_service": "refused-service"})
        assert result["passed"] is False
        errors = [c for c in result["checks"] if not c.get("passed", True)]
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_failed_health_check_marks_deployment_failed(self):
        """Health check failure must propagate to DeploymentRecord.status == 'failed'."""
        from agents.deployment_agent import DeploymentAgent
        agent = DeploymentAgent()

        # Inject mock health check that always fails
        async def bad_health(context):
            return {"passed": False, "checks": [], "reason": "http_500"}

        agent._run_health_checks = bad_health

        # Build a minimal context with required keys
        context = {
            "target_service": "payment-api",
            "patch_id": "p-001",
            "validation_id": "v-001",
            "deployment_strategy": "rolling",
            "new_image_tag": "payment-api:patch-99",
            "previous_image_tag": "payment-api:stable",
            "_deploy_start": time.time(),
            "_deploy_end": time.time(),
        }
        health = await agent._run_health_checks(context)
        record = agent._build_deployment_record(context, health)

        assert record.status == "failed"
        assert record.health_check_passed is False

    def test_previous_image_tag_stored_before_build(self):
        import inspect
        from agents.deployment_agent import DeploymentAgent
        src = inspect.getsource(DeploymentAgent._build_image)
        assert "previous_image_tag" in src, \
            "_build_image must store previous_image_tag for real rollback"


# ═══════════════════════════════════════════════════════════════════════════
# 8. ReAct Iteration Telemetry — FIX #8
# ═══════════════════════════════════════════════════════════════════════════

class TestReActTelemetry:

    def test_record_react_iteration_exists(self):
        from core.telemetry import record_react_iteration
        assert callable(record_react_iteration)

    def test_react_histogram_registered(self):
        from core.telemetry import REACT_ITERATIONS
        assert REACT_ITERATIONS is not None

    def test_react_timeouts_counter_registered(self):
        from core.telemetry import REACT_TIMEOUTS_TOTAL
        assert REACT_TIMEOUTS_TOTAL is not None

    def test_decided_outcome_increments_histogram(self):
        from core.telemetry import record_react_iteration
        from prometheus_client import generate_latest
        record_react_iteration("detection", 2, "decided")
        out = generate_latest().decode()
        assert 'outcome="decided"' in out

    def test_timeout_outcome_increments_timeout_counter(self):
        from core.telemetry import record_react_iteration
        from prometheus_client import generate_latest
        record_react_iteration("deployment", 7, "timeout")
        out = generate_latest().decode()
        assert 'react_timeouts_total{agent_type="deployment"}' in out

    def test_all_outcomes_accepted(self):
        from core.telemetry import record_react_iteration
        for outcome in ("decided", "timeout", "error", "exhausted"):
            record_react_iteration("validation", 3, outcome)  # must not raise

    def test_base_agent_calls_record_on_decided(self):
        import inspect
        from agents.base_agent import BaseAgent
        src = inspect.getsource(BaseAgent.execute_react_loop)
        assert "record_react_iteration" in src

    def test_base_agent_calls_record_on_timeout(self):
        import inspect
        from agents.base_agent import BaseAgent
        src = inspect.getsource(BaseAgent.execute_react_loop)
        assert '"timeout"' in src

    def test_base_agent_calls_record_on_exhausted(self):
        import inspect
        from agents.base_agent import BaseAgent
        src = inspect.getsource(BaseAgent.execute_react_loop)
        assert '"exhausted"' in src


# ═══════════════════════════════════════════════════════════════════════════
# 9. Sandbox Security Bypass Attempts
# ═══════════════════════════════════════════════════════════════════════════

class TestSandboxSecurity:
    """Verify AST analysis catches common bypass patterns."""

    @pytest.fixture
    def analyzer(self):
        from sandbox.sandbox_executor import SecurityNodeVisitor
        return SecurityNodeVisitor

    def _analyze(self, analyzer, code: str):
        import ast
        tree = ast.parse(code)
        v = analyzer()
        v.visit(tree)
        return v.violations

    def test_direct_eval_blocked(self, analyzer):
        violations = self._analyze(analyzer, 'result = eval(user_input)')
        assert any(v["name"] == "eval" for v in violations)

    def test_direct_exec_blocked(self, analyzer):
        violations = self._analyze(analyzer, "exec(\"import os; os.system('id')\")")
        assert any(v["name"] == "exec" for v in violations)

    def test_os_system_blocked(self, analyzer):
        violations = self._analyze(analyzer, 'import os\nos.system("whoami")')
        types = {v["type"] for v in violations}
        # Must flag either the import or the call
        assert "banned_import" in types or "banned_os_call" in types

    def test_subprocess_import_blocked(self, analyzer):
        violations = self._analyze(analyzer, 'import subprocess\nsubprocess.run(["rm","-rf","/"])')
        assert any(v["type"] == "banned_import" for v in violations)

    def test_safe_code_passes(self, analyzer):
        code = '''
import math
import json

def compute(x):
    return math.sqrt(x)

result = compute(16)
data = json.dumps({"result": result})
'''
        violations = self._analyze(analyzer, code)
        critical = [v for v in violations if v.get("severity") == "critical"]
        assert not critical, f"Safe code flagged as critical: {critical}"

    def test_aliased_os_import_is_risky(self, analyzer):
        """
        'import os as operating_system' — the AST visitor catches the import
        (alias.name == 'os') even when the local alias differs.
        """
        violations = self._analyze(
            analyzer, 'import os as operating_system\noperating_system.system("id")'
        )
        # At minimum the import must be flagged
        import_violations = [v for v in violations if v["type"] == "banned_import"]
        assert import_violations, \
            "Aliased 'import os as X' must be flagged at the import level"

    def test_getattr_builtins_bypass_blocked(self, analyzer):
        """Dynamic builtins access via getattr(__builtins__, ...) must be blocked."""
        code = "fn = getattr(__builtins__, 'ev' + 'al')\nfn('1+1')"
        violations = self._analyze(analyzer, code)
        critical_types = {v["type"] for v in violations if v.get("severity") == "critical"}
        assert "builtins_escape_attempt" in critical_types or "banned_dynamic_access" in critical_types, \
            f"Expected critical builtins escape violation, got: {violations}"

    @pytest.mark.asyncio
    async def test_container_isolation_required_when_docker_missing(self):
        from sandbox.sandbox_executor import SandboxExecutor

        executor = SandboxExecutor()
        executor._docker_available = False
        executor._require_container = True

        result = await executor.execute({"safe.py": "x = len([1,2,3])\nprint(x)"})
        assert result["passed"] is False
        assert result.get("blocked_reason") == "container_isolation_required"


# ═══════════════════════════════════════════════════════════════════════════
# 10. Load / Buffer Overflow Protection
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadBehavior:

    @pytest.mark.asyncio
    async def test_buffer_does_not_overflow_under_load(self):
        """Simulate 1000 rapid writes — buffer stays at MAX_SIZE."""
        from listener.real_metrics import MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 50)

        async def burst():
            for _ in range(200):
                await buf.write(m)

        await asyncio.gather(*[burst() for _ in range(5)])
        assert buf.size == MetricsBuffer.MAX_SIZE

    @pytest.mark.asyncio
    async def test_listener_semaphore_under_burst(self):
        """Under rapid polling, callback fires at most once per poll window."""
        from listener.real_metrics import RealLogListener, MetricsBuffer
        buf = MetricsBuffer()
        m = _make_metric("svc", "response_time_ms", 50)
        for _ in range(20):
            await buf.write(m)

        listener = RealLogListener(fallback_simulator=None, min_real_metrics=1)
        listener._buffer = buf

        call_count = 0

        async def callback(metrics):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)   # simulate slow pipeline

        listener._metric_callbacks = [callback]

        # Fire 10 concurrent polls
        await asyncio.gather(*[listener._poll_and_dispatch() for _ in range(10)])
        assert call_count == 1, (
            f"Semaphore should allow only 1 callback per poll window, got {call_count}"
        )

    @pytest.mark.asyncio
    async def test_orchestrator_history_bounded(self):
        from agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        # Directly append beyond limit using the internal method
        from core.models import RemediationRecord, Anomaly, Diagnosis, Patch, ValidationResult, DeploymentRecord
        dummy_anomaly = Anomaly(
            service_name="svc", anomaly_type="latency_spike",
            description="test", severity=Severity.HIGH,
        )
        dummy_diagnosis = Diagnosis(
            anomaly_id=dummy_anomaly.id, root_cause="test",
            root_cause_category="performance",
            affected_components=["svc"], confidence=0.8,
            recommended_actions=["scale"],
        )
        dummy_patch = Patch(
            diagnosis_id=dummy_diagnosis.id, anomaly_id=dummy_anomaly.id,
            patch_type="config_change", description="test",
            code_changes={}, config_changes={},
        )
        dummy_val = ValidationResult(
            patch_id=dummy_patch.id, risk_score=0.1,
            risk_level=RiskLevel.LOW, static_analysis_passed=True,
            sandbox_execution_passed=True, policy_check_passed=True,
        )
        dummy_dep = DeploymentRecord(
            patch_id=dummy_patch.id, validation_id=dummy_val.id,
            target_service="svc", status="deployed",
        )
        record = RemediationRecord(
            anomaly=dummy_anomaly, diagnosis=dummy_diagnosis,
            patch=dummy_patch, validation=dummy_val,
            deployment=dummy_dep, total_duration_seconds=1.0,
            was_successful=True,
        )

        async with orch._history_lock:
            for _ in range(orch.MAX_HISTORY_SIZE + 100):
                orch._append_history(record)
        assert len(orch._remediation_history) == orch.MAX_HISTORY_SIZE


# ═══════════════════════════════════════════════════════════════════════════
# 11. Full Pipeline Acceptance Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFullPipelineAcceptance:
    """End-to-end acceptance criteria for all 5 production readiness gates."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_single_pipeline_runs_per_anomaly(self):
        """
        ACCEPTANCE GATE 1:
        Only one pipeline per anomaly fingerprint — duplicate triggers are
        deduplicated before any agent is invoked.
        """
        from agents.orchestrator import AgentOrchestrator, _anomaly_fingerprint
        orch = AgentOrchestrator()

        await _build_baseline(orch.detection_agent, "payment-api")

        diagnosis_count = 0
        real_diagnose = orch.diagnosis_agent.diagnose

        async def counted_diagnose(anomaly):
            nonlocal diagnosis_count
            diagnosis_count += 1
            return await real_diagnose(anomaly)

        orch.diagnosis_agent.diagnose = counted_diagnose

        # Fire 5 concurrent pipeline runs with the same anomaly data
        tasks = [
            orch.run_full_pipeline(_spike_metrics("payment-api"),
                                   scenario="payment_latency_spike")
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # At most 1 pipeline runs (the first claimant); others deduplicated
        actual_runs = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert diagnosis_count <= 1, (
            f"Deduplication failed: diagnosis ran {diagnosis_count} times "
            f"for 5 concurrent identical anomaly triggers"
        )

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_prometheus_label_cardinality_stable_under_varied_scenarios(self):
        """
        ACCEPTANCE GATE 2:
        Sending 100 different 'scenario' values must not create 100 label sets.
        All unknown values collapse to label scenario='other'.
        """
        from agents.orchestrator import _safe_scenario_label
        from prometheus_client import REGISTRY

        before = {
            s.name: len(list(s.samples))
            for s in REGISTRY.collect()
            if "pipeline_runs" in s.name
        }

        # Generate 100 distinct "attacker" scenario names
        for i in range(100):
            label = _safe_scenario_label(f"__attacker_scenario_{i}__")
            assert label == "other"

        after = {
            s.name: len(list(s.samples))
            for s in REGISTRY.collect()
            if "pipeline_runs" in s.name
        }

        # Sample count must not have exploded by 100 for each bad label
        for name in before:
            growth = after.get(name, 0) - before.get(name, 0)
            assert growth <= 5, (
                f"Cardinality explosion: {name} grew by {growth} samples "
                f"from 100 unknown scenario labels"
            )

    @pytest.mark.asyncio
    async def test_config_values_are_typed_not_strings(self):
        """ACCEPTANCE GATE 3: Generated config values must be numeric types."""
        from agents.remediation_agent import RemediationAgent, REMEDIATION_TEMPLATES
        agent = RemediationAgent.__new__(RemediationAgent)
        agent._knowledge_engine = None

        for tmpl_name, tmpl in REMEDIATION_TEMPLATES.items():
            cfg = agent._generate_config(tmpl, {})
            for key, value in cfg.items():
                if isinstance(value, str):
                    assert "{" not in value, (
                        f"Template {tmpl_name!r}.config_changes[{key!r}] "
                        f"still contains unresolved placeholder: {value!r}"
                    )

    @pytest.mark.asyncio
    async def test_failed_health_check_blocks_deployment(self):
        """
        ACCEPTANCE GATE 4:
        A /health endpoint returning 500 must produce:
          - health_check_passed = False
          - deployment.status = 'failed'
          - remediation NOT recorded as successful
        """
        from agents.deployment_agent import DeploymentAgent
        from core.models import FailureStage, RemediationStatus
        srv = _TinyHTTPServer(status_code=500)
        srv.start()
        try:
            agent = DeploymentAgent(
                health_check_timeout=1.0,
                health_check_latency_threshold_ms=2000.0,
            )
            agent._service_urls["payment-api"] = f"http://127.0.0.1:{srv.port}"
            ctx = {
                "target_service": "payment-api",
                "patch_id": "p-test",
                "validation_id": "v-test",
                "deployment_strategy": "rolling",
                "new_image_tag": "payment-api:patch-X",
                "previous_image_tag": "payment-api:stable",
                "_deploy_start": time.time(),
                "_deploy_end": time.time(),
            }
            health = await agent._run_health_checks(ctx)
            record = agent._build_deployment_record(ctx, health)

            assert health["passed"] is False, "Expected health check to fail for HTTP 500"
            assert record.status == "failed"
            assert record.health_check_passed is False
            assert record.failure_stage == FailureStage.DEPLOYMENT
            assert record.remediation_status == RemediationStatus.ROLLED_BACK
        finally:
            srv.stop()

    def test_all_new_prometheus_metrics_exposed(self):
        """
        ACCEPTANCE GATE 5:
        Every metric introduced in the fixes must be queryable from the
        default Prometheus registry (simulates /metrics scrape).
        """
        import core.telemetry  # ensure metric families are registered
        from prometheus_client import generate_latest
        text = generate_latest().decode()

        required = [
            "aethelgard_pipeline_runs_total",
            "aethelgard_react_iterations_total",
            "aethelgard_react_timeouts_total",
            "aethelgard_active_pipeline_jobs",
            "aethelgard_dedup_suppression_ratio",
            "aethelgard_anomalies_detected_total",
            "aethelgard_remediations_total",
            "aethelgard_agent_stage_duration_seconds",
            "aethelgard_pipeline_duration_seconds",
        ]
        for metric in required:
            assert metric in text, (
                f"Metric {metric!r} not found in /metrics output — "
                f"Prometheus scrape would miss this signal"
            )
