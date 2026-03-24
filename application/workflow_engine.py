import asyncio
import uuid
import time
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
        fingerprint = f"scenario:{scenario}" # Simplified for now
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
        """Background pipeline execution logic."""
        job = await self.job_store.get_job(job_id)
        if not job: return

        try:
            async with pipeline_span(job_id, scenario=job.scenario):
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc)
                await self.job_store.update_state(job)

                # Coordination handover
                # In a real refactor, we would call the coordinator's stages here
                # result = await self.coordinator.run_detection(metrics)
                # ... etc ...
                
                await asyncio.sleep(2) # Simulating work
                
                job.status = JobStatus.COMPLETED
                job.finished_at = datetime.now(timezone.utc)
                await self.job_store.update_state(job)
                
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            await self.job_store.update_state(job)
        finally:
            await self.lock_manager.release(job.scenario)
            await self.fingerprint_store.release_fingerprint(fingerprint)

    async def shutdown(self) -> None:
        logger.info("workflow_engine_shutdown")
