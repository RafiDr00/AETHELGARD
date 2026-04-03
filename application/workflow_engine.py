
import asyncio
import uuid
import time
from datetime import datetime, timezone
from typing import List, Optional, Any

from domain.job import Job, JobStatus
from domain.state_machine import require_valid_transition
from infrastructure.persistence import JobStore, FingerprintStore
from infrastructure.distributed_lock import DistributedLock
from application.agent_coordinator import AgentCoordinator
from observability.metrics_publisher import MetricsPublisher
from observability.tracing import pipeline_span
from core.logging_config import get_logger

logger = get_logger("aethelgard.application.workflow_engine")

class WorkflowEngine:
    """The central brain orchestrating the remediation lifecycle."""
    
    def __init__(
        self,
        job_store: JobStore,
        fingerprint_store: FingerprintStore,
        lock_manager: DistributedLock,
        agent_coordinator: AgentCoordinator,
        metrics_publisher: MetricsPublisher,
    ):
        self.job_store = job_store
        self.fingerprint_store = fingerprint_store
        self.lock_manager = lock_manager
        self.coordinator = agent_coordinator
        self.publisher = metrics_publisher
        self.ready = False

    async def initialize(self) -> None:
        """Initialize components and restore state if needed."""
        # In a real system, we might restore internal counters here
        self.ready = True
        logger.info("workflow_engine_ready")

    async def start_job(self, scenario: str, metrics: List[Any] = None) -> Job:
        """Start a new remediation job."""
        job = await self.job_store.create_job(scenario)
        
        # Guard: Deduplication
        import time
        fingerprint = f"scenario:{scenario}:{int(time.time() // 30)}"
        if not await self.fingerprint_store.claim_fingerprint(fingerprint):
            job.status = JobStatus.FAILED
            job.error = "duplicate_remediation_suppressed"
            job.failure_stage = "deduplication"
            await self.job_store.update_state(job)
            return job

        # Guard: Distributed Lock
        if not await self.lock_manager.acquire(scenario): # Per-scenario lock
             job.status = JobStatus.FAILED
             job.error = "resource_lock_busy"
             await self.job_store.update_state(job)
             await self.fingerprint_store.release_fingerprint(fingerprint)
             return job

        # Trigger background execution
        asyncio.create_task(self._execute_pipeline(job.id, metrics, fingerprint))
        return job


    async def _execute_pipeline(self, job_id: str, metrics: Any, fingerprint: str) -> None:
        job = await self.job_store.get_job(job_id)
        if not job:
            return

        try:
            async with pipeline_span(job_id, scenario=job.scenario):
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc)
                await self.job_store.update_state(job)
                await self.publisher.publish_stage("detection", "running", job_id)

                # Stage 1: Detection
                detection_result = await self.coordinator.run_detection(metrics, job.scenario)
                if not detection_result or not detection_result.get("anomaly"):
                    job.status = JobStatus.COMPLETED
                    job.result = {"message": "No anomaly detected. System healthy."}
                    job.finished_at = datetime.now(timezone.utc)
                    await self.job_store.update_state(job)
                    await self.publisher.publish_stage("detection", "healthy", job_id)
                    return

                await self.publisher.publish_stage("detection", "complete", job_id)
                await self.publisher.publish_stage("diagnosis", "running", job_id)

                # Stage 2: Diagnosis
                anomaly = detection_result["anomaly"]
                diagnosis_result = await self.coordinator.run_diagnosis(anomaly, job_id)
                if not diagnosis_result:
                    raise RuntimeError("Diagnosis agent returned no result")

                await self.publisher.publish_stage("diagnosis", "complete", job_id)
                await self.publisher.publish_stage("remediation", "running", job_id)

                # Stage 3: Remediation
                diagnosis = diagnosis_result["diagnosis"]
                remediation_result = await self.coordinator.run_remediation(diagnosis, job_id)
                if not remediation_result:
                    raise RuntimeError("Remediation agent returned no result")

                await self.publisher.publish_stage("remediation", "complete", job_id)
                await self.publisher.publish_stage("validation", "running", job_id)

                # Stage 4: Validation
                patch = remediation_result["patch"]
                validation_result = await self.coordinator.run_validation(patch, job_id)
                if not validation_result:
                    raise RuntimeError("Validation agent returned no result")

                await self.publisher.publish_stage("validation", "complete", job_id)
                await self.publisher.publish_stage("deployment", "running", job_id)

                # Stage 5: Deployment
                deploy_result = await self.coordinator.run_deployment(patch, validation_result["result"], job_id)

                await self.publisher.publish_stage("deployment", "complete", job_id)

                job.status = JobStatus.COMPLETED
                job.finished_at = datetime.now(timezone.utc)
                job.result = {
                    "anomaly_type": anomaly.anomaly_type if hasattr(anomaly, "anomaly_type") else str(anomaly),
                    "root_cause": diagnosis.root_cause if hasattr(diagnosis, "root_cause") else str(diagnosis),
                    "patch_type": patch.patch_type if hasattr(patch, "patch_type") else str(patch),
                    "deployed": deploy_result.get("success", False),
                }
                await self.job_store.update_state(job)

        except Exception as e:
            logger.error("pipeline_execution_failed", job_id=job_id, error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.finished_at = datetime.now(timezone.utc)
            await self.job_store.update_state(job)
        finally:
            await self.lock_manager.release(job.scenario)
            await self.fingerprint_store.release_fingerprint(fingerprint)

    async def shutdown(self) -> None:
        logger.info("workflow_engine_shutdown")
