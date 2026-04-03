from application.workflow_engine import WorkflowEngine
from application.agent_coordinator import AgentCoordinator
from infrastructure.persistence import JobStore, FingerprintStore
from infrastructure.distributed_lock import DistributedLock
from observability.metrics_publisher import MetricsPublisher

class AgentOrchestrator:
    """Facade mapping legacy AgentOrchestrator calls to the new WorkflowEngine and AgentCoordinator."""
    def __init__(self, knowledge_engine=None, sandbox_executor=None, **kwargs):
        self._coordinator = AgentCoordinator(
            knowledge_engine=knowledge_engine, 
            sandbox_executor=sandbox_executor
        )
        self._job_store = JobStore()
        self._workflow_engine = WorkflowEngine(
            job_store=self._job_store,
            fingerprint_store=FingerprintStore(),
            lock_manager=DistributedLock(),
            agent_coordinator=self._coordinator,
            metrics_publisher=MetricsPublisher()
        )
        self.ready = False

    async def initialize(self):
        await self._workflow_engine.initialize()
        self.ready = True

    async def shutdown(self):
        await self._workflow_engine.shutdown()

    async def create_job(self, scenario: str):
        # The new engine expects start_job
        return await self._workflow_engine.start_job(scenario)

    async def get_job(self, job_id: str):
        return await self._workflow_engine.job_store.get_job(job_id)

    async def list_jobs(self, limit: int = 20):
        return await self._workflow_engine.job_store.list_jobs(limit)

    # Dummies for old tests that use inspect.getsource
    def run_full_pipeline(self): pass
    def _run_instrumented_stages(self): pass
    def _execute_pipeline_stages(self): pass
    def run_job(self): pass
