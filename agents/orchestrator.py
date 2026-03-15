"""
Aethelgard v2 — Agent Orchestrator (Production-Grade)
=======================================================

FIXES APPLIED IN THIS VERSION:
─────────────────────────────────────────────────────
FIX #2  — OTel spans embedded directly in run_full_pipeline().
           ObservableOrchestrator wrapper REMOVED (it was a bug:
           background jobs called base.run_full_pipeline which had zero spans).
           Instrumentation now lives where the code executes.

FIX #3  — asyncio.Lock on all shared mutable state:
           _remediation_history, _jobs, _metrics, running totals.
           Per-service remediation mutex prevents concurrent fixes
           to the same service from race-deploying conflicting patches.

FIX #4  — Anomaly fingerprint deduplication:
           fingerprint = sha256(service + anomaly_type + severity)
           Active fingerprints tracked; duplicate triggers skipped.
           Fingerprint released after pipeline completes or fails.

FIX #5  — Prometheus cardinality fix:
           'scenario' label allowlisted to KNOWN_SCENARIOS set.
           Unknown values mapped to "other" so Prometheus cardinality
           stays bounded regardless of API input.

FIX #8  — ReAct iteration histogram (aethelgard_react_iterations_histogram)
           emitted from the base agent via record_react_iteration().
─────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from opentelemetry import trace as otel_trace

from agents.detection_agent import DetectionAgent
from agents.diagnosis_agent import DiagnosisAgent
from agents.remediation_agent import RemediationAgent
from agents.validation_agent import ValidationAgent
from agents.deployment_agent import DeploymentAgent
from core.config import get_settings
from core.logging_config import get_logger
from core.models import (
    Anomaly,
    Diagnosis,
    DeploymentRecord,
    EventType,
    FailureStage,
    Patch,
    PlatformMetrics,
    RemediationStatus,
    RemediationRecord,
    ServiceMetric,
    ValidationResult,
)
from core.telemetry import (
    tracer,
    agent_span,
    ACTIVE_PIPELINE_JOBS,
    PIPELINE_RUNS_TOTAL,
    PIPELINE_DURATION_SECONDS,
    ANOMALIES_DETECTED_TOTAL,
    REMEDIATIONS_TOTAL,
    MTTD_SECONDS,
    MTTR_SECONDS,
    DIAGNOSIS_CONFIDENCE,
    RISK_SCORE_DISTRIBUTION,
    AUTONOMOUS_RESOLUTION_RATE,
    ENGINEERING_HOURS_SAVED,
    ROI_DOLLARS,
    KNOWLEDGE_BASE_DOCUMENTS,
    LEARNING_STORES_TOTAL,
    DEPLOYMENT_GUARDRAIL_BLOCKS_TOTAL,
    VALIDATION_FAILURES_TOTAL,
    telemetry_health_status,
    record_dedup_suppression_ratio,
    record_pipeline_run,
    record_rag_query,
)

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# FIX #5 — Allowlisted scenario labels (cardinality guard)
# ─────────────────────────────────────────────────────────────
KNOWN_SCENARIOS: Set[str] = {
    "payment_latency_spike",
    "high_memory_usage",
    "database_connection_exhaustion",
    "cpu_saturation",
    "error_rate_spike",
    "worker_pool_exhaustion",
    "queue_buildup",
    "disk_saturation",
    "dependency_failure",
    "connection_exhaustion",
    "real_traffic",       # set by RealLogListener when using real metrics
    "unknown",
    "other",
}


def _safe_scenario_label(scenario: str) -> str:
    """Map free-form scenario string to allowlisted label value."""
    return scenario if scenario in KNOWN_SCENARIOS else "other"


# ─────────────────────────────────────────────────────────────
# FIX #4 — Anomaly fingerprint
# ─────────────────────────────────────────────────────────────

def _anomaly_fingerprint(service: str, anomaly_type: str, severity: str) -> str:
    """
    Deterministic fingerprint for an anomaly class.

    Two anomalies with the same (service, type, severity) get the same
    fingerprint. The orchestrator uses this to deduplicate concurrent
    pipeline triggers for the same underlying incident.
    """
    raw = f"{service}:{anomaly_type}:{severity}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class PipelineJob:
    """
    Tracks the state of an async background pipeline execution.
    Lifecycle: PENDING → RUNNING → AWAITING_APPROVAL → COMPLETED / FAILED
    """

    def __init__(self, job_id: str, scenario: str):
        self.job_id = job_id
        self.scenario = scenario
        self.status: str = "pending"
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.record: Optional[RemediationRecord] = None
        self.error: Optional[str] = None
        # Store anomaly_type, patch_type for API responses
        self.anomaly_type: Optional[str] = None
        self.patch_type: Optional[str] = None
        self.deployed: bool = False
        self.remediation_status: Optional[str] = None
        self.failure_stage: Optional[str] = None
        self.failure_reason: Optional[str] = None
        # Approval workflow state
        self.awaiting_approval: bool = False
        self._approval_context: Optional[Dict[str, Any]] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return round(self.finished_at - self.started_at, 3)
        return None

    def set_approval_context(self, context: Dict[str, Any]) -> None:
        """Store state needed to continue deployment after approval."""
        self._approval_context = context

    def get_approval_context(self) -> Optional[Dict[str, Any]]:
        """Retrieve stored approval context."""
        return self._approval_context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "scenario": self.scenario,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "anomaly_type": self.anomaly_type,
            "patch_type": self.patch_type,
            "deployed": self.deployed,
            "remediation_status": self.remediation_status,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "record": self.record.id if self.record else None,
            "awaiting_approval": self.awaiting_approval,
        }


class AgentOrchestrator:
    """
    Production-grade explicit-pipeline orchestrator.

    Design contract:
    ─────────────────────────────────────────────────────────────────────
    ✅ OTel spans embedded directly in run_full_pipeline() (FIX #2)
    ✅ asyncio.Lock on ALL shared mutable state (FIX #3)
    ✅ Per-service mutex prevents concurrent conflicting deployments (FIX #3)
    ✅ Anomaly fingerprint deduplication (FIX #4)
    ✅ Prometheus scenario label allowlisted (FIX #5)
    ✅ Learning system write path after every successful deployment
    ✅ Background job registry with bounded eviction
    ─────────────────────────────────────────────────────────────────────
    """

    MAX_HISTORY_SIZE = 500

    def __init__(self, knowledge_engine=None, sandbox_executor=None, docker_remediator=None):
        self._settings = get_settings()
        self._knowledge_engine = knowledge_engine
        self._sandbox_executor = sandbox_executor

        self.detection_agent = DetectionAgent()
        self.diagnosis_agent = DiagnosisAgent(knowledge_engine=knowledge_engine)
        self.remediation_agent = RemediationAgent(knowledge_engine=knowledge_engine)
        self.validation_agent = ValidationAgent(sandbox_executor=sandbox_executor)
        self.deployment_agent = DeploymentAgent(docker_remediator=docker_remediator)

        # ── FIX #3: Locks for all shared mutable state ────────────────
        self._history_lock = asyncio.Lock()
        self._jobs_lock = asyncio.Lock()
        self._metrics_lock = asyncio.Lock()

        # Per-service remediation mutex: prevents two concurrent pipeline
        # runs from racing to deploy conflicting patches to the same service
        self._service_locks: Dict[str, asyncio.Lock] = {}
        self._service_locks_lock = asyncio.Lock()  # protects the dict itself

        # ── FIX #4: Active anomaly fingerprint registry ────────────────
        self._active_fingerprints: Set[str] = set()
        self._recent_fingerprints: Dict[str, float] = {}
        self._fingerprints_lock = asyncio.Lock()
        self._fingerprint_ttl_seconds: float = self._settings.dedup.fingerprint_ttl_seconds

        # Dedup pressure counters (for suppression ratio metric)
        self._total_pipeline_triggers: int = 0
        self._deduplicated_triggers: int = 0

        # State
        self._remediation_history: List[RemediationRecord] = []
        self._jobs: Dict[str, PipelineJob] = {}
        self._pipeline_outcomes: collections.OrderedDict[str, Dict[str, Optional[str]]] = collections.OrderedDict()

        # O(1) running metrics totals
        self._total_mttd: float = 0.0
        self._total_mttr: float = 0.0
        self._total_pipeline_latency_ms: float = 0.0
        self._total_sandbox_duration_seconds: float = 0.0
        self._success_count: int = 0
        self._metrics = PlatformMetrics()

    # ─────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        logger.info("orchestrator_initializing")
        await self.detection_agent.initialize()
        await self.diagnosis_agent.initialize()
        await self.remediation_agent.initialize()
        await self.validation_agent.initialize()
        await self.deployment_agent.initialize()
        logger.info("orchestrator_ready", agents=5,
                    mode="explicit_pipeline_instrumented",
                    learning="enabled",
                    deduplication="enabled",
                    concurrency_safe="true")

    async def shutdown(self) -> None:
        logger.info("orchestrator_shutting_down")
        for agent in [
            self.detection_agent, self.diagnosis_agent,
            self.remediation_agent, self.validation_agent,
            self.deployment_agent,
        ]:
            await agent.shutdown()

    async def approve_deployment(self, job_id: str) -> Optional[RemediationRecord]:
        """
        Approve a pending deployment and resume the pipeline.
        Called when user approves via POST /pipeline/{jobId}/approve.
        """
        async with self._jobs_lock:
            if job_id not in self._jobs:
                logger.warning("approve_deployment_job_not_found", job_id=job_id)
                return None

            job = self._jobs[job_id]
            if not job.awaiting_approval:
                logger.warning("approve_deployment_not_awaiting", job_id=job_id, status=job.status)
                return None

            context = job.get_approval_context()
            if not context:
                logger.error("approve_deployment_no_context", job_id=job_id)
                return None

        # Resume deployment with stored context
        try:
            anomaly = context["anomaly"]
            patch = context["patch"]
            validation = context["validation"]
            cid = context["cid"]
            service_lock = context["service_lock"]

            logger.info("deployment_approved",
                        job_id=job_id,
                        correlation_id=cid,
                        service=anomaly.service_name)

            # Execute deployment now that approval is granted
            async with service_lock:
                deployment = await self.deployment_agent.deploy(
                    validation=validation,
                    patch_data={
                        "code_changes": patch.code_changes,
                        "config_changes": patch.config_changes,
                    },
                    target_service=anomaly.service_name,
                )

            # Update job status
            async with self._jobs_lock:
                if job_id in self._jobs:
                    job = self._jobs[job_id]
                    job.awaiting_approval = False
                    job.deployed = deployment.health_check_passed if deployment else False
                    job.remediation_status = "success" if deployment and deployment.status == "deployed" else "failed"
                    if deployment:
                        job.set_approval_context(None)

            logger.info("deployment_post_approval_complete",
                        job_id=job_id,
                        status=deployment.status if deployment else "skipped")

            return deployment

        except Exception as e:
            logger.error("approval_deployment_failed",
                         job_id=job_id,
                         error=str(e))
            async with self._jobs_lock:
                if job_id in self._jobs:
                    job = self._jobs[job_id]
                    job.error = str(e)
                    job.remediation_status = "failed"
            return None

    # ─────────────────────────────────────────────────────────────
    # FIX #3 — Per-service lock helper
    # ─────────────────────────────────────────────────────────────

    async def _get_service_lock(self, service_name: str) -> asyncio.Lock:
        """
        Return (creating if needed) the per-service remediation mutex.
        The double-lock pattern ensures the outer dict is itself safe.
        """
        async with self._service_locks_lock:
            if service_name not in self._service_locks:
                self._service_locks[service_name] = asyncio.Lock()
            return self._service_locks[service_name]

    # ─────────────────────────────────────────────────────────────
    # FIX #4 — Fingerprint deduplication helpers
    # ─────────────────────────────────────────────────────────────

    async def _claim_fingerprint(self, fp: str) -> bool:
        """
        Atomically claim a fingerprint. Returns True if claimed (proceed),
        False if already active (skip — duplicate incident).
        """
        async with self._fingerprints_lock:
            now = time.time()
            # Evict expired recent fingerprints
            expired = [k for k, expiry in self._recent_fingerprints.items() if expiry <= now]
            for k in expired:
                self._recent_fingerprints.pop(k, None)

            if fp in self._active_fingerprints:
                return False
            if fp in self._recent_fingerprints:
                return False
            self._active_fingerprints.add(fp)
            return True

    async def _release_fingerprint(self, fp: str) -> None:
        async with self._fingerprints_lock:
            self._active_fingerprints.discard(fp)
            self._recent_fingerprints[fp] = time.time() + self._fingerprint_ttl_seconds

    async def _record_dedup_outcome(self, was_deduplicated: bool) -> None:
        """Track dedup pressure and emit suppression ratio."""
        async with self._metrics_lock:
            self._total_pipeline_triggers += 1
            if was_deduplicated:
                self._deduplicated_triggers += 1
            record_dedup_suppression_ratio(
                deduplicated_triggers=self._deduplicated_triggers,
                total_triggers=self._total_pipeline_triggers,
            )

    async def _set_pipeline_outcome(
        self,
        correlation_id: str,
        remediation_status: Optional[str],
        failure_stage: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        async with self._jobs_lock:
            self._pipeline_outcomes[correlation_id] = {
                "remediation_status": remediation_status,
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
            }
            # Bounded eviction — prevent unbounded memory growth
            if len(self._pipeline_outcomes) > 500:
                oldest = next(iter(self._pipeline_outcomes))
                del self._pipeline_outcomes[oldest]

    @staticmethod
    def _derive_remediation_status(
        validation: ValidationResult,
        deployment: Optional[DeploymentRecord],
    ) -> RemediationStatus:
        if deployment and deployment.status == "pending" and deployment.remediation_status == RemediationStatus.AWAITING_APPROVAL:
            return RemediationStatus.AWAITING_APPROVAL
        if deployment and deployment.status == "blocked":
            return RemediationStatus.VALIDATION_FAILED
        if deployment and deployment.status == "rolled_back":
            return RemediationStatus.ROLLED_BACK
        if not validation.sandbox_execution_passed:
            return RemediationStatus.SANDBOX_FAILED
        if not validation.is_safe_for_auto_deploy:
            return RemediationStatus.VALIDATION_FAILED
        return RemediationStatus.SUCCESS

    @staticmethod
    def _derive_failure_details(
        status: RemediationStatus,
        validation: ValidationResult,
        deployment: Optional[DeploymentRecord],
    ) -> tuple[Optional[FailureStage], Optional[str]]:
        if deployment and deployment.status == "blocked":
            return FailureStage.DEPLOYMENT, deployment.failure_reason or "deployment_guardrail_blocked"
        if status == RemediationStatus.SUCCESS:
            return None, None
        if status == RemediationStatus.ROLLED_BACK:
            reason = "deployment_rollback"
            if deployment and deployment.failure_reason:
                reason = deployment.failure_reason
            return FailureStage.DEPLOYMENT, reason
        if status == RemediationStatus.SANDBOX_FAILED:
            reason = "sandbox_execution_failed"
            if validation.issues:
                reason = validation.issues[0][:200]
            return FailureStage.VALIDATION, reason
        if status == RemediationStatus.VALIDATION_FAILED:
            reason = "validation_checks_failed"
            if validation.issues:
                reason = validation.issues[0][:200]
            return FailureStage.VALIDATION, reason
        return FailureStage.UNKNOWN, "unknown_failure"

    def _lock_state_consistent(self, expected_service_lock_held: bool = False, service_locked: bool = False) -> tuple[bool, str]:
        lock_fields = (
            self._history_lock,
            self._jobs_lock,
            self._metrics_lock,
            self._service_locks_lock,
            self._fingerprints_lock,
        )
        if any(not isinstance(lock, asyncio.Lock) for lock in lock_fields):
            return False, "invalid_lock_type"
        if expected_service_lock_held and not service_locked:
            return False, "service_lock_not_held"
        if any(not isinstance(lock, asyncio.Lock) for lock in self._service_locks.values()):
            return False, "service_lock_registry_corrupt"
        return True, "ok"

    def _deployment_guardrail_reason(
        self,
        validation: ValidationResult,
        *,
        service_locked: bool,
    ) -> Optional[str]:
        if not validation.static_analysis_passed:
            return "validation_static_failed"
        if not validation.policy_check_passed:
            return "validation_policy_failed"
        if not validation.tests_passed:
            return "validation_tests_failed"
        if not validation.sandbox_execution_passed:
            return "sandbox_failed"
        telemetry_ok, telemetry_reason = telemetry_health_status()
        if not telemetry_ok:
            return f"telemetry_unhealthy:{telemetry_reason}"
        locks_ok, lock_reason = self._lock_state_consistent(
            expected_service_lock_held=True,
            service_locked=service_locked,
        )
        if not locks_ok:
            return f"lock_state_inconsistent:{lock_reason}"
        return None

    # ─────────────────────────────────────────────────────────────
    # FIX #2 — Fully instrumented pipeline
    # ─────────────────────────────────────────────────────────────

    async def run_full_pipeline(
        self,
        metrics: List[ServiceMetric],
        correlation_id: Optional[str] = None,
        scenario: str = "unknown",
    ) -> Optional[RemediationRecord]:
        """
        Execute the complete autonomous remediation pipeline.

        FIX #2: OTel spans are created HERE, inside the method that
        BackgroundTasks actually calls. The ObservableOrchestrator wrapper
        is eliminated — it never traced background jobs because it delegated
        to base.run_job() → base.run_full_pipeline() (uninstrumented).

        Span hierarchy:
          pipeline.run
            ├── agent.detection.analyze_metrics
            ├── agent.diagnosis.diagnose
            ├── agent.remediation.generate_patch
            ├── agent.validation.validate
            ├── agent.deployment.deploy
            └── pipeline.learning_store  (on success)
        """
        pipeline_start = time.time()
        # FIX #5: safe label
        safe_scenario = _safe_scenario_label(scenario)
        cid = correlation_id or f"pipeline-{uuid.uuid4().hex[:12]}"

        # Root OTel span for this pipeline run
        with tracer.start_as_current_span(
            "pipeline.run",
            attributes={
                "pipeline.correlation_id": cid,
                "pipeline.scenario": safe_scenario,
                "pipeline.metric_count": len(metrics),
                "service_name": metrics[0].service_name if metrics else "unknown",
            },
        ) as root_span:
            ACTIVE_PIPELINE_JOBS.inc()
            try:
                return await self._execute_pipeline_stages(
                    metrics=metrics,
                    cid=cid,
                    safe_scenario=safe_scenario,
                    pipeline_start=pipeline_start,
                    root_span=root_span,
                )
            except Exception as e:
                root_span.set_status(otel_trace.StatusCode.ERROR, str(e))
                root_span.record_exception(e)
                await self._record_dedup_outcome(was_deduplicated=False)
                await self._set_pipeline_outcome(
                    cid,
                    remediation_status=RemediationStatus.VALIDATION_FAILED.value,
                    failure_stage=FailureStage.UNKNOWN.value,
                    failure_reason=str(e)[:200],
                )
                PIPELINE_RUNS_TOTAL.labels(
                    scenario=safe_scenario, status=RemediationStatus.VALIDATION_FAILED.value
                ).inc()
                logger.error("pipeline_error",
                             correlation_id=cid,
                             error=str(e),
                             duration_seconds=round(time.time() - pipeline_start, 3))
                raise
            finally:
                ACTIVE_PIPELINE_JOBS.dec()

    async def _execute_pipeline_stages(
        self,
        metrics: List[ServiceMetric],
        cid: str,
        safe_scenario: str,
        pipeline_start: float,
        root_span,
    ) -> Optional[RemediationRecord]:
        """Inner pipeline logic — runs inside the root OTel span.

        History writes are guarded by `_history_lock` in `_run_instrumented_stages`.
        """

        logger.info("pipeline_started", correlation_id=cid,
                    metric_count=len(metrics))

        # ── FIX A: Entry dedup gate (earliest possible point) ─────────
        # Prevents N concurrent identical triggers from all running
        # expensive detection/diagnosis in parallel.
        service_hint = metrics[0].service_name if metrics else "unknown"
        entry_fp = _anomaly_fingerprint(service_hint, f"scenario:{safe_scenario}", "entry")
        entry_claimed = await self._claim_fingerprint(entry_fp)
        if not entry_claimed:
            await self._record_dedup_outcome(was_deduplicated=True)
            await self._set_pipeline_outcome(
                cid,
                remediation_status=RemediationStatus.DEDUPLICATED.value,
                failure_stage=FailureStage.DEDUPLICATION.value,
                failure_reason="entry_fingerprint_conflict",
            )
            logger.info("pipeline_entry_deduplicated",
                        correlation_id=cid,
                        fingerprint=entry_fp,
                        service=service_hint,
                        scenario=safe_scenario,
                        remediation_status=RemediationStatus.DEDUPLICATED.value)
            root_span.set_attribute("pipeline.deduplicated", True)
            root_span.set_attribute("pipeline.fingerprint", entry_fp)
            root_span.set_attribute("pipeline.dedup_stage", "entry")
            PIPELINE_RUNS_TOTAL.labels(
                scenario=safe_scenario, status=RemediationStatus.DEDUPLICATED.value
            ).inc()
            return None

        try:
            # ── Stage 1: DETECTION ─────────────────────────────────────────
            with agent_span("detection", "analyze_metrics", {
                "metric_count": len(metrics),
            }) as det_span:
                anomaly: Optional[Anomaly] = await self.detection_agent.analyze_metrics(metrics)

                if not anomaly:
                    await self._record_dedup_outcome(was_deduplicated=False)
                    await self._set_pipeline_outcome(
                        cid,
                        remediation_status=None,
                        failure_stage=None,
                        failure_reason=None,
                    )
                    det_span.set_attribute("anomaly.detected", False)
                    logger.info("pipeline_no_anomaly", correlation_id=cid)
                    return None

                det_span.set_attribute("anomaly.detected", True)
                det_span.set_attribute("anomaly.type", anomaly.anomaly_type)
                det_span.set_attribute("anomaly.severity", anomaly.severity.value)
                det_span.set_attribute("anomaly.service", anomaly.service_name)
                det_span.set_attribute("anomaly.confidence", anomaly.confidence)

            # ── FIX #4: Deduplication check ────────────────────────────────
            fp = _anomaly_fingerprint(
                anomaly.service_name, anomaly.anomaly_type, anomaly.severity.value
            )
            claimed = await self._claim_fingerprint(fp)
            if not claimed:
                await self._record_dedup_outcome(was_deduplicated=True)
                await self._set_pipeline_outcome(
                    cid,
                    remediation_status=RemediationStatus.DEDUPLICATED.value,
                    failure_stage=FailureStage.DEDUPLICATION.value,
                    failure_reason="anomaly_fingerprint_conflict",
                )
                logger.info("pipeline_duplicate_skipped",
                            correlation_id=cid,
                            fingerprint=fp,
                            service=anomaly.service_name,
                            anomaly_type=anomaly.anomaly_type,
                            remediation_status=RemediationStatus.DEDUPLICATED.value)
                root_span.set_attribute("pipeline.deduplicated", True)
                root_span.set_attribute("pipeline.fingerprint", fp)
                root_span.set_attribute("pipeline.dedup_stage", "anomaly")
                PIPELINE_RUNS_TOTAL.labels(
                    scenario=safe_scenario, status=RemediationStatus.DEDUPLICATED.value
                ).inc()
                return None

            root_span.set_attribute("pipeline.fingerprint", fp)

            try:
                return await self._run_instrumented_stages(
                    anomaly=anomaly,
                    fp=fp,
                    cid=cid,
                    safe_scenario=safe_scenario,
                    pipeline_start=pipeline_start,
                    root_span=root_span,
                )
            finally:
                # Always release anomaly fingerprint whether success or failure
                await self._release_fingerprint(fp)
        finally:
            # Always release the entry fingerprint whether success or failure
            await self._release_fingerprint(entry_fp)

    async def _run_instrumented_stages(
        self,
        anomaly: Anomaly,
        fp: str,
        cid: str,
        safe_scenario: str,
        pipeline_start: float,
        root_span,
    ) -> Optional[RemediationRecord]:
        """
        Stages 2-6 with per-service mutex (FIX #3) and full OTel spans.
        """
        stage_order = ("detection", "diagnosis", "remediation", "validation", "deployment", "verification")
        root_span.set_attribute("pipeline.stage_order", ",".join(stage_order))

        ANOMALIES_DETECTED_TOTAL.labels(
            anomaly_type=anomaly.anomaly_type,
            severity=anomaly.severity.value,
            service=anomaly.service_name,
        ).inc()

        async with self._metrics_lock:
            self._metrics.total_anomalies_detected += 1

        logger.info("pipeline_anomaly_detected",
                    anomaly_id=anomaly.id,
                    service=anomaly.service_name,
                    type=anomaly.anomaly_type,
                    severity=anomaly.severity.value,
                    fingerprint=fp,
                    correlation_id=cid)

        # ── FIX #3: Acquire per-service mutex ─────────────────────────
        service_lock = await self._get_service_lock(anomaly.service_name)

        async with service_lock:
            logger.debug("service_lock_acquired",
                         service=anomaly.service_name,
                         correlation_id=cid)

            # ── Stage 2: DIAGNOSIS ─────────────────────────────────────
            with agent_span("diagnosis", "diagnose", {
                "anomaly.id": anomaly.id,
                "anomaly.type": anomaly.anomaly_type,
                "service_name": anomaly.service_name,
            }) as diag_span:
                t0 = time.time()
                diagnosis: Diagnosis = await self.diagnosis_agent.diagnose(anomaly)
                rag_dur = time.time() - t0

                diag_span.set_attribute("diagnosis.root_cause", diagnosis.root_cause[:120])
                diag_span.set_attribute("diagnosis.confidence", diagnosis.confidence)
                diag_span.set_attribute("diagnosis.category", diagnosis.root_cause_category)
                diag_span.set_attribute("diagnosis.knowledge_refs",
                                        len(diagnosis.knowledge_references))

                record_rag_query(
                    duration=rag_dur,
                    backend=getattr(self._knowledge_engine, "_backend", "unknown"),
                    results_count=len(diagnosis.knowledge_references),
                )
                logger.info("pipeline_diagnosis_complete",
                            diagnosis_id=diagnosis.id,
                            root_cause=diagnosis.root_cause[:80],
                            confidence=diagnosis.confidence,
                            correlation_id=cid)

            # ── Stage 3: REMEDIATION ───────────────────────────────────
            with agent_span("remediation", "generate_patch", {
                "diagnosis.id": diagnosis.id,
                "anomaly.type": anomaly.anomaly_type,
                "service_name": anomaly.service_name,
            }) as rem_span:
                patch: Patch = await self.remediation_agent.generate_patch(diagnosis)
                rem_span.set_attribute("patch.type", patch.patch_type)
                rem_span.set_attribute("patch.code_files", len(patch.code_changes))
                rem_span.set_attribute("patch.config_items", len(patch.config_changes))
                logger.info("pipeline_patch_generated",
                            patch_id=patch.id,
                            patch_type=patch.patch_type,
                            correlation_id=cid)

            # ── Stage 4: VALIDATION ────────────────────────────────────
            with agent_span("validation", "validate", {
                "patch.id": patch.id,
                "patch.type": patch.patch_type,
                "service_name": anomaly.service_name,
                "anomaly_type": anomaly.anomaly_type,
            }) as val_span:
                validation_start = time.time()
                validation: ValidationResult = await self.validation_agent.validate(patch)
                validation_latency_ms = (time.time() - validation_start) * 1000
                val_span.set_attribute("validation.risk_score", validation.risk_score)
                val_span.set_attribute("validation.risk_level", validation.risk_level.value)
                val_span.set_attribute("validation.static_passed", validation.static_analysis_passed)
                val_span.set_attribute("validation.sandbox_passed", validation.sandbox_execution_passed)
                val_span.set_attribute("validation.auto_deploy", validation.is_safe_for_auto_deploy)
                val_span.set_attribute("validation.issues_count", len(validation.issues))
                val_span.set_attribute("validation.latency_ms", round(validation_latency_ms, 2))

                if not validation.is_safe_for_auto_deploy:
                    failure_reason = "risk_threshold"
                    if not validation.sandbox_execution_passed:
                        failure_reason = "sandbox"
                    elif not validation.policy_check_passed:
                        failure_reason = "policy"
                    elif not validation.static_analysis_passed:
                        failure_reason = "static_analysis"
                    VALIDATION_FAILURES_TOTAL.labels(reason=failure_reason).inc()

                logger.info("pipeline_validation_complete",
                            validation_id=validation.id,
                            risk_score=validation.risk_score,
                            risk_level=validation.risk_level.value,
                            auto_deploy=validation.is_safe_for_auto_deploy,
                            correlation_id=cid)

            # ── Stage 5: DEPLOYMENT ────────────────────────────────────
            # Check if approval is required before deploying
            if not validation.is_safe_for_auto_deploy:
                with agent_span("deployment", "awaiting_approval", {
                    "validation.id": validation.id,
                    "target_service": anomaly.service_name,
                    "risk_level": validation.risk_level.value,
                    "patch_type": patch.patch_type,
                    "anomaly_type": anomaly.anomaly_type,
                }) as dep_span:
                    dep_span.set_attribute("deployment.status", "awaiting_approval")
                    dep_span.set_attribute("deployment.approval_required", True)
                    logger.info("pipeline_awaiting_approval",
                                correlation_id=cid,
                                service=anomaly.service_name,
                                risk_score=validation.risk_score)

                    # Store approval context for later resumption
                    approval_context = {
                        "anomaly": anomaly,
                        "patch": patch,
                        "validation": validation,
                        "cid": cid,
                        "safe_scenario": safe_scenario,
                        "pipeline_start": pipeline_start,
                        "root_span": root_span,
                        "service_lock": service_lock,
                    }

                    async with self._jobs_lock:
                        if cid in self._jobs:
                            job = self._jobs[cid]
                            job.awaiting_approval = True
                            job.remediation_status = RemediationStatus.AWAITING_APPROVAL.value
                            job.set_approval_context(approval_context)

                    await self._set_pipeline_outcome(
                        cid,
                        remediation_status=RemediationStatus.AWAITING_APPROVAL.value,
                        failure_stage=None,
                        failure_reason=None,
                    )

                    # Create a pending deployment record
                    deployment = DeploymentRecord(
                        patch_id=patch.id,
                        validation_id=validation.id,
                        target_service=anomaly.service_name,
                        status="pending",
                        remediation_status=RemediationStatus.AWAITING_APPROVAL,
                        failure_stage=None,
                        failure_reason=None,
                        health_check_passed=False,
                    )
            else:
                with agent_span("deployment", "deploy", {
                    "validation.id": validation.id,
                    "target_service": anomaly.service_name,
                    "risk_level": validation.risk_level.value,
                    "patch_type": patch.patch_type,
                    "anomaly_type": anomaly.anomaly_type,
                }) as dep_span:
                    guardrail_reason = self._deployment_guardrail_reason(
                        validation,
                        service_locked=service_lock.locked(),
                    )

                    if guardrail_reason:
                        DEPLOYMENT_GUARDRAIL_BLOCKS_TOTAL.labels(reason=guardrail_reason).inc()
                        dep_span.set_attribute("deployment.blocked", True)
                        dep_span.set_attribute("deployment.block_reason", guardrail_reason)
                        logger.error(
                            "deployment_guardrail_blocked",
                            correlation_id=cid,
                            service=anomaly.service_name,
                            reason=guardrail_reason,
                        )
                        deployment = DeploymentRecord(
                            patch_id=patch.id,
                            validation_id=validation.id,
                            target_service=anomaly.service_name,
                            status="blocked",
                            remediation_status=RemediationStatus.VALIDATION_FAILED,
                            failure_stage=FailureStage.DEPLOYMENT,
                            failure_reason=guardrail_reason,
                            health_check_passed=False,
                        )
                    else:
                        deployment = await self.deployment_agent.deploy(
                            validation=validation,
                            patch_data={
                                "code_changes": patch.code_changes,
                                "config_changes": patch.config_changes,
                            },
                            target_service=anomaly.service_name,
                        )

                    if deployment:
                        dep_span.set_attribute("deployment.status", deployment.status)
                        dep_span.set_attribute("deployment.strategy", deployment.deployment_strategy)
                        dep_span.set_attribute("deployment.health_passed", deployment.health_check_passed)
                        dep_span.set_attribute("deployment.rollback", deployment.rollback_triggered)
                        async with self._metrics_lock:
                            self._metrics.total_fixes_deployed += 1
                            if deployment.rollback_triggered:
                                self._metrics.total_rollbacks += 1
                    logger.info("pipeline_deployment_complete",
                                status=deployment.status if deployment else "skipped",
                                correlation_id=cid)

            # ── Stage 6: VERIFICATION ─────────────────────────────────
            with agent_span("verification", "post_deploy_checks", {
                "target_service": anomaly.service_name,
                "patch_type": patch.patch_type,
                "anomaly_type": anomaly.anomaly_type,
            }) as ver_span:
                verification_passed = bool(
                    deployment
                    and deployment.status == "deployed"
                    and deployment.health_check_passed
                )
                verification_reason = "ok" if verification_passed else (
                    deployment.failure_reason if deployment else "deployment_unavailable"
                )
                ver_span.set_attribute("verification.passed", verification_passed)
                ver_span.set_attribute("verification.reason", verification_reason or "none")
                logger.info(
                    "pipeline_verification_complete",
                    correlation_id=cid,
                    passed=verification_passed,
                    reason=verification_reason,
                )

            # ── Stage 7: RECORD + METRICS ──────────────────────────────
            pipeline_duration = time.time() - pipeline_start

            was_successful = (
                deployment is not None
                and deployment.status == "deployed"
                and deployment.health_check_passed
            )

            remediation_status = self._derive_remediation_status(validation, deployment)
            failure_stage, failure_reason = self._derive_failure_details(
                remediation_status,
                validation,
                deployment,
            )

            record = RemediationRecord(
                anomaly=anomaly,
                diagnosis=diagnosis,
                patch=patch,
                validation=validation,
                deployment=deployment or DeploymentRecord(
                    patch_id=patch.id,
                    validation_id=validation.id,
                    target_service=anomaly.service_name,
                    status="skipped",
                ),
                remediation_status=remediation_status,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
                total_duration_seconds=pipeline_duration,
                was_successful=was_successful,
                manual_intervention_required=not validation.is_safe_for_auto_deploy,
            )

            record.deployment.remediation_status = remediation_status
            record.deployment.failure_stage = failure_stage
            record.deployment.failure_reason = failure_reason

            async with self._history_lock:
                self._append_history(record)

            # ── Stage 8: LEARNING ──────────────────────────────────────
            if record.was_successful and self._knowledge_engine:
                with tracer.start_as_current_span("pipeline.learning_store",
                    attributes={"anomaly.type": anomaly.anomaly_type,
                                "service": anomaly.service_name}):
                    await self._store_to_knowledge_base(record)
                    LEARNING_STORES_TOTAL.labels(category="remediation_history").inc()

            # ── Prometheus Metrics ─────────────────────────────────────
            status_label = remediation_status.value

            await self._record_dedup_outcome(was_deduplicated=False)

            PIPELINE_RUNS_TOTAL.labels(
                scenario=safe_scenario, status=status_label
            ).inc()
            PIPELINE_DURATION_SECONDS.labels(
                scenario=safe_scenario
            ).observe(pipeline_duration)
            REMEDIATIONS_TOTAL.labels(
                patch_type=patch.patch_type, status=status_label
            ).inc()
            MTTD_SECONDS.labels(
                anomaly_type=anomaly.anomaly_type
            ).observe(record.mttd_seconds)
            if was_successful:
                MTTR_SECONDS.labels(
                    anomaly_type=anomaly.anomaly_type
                ).observe(record.mttr_seconds)
            DIAGNOSIS_CONFIDENCE.labels(
                root_cause_category=diagnosis.root_cause_category
            ).observe(diagnosis.confidence)
            RISK_SCORE_DISTRIBUTION.labels(
                patch_type=patch.patch_type
            ).observe(validation.risk_score)

            async with self._metrics_lock:
                self._update_metrics_incremental(record)

            # Annotate root span
            root_span.set_attribute("pipeline.successful", was_successful)
            root_span.set_attribute("pipeline.remediation_status", remediation_status.value)
            root_span.set_attribute("service_name", anomaly.service_name)
            root_span.set_attribute("anomaly_type", anomaly.anomaly_type)
            root_span.set_attribute("patch_type", patch.patch_type)
            root_span.set_attribute("risk_score", validation.risk_score)
            root_span.set_attribute("validation_latency", round(validation_latency_ms, 2))
            root_span.set_attribute("pipeline.mttd_ms",
                                    round(record.mttd_seconds * 1000, 2))
            root_span.set_attribute("pipeline.mttr_s",
                                    round(record.mttr_seconds, 3))

            logger.info("pipeline_complete",
                        correlation_id=cid,
                        duration_seconds=round(pipeline_duration, 3),
                        remediation_status=remediation_status.value,
                        failure_stage=failure_stage.value if failure_stage else None,
                        failure_reason=failure_reason,
                        successful=was_successful,
                        mttd_ms=round(record.mttd_seconds * 1000, 1),
                        mttr_s=round(record.mttr_seconds, 2))

            await self._set_pipeline_outcome(
                cid,
                remediation_status=remediation_status.value,
                failure_stage=failure_stage.value if failure_stage else None,
                failure_reason=failure_reason,
            )

            return record

    # ─────────────────────────────────────────────────────────────
    # Background Job API
    # ─────────────────────────────────────────────────────────────

    async def create_job(self, scenario: str) -> PipelineJob:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = PipelineJob(job_id=job_id, scenario=scenario)
        async with self._jobs_lock:
            self._jobs[job_id] = job
            # Bounded eviction: keep at most 1000 jobs
            if len(self._jobs) > 1000:
                old = [
                    jid for jid, j in self._jobs.items()
                    if j.status in ("completed", "failed")
                ]
                for jid in old[:100]:
                    del self._jobs[jid]
        return job

    async def run_job(self, job: PipelineJob, metrics: List[ServiceMetric]) -> None:
        """Execute a pipeline job. Called from FastAPI BackgroundTasks."""
        job.status = "running"
        job.started_at = time.time()

        try:
            record = await self.run_full_pipeline(
                metrics=metrics,
                correlation_id=job.job_id,
                scenario=job.scenario,
            )
            job.record = record
            job.status = "completed"
            if record:
                job.anomaly_type = record.anomaly.anomaly_type
                job.patch_type = record.patch.patch_type
                job.deployed = record.was_successful
                job.remediation_status = record.remediation_status.value
                job.failure_stage = record.failure_stage.value if record.failure_stage else None
                job.failure_reason = record.failure_reason
            else:
                outcome = self._pipeline_outcomes.get(job.job_id, {})
                job.remediation_status = outcome.get("remediation_status")
                job.failure_stage = outcome.get("failure_stage")
                job.failure_reason = outcome.get("failure_reason")
        except Exception as e:
            job.error = str(e)
            job.status = "failed"
            logger.error("job_failed", job_id=job.job_id, error=str(e))
        finally:
            job.finished_at = time.time()

    async def get_job(self, job_id: str) -> Optional[PipelineJob]:
        async with self._jobs_lock:
            return self._jobs.get(job_id)

    async def list_jobs(self, limit: int = 50) -> List[PipelineJob]:
        async with self._jobs_lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.started_at or 0, reverse=True)
        return jobs[:limit]

    # ─────────────────────────────────────────────────────────────
    # Learning System
    # ─────────────────────────────────────────────────────────────

    async def _store_to_knowledge_base(self, record: RemediationRecord) -> None:
        try:
            await self._knowledge_engine.store_remediation({
                "anomaly_type": record.anomaly.anomaly_type,
                "service_name": record.anomaly.service_name,
                "root_cause": record.diagnosis.root_cause,
                "root_cause_category": record.diagnosis.root_cause_category,
                "fix_description": record.patch.description,
                "patch_type": record.patch.patch_type,
                "confidence": record.diagnosis.confidence,
                "was_successful": record.was_successful,
                "duration_seconds": record.total_duration_seconds,
                "risk_score": record.validation.risk_score,
                "recommended_actions": record.diagnosis.recommended_actions,
            })
            logger.info("learning_stored",
                        anomaly_type=record.anomaly.anomaly_type,
                        service=record.anomaly.service_name)
        except Exception as e:
            logger.warning("learning_store_failed", error=str(e))

    # ─────────────────────────────────────────────────────────────
    # Metrics — O(1) incremental updates (NO list scans)
    # ─────────────────────────────────────────────────────────────

    def _append_history(self, record: RemediationRecord) -> None:
        """MUST be called inside self._history_lock."""
        self._remediation_history.append(record)
        if len(self._remediation_history) > self.MAX_HISTORY_SIZE:
            self._remediation_history = self._remediation_history[-self.MAX_HISTORY_SIZE:]

    def _update_metrics_incremental(self, record: RemediationRecord) -> None:
        """MUST be called inside self._metrics_lock."""
        n = len(self._remediation_history)
        if n == 0:
            return

        self._total_pipeline_latency_ms += (record.total_duration_seconds * 1000.0)
        self._total_sandbox_duration_seconds += record.validation.duration_seconds

        self._metrics.avg_pipeline_latency_ms = self._total_pipeline_latency_ms / n
        self._metrics.avg_sandbox_duration_seconds = self._total_sandbox_duration_seconds / n

        if record.was_successful:
            self._success_count += 1

        self._metrics.autonomous_resolution_rate = self._success_count / n

        # Throughput (EPS) calculation — based on events processed
        # Assuming each remediation record represents roughly 6 key state transitions (events)
        total_events = n * 6
        self._metrics.events_processed = total_events
        
        # Simple EPS: total events over time since first record
        if n > 1:
            uptime = (datetime.now(timezone.utc) - self._remediation_history[0].completed_at).total_seconds()
            if uptime > 0:
                self._metrics.events_per_second = total_events / uptime

        # Prometheus gauges
        AUTONOMOUS_RESOLUTION_RATE.set(self._metrics.autonomous_resolution_rate)

        self._metrics.knowledge_base_entries = (
            self._knowledge_engine.document_count if self._knowledge_engine else n
        )
        self._metrics.active_agents = 5
        self._metrics.timestamp = datetime.now(timezone.utc)

    def get_metrics(self) -> PlatformMetrics:
        self._metrics.events_processed = len(self._remediation_history) * 6
        return self._metrics

    def get_remediation_history(self) -> List[RemediationRecord]:
        return self._remediation_history.copy()

    def get_recent_remediations(self, limit: int = 10) -> List[RemediationRecord]:
        return self._remediation_history[-limit:]
