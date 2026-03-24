from prometheus_client import Counter, Histogram, Gauge, REGISTRY

_REG = REGISTRY

PIPELINE_RUNS_TOTAL = Counter("aethelgard_pipeline_runs_total", "Total pipeline executions", ["scenario", "status"], registry=_REG)
ANOMALIES_DETECTED_TOTAL = Counter("aethelgard_anomalies_detected_total", "Detected anomalies", ["anomaly_type", "severity", "service"], registry=_REG)
REMEDIATIONS_TOTAL = Counter("aethelgard_remediations_total", "Total remediation attempts", ["patch_type", "status"], registry=_REG)
SANDBOX_VALIDATIONS_TOTAL = Counter("aethelgard_sandbox_validations_total", "Sandbox outcomes", ["result", "reason"], registry=_REG)
VALIDATION_FAILURES_TOTAL = Counter("aethelgard_validation_failures_total", "Validation failures", ["reason"], registry=_REG)
POLICY_VIOLATIONS_TOTAL = Counter("aethelgard_policy_violations_total", "Security violations", ["violation_type", "severity"], registry=_REG)
LEARNING_STORES_TOTAL = Counter("aethelgard_learning_stores_total", "Docs in KB", ["category"], registry=_REG)
API_AUTH_FAILURES_TOTAL = Counter("aethelgard_api_auth_failures_total", "API auth fails", ["endpoint"], registry=_REG)
DEPLOYMENT_GUARDRAIL_BLOCKS_TOTAL = Counter("aethelgard_deployment_guardrail_blocks_total", "Deploy blocks", ["reason"], registry=_REG)
REACT_TIMEOUTS_TOTAL = Counter("aethelgard_react_timeouts_total", "ReAct timeouts", ["agent_type"], registry=_REG)

PIPELINE_DURATION_SECONDS = Histogram("aethelgard_pipeline_duration_seconds", "Pipeline duration", ["scenario"], registry=_REG)
AGENT_STAGE_DURATION_SECONDS = Histogram("aethelgard_agent_stage_duration_seconds", "Agent stage duration", ["agent_type"], registry=_REG)
AGENT_LATENCY_SECONDS = Histogram("aethelgard_agent_latency_seconds", "Agent latency", ["agent_type"], registry=_REG)
MTTD_SECONDS = Histogram("aethelgard_mttd_seconds", "MTTD", ["anomaly_type"], registry=_REG)
MTTR_SECONDS = Histogram("aethelgard_mttr_seconds", "MTTR", ["anomaly_type"], registry=_REG)
DIAGNOSIS_CONFIDENCE = Histogram("aethelgard_diagnosis_confidence", "Diagnosis confidence", ["root_cause_category"], registry=_REG)
RISK_SCORE_DISTRIBUTION = Histogram("aethelgard_validation_risk_score", "Risk scores", ["patch_type"], registry=_REG)
SANDBOX_DURATION_SECONDS = Histogram("aethelgard_sandbox_duration_seconds", "Sandbox time", ["mode"], registry=_REG)
RAG_QUERY_DURATION_SECONDS = Histogram("aethelgard_rag_query_duration_seconds", "RAG query time", ["backend"], registry=_REG)
REACT_ITERATIONS = Histogram("aethelgard_react_iterations_total", "ReAct loop iterations", ["agent_type", "outcome"], registry=_REG)

ACTIVE_PIPELINE_JOBS = Gauge("aethelgard_active_pipeline_jobs", "Active pipelines", registry=_REG)
KNOWLEDGE_BASE_DOCUMENTS = Gauge("aethelgard_knowledge_base_documents", "KB docs", ["category"], registry=_REG)
AUTONOMOUS_RESOLUTION_RATE = Gauge("aethelgard_autonomous_resolution_rate", "Resolution rate", registry=_REG)
ENGINEERING_HOURS_SAVED = Gauge("aethelgard_engineering_hours_saved_total", "Hours saved", registry=_REG)
ROI_DOLLARS = Gauge("aethelgard_roi_dollars_total", "ROI USD", registry=_REG)
DEDUP_SUPPRESSION_RATIO = Gauge("aethelgard_dedup_suppression_ratio", "Dedup ratio", registry=_REG)

def record_pipeline_run(record, scenario="unknown"):
    anomaly = record.anomaly
    status = record.remediation_status.value
    PIPELINE_RUNS_TOTAL.labels(scenario=scenario, status=status).inc()
    ANOMALIES_DETECTED_TOTAL.labels(anomaly_type=anomaly.anomaly_type, severity=anomaly.severity.value, service=anomaly.service_name).inc()
    REMEDIATIONS_TOTAL.labels(patch_type=record.patch.patch_type, status=status).inc()
    PIPELINE_DURATION_SECONDS.labels(scenario=scenario).observe(record.total_duration_seconds)
    MTTD_SECONDS.labels(anomaly_type=anomaly.anomaly_type).observe(record.mttd_seconds)

def record_sandbox_result(passed, reason, duration, mode="subprocess", violations=None):
    result = "passed" if passed else "failed"
    SANDBOX_VALIDATIONS_TOTAL.labels(result=result, reason=reason or "none").inc()
    SANDBOX_DURATION_SECONDS.labels(mode=mode).observe(duration)

def record_react_iteration(agent_type, iterations, outcome="decided"):
    REACT_ITERATIONS.labels(agent_type=agent_type, outcome=outcome).observe(iterations)
    if outcome == "timeout":
        REACT_TIMEOUTS_TOTAL.labels(agent_type=agent_type).inc()

def record_dedup_suppression_ratio(deduplicated, total):
    if total <= 0:
        DEDUP_SUPPRESSION_RATIO.set(0.0)
    else:
        DEDUP_SUPPRESSION_RATIO.set(deduplicated / total)
