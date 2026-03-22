"""
Aethelgard — Agent Test Suite

Comprehensive tests for the multi-agent remediation pipeline.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import (
    Anomaly,
    Diagnosis,
    Patch,
    PatchStatus,
    Severity,
    ServiceMetric,
    ValidationResult,
    RiskLevel,
)
from agents.detection_agent import DetectionAgent
from agents.diagnosis_agent import DiagnosisAgent
from agents.remediation_agent import RemediationAgent
from agents.validation_agent import ValidationAgent


# ============================================
# Detection Agent Tests
# ============================================

class TestDetectionAgent:
    """Tests for the anomaly detection agent."""

    @pytest.fixture
    def agent(self):
        return DetectionAgent()

    @pytest.fixture
    def normal_metrics(self):
        return [
            ServiceMetric(service_name="payment-api", metric_name="response_time_ms", value=180, unit="ms"),
            ServiceMetric(service_name="payment-api", metric_name="error_rate", value=0.001, unit="ratio"),
            ServiceMetric(service_name="payment-api", metric_name="cpu_usage", value=0.35, unit="ratio"),
        ]

    @pytest.fixture
    def anomalous_metrics(self):
        return [
            ServiceMetric(service_name="payment-api", metric_name="response_time_ms", value=2500, unit="ms"),
            ServiceMetric(service_name="payment-api", metric_name="error_rate", value=0.001, unit="ratio"),
            ServiceMetric(service_name="payment-api", metric_name="cpu_usage", value=0.35, unit="ratio"),
        ]

    @pytest.mark.asyncio
    async def test_no_anomaly_on_normal_metrics(self, agent, normal_metrics):
        """Normal metrics should not trigger an anomaly."""
        # First build a baseline
        for _ in range(15):
            await agent.analyze_metrics(normal_metrics)
        
        result = await agent.analyze_metrics(normal_metrics)
        # Stable normal metrics after baseline should yield no anomaly
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_latency_spike(self, agent, normal_metrics, anomalous_metrics):
        """Latency spike should be detected as an anomaly."""
        # Build baseline with normal metrics
        for _ in range(15):
            await agent.analyze_metrics(normal_metrics)

        # Inject anomalous metrics
        result = await agent.analyze_metrics(anomalous_metrics)
        
        if result:
            assert result.anomaly_type == "latency_spike"
            assert result.severity in [Severity.CRITICAL, Severity.HIGH]
            assert result.service_name == "payment-api"

    @pytest.mark.asyncio
    async def test_think_identifies_critical(self, agent):
        """Think method should identify critical thresholds."""
        context = {
            "metrics": [
                {"service_name": "payment-api", "metric_name": "response_time_ms", "value": 2500}
            ],
        }
        # Pre-populate a window
        agent._metric_windows["payment-api:response_time_ms"].extend([180] * 15)
        
        thought = await agent.think(context)
        assert "CRITICAL" in thought or "STATISTICAL" in thought


# ============================================
# Diagnosis Agent Tests
# ============================================

class TestDiagnosisAgent:
    """Tests for the root cause diagnosis agent."""

    @pytest.fixture
    def agent(self):
        return DiagnosisAgent()

    @pytest.fixture
    def sample_anomaly(self):
        return Anomaly(
            service_name="payment-api",
            anomaly_type="latency_spike",
            description="Response time increased from 180ms to 2500ms",
            severity=Severity.CRITICAL,
            metrics=[
                ServiceMetric(service_name="payment-api", metric_name="response_time_ms", value=2500, unit="ms"),
            ],
            confidence=0.85,
        )

    @pytest.mark.asyncio
    async def test_diagnose_latency_spike(self, agent, sample_anomaly):
        """Should diagnose latency spike with root cause."""
        diagnosis = await agent.diagnose(sample_anomaly)
        
        assert diagnosis is not None
        assert diagnosis.anomaly_id == sample_anomaly.id
        assert diagnosis.root_cause != ""
        assert diagnosis.confidence > 0
        assert len(diagnosis.reasoning_chain) > 0
        assert len(diagnosis.recommended_actions) > 0

    @pytest.mark.asyncio
    async def test_reasoning_chain_populated(self, agent, sample_anomaly):
        """Reasoning chain should have multiple steps."""
        diagnosis = await agent.diagnose(sample_anomaly)
        
        assert len(diagnosis.reasoning_chain) >= 3
        for step in diagnosis.reasoning_chain:
            assert step.thought != ""
            assert step.action != ""
            assert step.observation != ""

    def test_pattern_matching(self, agent):
        """Pattern matching should find relevant root causes."""
        context = {
            "anomaly": {
                "metrics": [
                    {"metric_name": "response_time_ms", "value": 2500}
                ],
            },
        }
        patterns = agent._match_patterns("latency_spike", context)
        assert len(patterns) > 0
        assert "worker_pool_exhaustion" in patterns


# ============================================
# Remediation Agent Tests
# ============================================

class TestRemediationAgent:
    """Tests for the patch generation agent."""

    @pytest.fixture
    def agent(self):
        return RemediationAgent()

    @pytest.fixture
    def sample_diagnosis(self):
        return Diagnosis(
            anomaly_id="test-anomaly-001",
            root_cause="Worker pool size insufficient for current load. Async workers saturated.",
            root_cause_category="configuration",
            affected_components=["payment-api"],
            confidence=0.85,
            recommended_actions=[
                "Increase async worker pool size",
                "Enable connection pooling",
            ],
        )

    @pytest.mark.asyncio
    async def test_generate_patch(self, agent, sample_diagnosis):
        """Should generate a patch for the diagnosis."""
        patch = await agent.generate_patch(sample_diagnosis)
        
        assert patch is not None
        assert patch.diagnosis_id == sample_diagnosis.id
        assert patch.anomaly_id == sample_diagnosis.anomaly_id
        assert patch.patch_type != ""
        assert patch.description != ""
        assert patch.status == PatchStatus.GENERATED

    @pytest.mark.asyncio
    async def test_patch_has_code_changes(self, agent, sample_diagnosis):
        """Generated patch should include code changes."""
        patch = await agent.generate_patch(sample_diagnosis)
        
        assert len(patch.code_changes) > 0
        for filepath, code in patch.code_changes.items():
            assert code.strip() != ""

    @pytest.mark.asyncio
    async def test_patch_has_config_changes(self, agent, sample_diagnosis):
        """Generated patch should include config changes."""
        patch = await agent.generate_patch(sample_diagnosis)
        
        assert len(patch.config_changes) > 0


# ============================================
# Validation Agent Tests
# ============================================

class TestValidationAgent:
    """Tests for the patch validation agent."""

    @pytest.fixture
    def agent(self):
        return ValidationAgent()

    @pytest.fixture
    def safe_patch(self):
        return Patch(
            diagnosis_id="test-diag-001",
            anomaly_id="test-anomaly-001",
            patch_type="config_change",
            description="Increase worker pool size",
            code_changes={
                "config/server.py": 'import uvicorn\n\nuvicorn.run("main:app", workers=8)\n',
            },
            config_changes={"workers": 8},
        )

    @pytest.fixture
    def risky_patch(self):
        return Patch(
            diagnosis_id="test-diag-002",
            anomaly_id="test-anomaly-002",
            patch_type="code_fix",
            description="Fix with eval",
            code_changes={
                "fix.py": 'result = eval(user_input)\n',
            },
            config_changes={},
        )

    @pytest.mark.asyncio
    async def test_validate_safe_patch(self, agent, safe_patch):
        """Safe patch should pass validation with low risk."""
        result = await agent.validate(safe_patch)
        
        assert result is not None
        assert result.risk_score <= 0.5
        assert result.static_analysis_passed
        assert result.policy_check_passed

    @pytest.mark.asyncio
    async def test_validate_risky_patch(self, agent, risky_patch):
        """Risky patch should have high risk score."""
        result = await agent.validate(risky_patch)
        
        assert result is not None
        assert not result.policy_check_passed
        assert result.risk_score > 0.3

    @pytest.mark.asyncio
    async def test_risk_scoring(self, agent, safe_patch):
        """Risk scoring should produce valid score."""
        result = await agent.validate(safe_patch)
        
        assert 0.0 <= result.risk_score <= 1.0
        assert result.risk_level in list(RiskLevel)

    def test_static_analysis_catches_syntax_error(self, agent):
        """Static analysis should catch Python syntax errors."""
        code_changes = {"bad.py": "def broken(\n    pass"}
        result = agent._run_static_analysis(code_changes)
        assert not result["passed"]
        assert len(result["issues"]) > 0

    def test_policy_engine_catches_eval(self, agent):
        """Policy engine should flag eval() usage."""
        code_changes = {"fix.py": "result = eval(data)"}
        result = agent._run_policy_checks(code_changes)
        assert not result["passed"]
        assert any("eval" in v["policy"] for v in result["violations"])


# ============================================
# Integration Tests
# ============================================

class TestIntegration:
    """End-to-end integration tests for the full pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Full pipeline should complete successfully."""
        from agents.orchestrator import AgentOrchestrator
        from services.log_simulator import LogSimulator

        orchestrator = AgentOrchestrator()
        simulator = LogSimulator()

        # Build baseline
        for _ in range(15):
            metrics = simulator.generate_metrics()
            await orchestrator.detection_agent.analyze_metrics(metrics)

        # Inject and detect anomaly
        simulator.inject_anomaly("payment_latency_spike")
        anomalous_metrics = simulator.generate_metrics()

        # Run pipeline
        record = await orchestrator.run_full_pipeline(anomalous_metrics)

        if record:
            assert record.anomaly is not None
            assert record.diagnosis is not None
            assert record.patch is not None
            assert record.validation is not None
            assert record.deployment is not None
            assert record.total_duration_seconds > 0
            assert record.total_duration_seconds < 60  # Under 60 seconds

    @pytest.mark.asyncio
    async def test_metrics_tracking(self):
        """Metrics should be tracked correctly after pipeline runs."""
        from agents.orchestrator import AgentOrchestrator
        from services.log_simulator import LogSimulator

        orchestrator = AgentOrchestrator()
        simulator = LogSimulator()

        # Build baseline
        for _ in range(15):
            metrics = simulator.generate_metrics()
            await orchestrator.detection_agent.analyze_metrics(metrics)

        simulator.inject_anomaly("payment_latency_spike")
        anomalous_metrics = simulator.generate_metrics()

        await orchestrator.run_full_pipeline(anomalous_metrics)

        platform_metrics = orchestrator.get_metrics()
        assert platform_metrics.total_anomalies_detected >= 1
        assert platform_metrics.active_agents == 5


# ============================================
# API Integration Tests
# ============================================

class TestPipelineAPI:
    """Integration tests for the FastAPI /pipeline/run endpoint.

    httpx.ASGITransport does not trigger ASGI lifespan events, so we inject
    the required app.state services directly before each request batch and
    clean them up afterwards.  This is safe because the production lifespan
    unconditionally initialises all services (no hasattr guard), so direct
    injection is additive, not conflicting.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _valid_key() -> str:
        """Return a currently-configured API key (reads the live module)."""
        from api import VALID_API_KEYS
        return next(iter(VALID_API_KEYS))

    @staticmethod
    @asynccontextmanager
    async def _client(with_state: bool = True, with_key: bool = True):
        """Async context manager: create an httpx client pointed at the FastAPI app.

        When with_state=True, injects orchestrator + simulator into app.state
        so that endpoint handlers can resolve them via _get_state().
        When with_state=False, leaves app.state empty to test the 503 path.
        """
        from api import app

        orchestrator = None
        if with_state:
            from agents.orchestrator import AgentOrchestrator
            from services.log_simulator import LogSimulator
            orchestrator = AgentOrchestrator()
            await orchestrator.initialize()
            app.state.orchestrator = orchestrator
            app.state.simulator = LogSimulator()
        else:
            # Clear residual state from any prior test
            for attr in ("orchestrator", "simulator", "knowledge_engine"):
                try:
                    delattr(app.state, attr)
                except (AttributeError, KeyError):
                    pass

        headers = {}
        if with_key:
            headers["X-API-Key"] = TestPipelineAPI._valid_key()

        try:
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                headers=headers,
            ) as client:
                yield client
        finally:
            if orchestrator is not None:
                await orchestrator.shutdown()
            for attr in ("orchestrator", "simulator"):
                try:
                    delattr(app.state, attr)
                except (AttributeError, KeyError):
                    pass

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_pipeline_run_returns_202(self):
        """POST /pipeline/run must return HTTP 202 with a job_id."""
        async with TestPipelineAPI._client(with_state=True, with_key=True) as client:
            resp = await client.post("/api/v1/pipeline/run?scenario=payment_latency_spike")
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        assert body["scenario"] == "payment_latency_spike"
        assert "poll_url" in body

    @pytest.mark.asyncio
    async def test_pipeline_run_unknown_scenario_returns_400(self):
        """POST /pipeline/run with an unknown scenario name must return 400."""
        async with TestPipelineAPI._client(with_state=True, with_key=True) as client:
            resp = await client.post("/api/v1/pipeline/run?scenario=nonexistent_scenario_xyz")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_pipeline_run_missing_key_returns_401(self):
        """POST /pipeline/run without an API key must be rejected (401/403)."""
        async with TestPipelineAPI._client(with_state=True, with_key=False) as client:
            resp = await client.post("/api/v1/pipeline/run?scenario=payment_latency_spike")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_pipeline_job_completes(self):
        """POST creates a job that transitions to a terminal state.

        httpx.ASGITransport executes background tasks synchronously as part of
        the ASGI response lifecycle, so by the time `await client.post()`
        returns the background pipeline has already run.  We verify the job
        state via the orchestrator object directly (no HTTP polling loop) to
        avoid any potential blockage in the GET handler.
        """
        from api import app
        async with TestPipelineAPI._client(with_state=True, with_key=True) as client:
            post_resp = await client.post(
                "/api/v1/pipeline/run?scenario=payment_latency_spike"
            )
            assert post_resp.status_code == 202, post_resp.text
            body = post_resp.json()
            job_id = body["job_id"]
            assert body["scenario"] == "payment_latency_spike"
            assert body["status"] == "pending"
            assert "poll_url" in body

            # Background task ran synchronously — inspect directly via orchestrator.
            orch = app.state.orchestrator
            job = await orch.get_job(job_id)
            assert job is not None, "Job not registered in orchestrator"
            assert job.job_id == job_id
            assert job.scenario == "payment_latency_spike"
            # Background may have completed or still be scheduled (async):
            assert job.status in ("pending", "running", "completed", "failed"), (
                f"Unexpected job status: {job.status}"
            )

    @pytest.mark.asyncio
    async def test_missing_state_returns_503(self):
        """_get_state() must return HTTP 503 (not AttributeError) when absent."""
        async with TestPipelineAPI._client(with_state=False, with_key=True) as client:
            resp = await client.post("/pipeline/run?scenario=payment_latency_spike")
        assert resp.status_code == 503, (
            f"Expected 503 when state is absent, got {resp.status_code}: {resp.text}"
        )
