import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from interfaces.api.dependencies import require_api_key, get_orchestrator
from core.logging_config import get_logger

logger = get_logger("aethelgard.api.pipeline_routes")
router = APIRouter(prefix="/pipeline", tags=["Pipeline"])

class PipelineJobResponse(BaseModel):
    job_id: str
    status: str = "pending"
    scenario: str
    message: str = "Pipeline job accepted. Poll /pipeline/jobs/{job_id} for status."
    poll_url: str

class PipelineJobStatus(BaseModel):
    job_id: str
    status: str
    scenario: str
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    anomaly_detected: Optional[bool] = None
    service: Optional[str] = None
    anomaly_type: Optional[str] = None
    root_cause: Optional[str] = None
    patch_type: Optional[str] = None
    remediation_status: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None
    risk_score: Optional[float] = None
    deployed: Optional[bool] = None
    mttd_seconds: Optional[float] = None
    mttr_seconds: Optional[float] = None

@router.post(
    "/run",
    response_model=PipelineJobResponse,
    status_code=202,
)
async def run_pipeline(
    background_tasks: BackgroundTasks,
    scenario: str = Query("payment_latency_spike"),
    _api_key: str = Depends(require_api_key),
    orchestrator=Depends(get_orchestrator),
):
    try:
        from experiments.scenario_runner import DEMO_SCENARIOS
        if scenario not in DEMO_SCENARIOS:
            raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario}")

        # Start job through workflow engine facade
        job = await orchestrator.start_job(scenario=scenario)
        logger.info("pipeline_job_accepted", job_id=job.id, scenario=scenario)

        return PipelineJobResponse(
            job_id=job.id,
            status="pending",
            scenario=scenario,
            poll_url=f"/api/v1/pipeline/jobs/{job.id}",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("pipeline_run_failed", error=str(exc), scenario=scenario)
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})

@router.get("/jobs/{job_id}", response_model=PipelineJobStatus)
async def get_pipeline_job(
    job_id: str,
    _api_key: str = Depends(require_api_key),
    orchestrator=Depends(get_orchestrator),
):
    try:
        job = await orchestrator.job_store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        
        response = PipelineJobStatus(
            job_id=job.id,
            status=job.status.value,
            scenario=job.scenario,
            duration_seconds=job.duration_seconds,
            error=job.error,
            remediation_status=job.remediation_status,
            failure_stage=job.failure_stage,
            failure_reason=job.failure_reason,
        )
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("pipeline_job_status_failed", job_id=job_id, error=str(exc))
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})
