from typing import Any, Optional, Dict, List

from domain.job import Job
from domain.anomaly import Anomaly
from core.models import Diagnosis, Patch, ValidationResult, DeploymentRecord
from core.logging_config import get_logger

logger = get_logger(__name__)

class AgentCoordinator:
    """Manages execution progression through the agent stages."""

    def __init__(self, *args, **kwargs):
        self.knowledge_engine = kwargs.get('knowledge_engine', None)
        self.sandbox_executor = kwargs.get('sandbox_executor', None)

    async def run_detection(self, metrics: Any, scenario: str) -> dict:
        from agents.detection_agent import DetectionAgent
        from listener.real_metrics import generate_scenario_metrics
        from core.models import ServiceMetric

        agent = DetectionAgent()
        await agent.initialize()

        if metrics:
            service_metrics = metrics
        else:
            raw = generate_scenario_metrics(scenario)
            service_metrics = [ServiceMetric(**m) if isinstance(m, dict) else m for m in raw]

        anomaly = await agent.analyze_metrics(service_metrics)
        return {"anomaly": anomaly}

    async def run_diagnosis(self, anomaly, job_id: str) -> dict:
        from agents.diagnosis_agent import DiagnosisAgent
        agent = DiagnosisAgent(
            knowledge_engine=self.knowledge_engine,
        )
        await agent.initialize()
        diagnosis = await agent.diagnose(anomaly)
        return {"diagnosis": diagnosis}

    async def run_remediation(self, diagnosis, job_id: str) -> dict:
        from agents.remediation_agent import RemediationAgent
        agent = RemediationAgent(
            knowledge_engine=self.knowledge_engine,
            sandbox_executor=self.sandbox_executor,
        )
        await agent.initialize()
        patch = await agent.remediate(diagnosis)
        return {"patch": patch}

    async def run_validation(self, patch, job_id: str) -> dict:
        from agents.validation_agent import ValidationAgent
        agent = ValidationAgent(
            sandbox_executor=self.sandbox_executor,
        )
        await agent.initialize()
        result = await agent.validate(patch)
        return {"result": result}

    async def run_deployment(self, patch, validation_result, job_id: str) -> dict:
        from agents.deployment_agent import DeploymentAgent
        agent = DeploymentAgent()
        await agent.initialize()
        record = await agent.deploy(patch, validation_result)
        return {"record": record, "success": record is not None}
