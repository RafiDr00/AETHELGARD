# Aethelgard — Observability Debug Runbook
## How to Diagnose a Failed Remediation Run

This runbook explains how to trace a failed remediation from first alert to root
cause using the telemetry stack (Jaeger traces + Prometheus/Grafana metrics).

---

## 1. Stack Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Aethelgard                                                        │
│                                                                       │
│  FastAPI  ──► OpenTelemetry SDK ──► OTLP ──► Jaeger (traces)         │
│     │                                                                 │
│     └──────────────────────────────────► Prometheus (/metrics/prom)  │
│                                                  │                   │
│                                             Grafana (dashboards)     │
│                                                  │                   │
│                                          PagerDuty / Alertmanager    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architecture Diagram (Observability Layer)

```
┌─────────────────────────────────────────────────────────────────────┐
│  REQUEST: POST /pipeline/run                                         │
│  ────────────────────────────────────────────────────────────────── │
│                                                                      │
│  [FastAPI HTTP Span]──────────────────────────────────────────────┐ │
│    trace_id: abc123def456                                          │ │
│    span_id:  0011223344556677                                      │ │
│    ├── [agent.detection.analyze_metrics]                           │ │
│    │     anomaly.detected = true                                   │ │
│    │     anomaly.type     = latency_spike                          │ │
│    │     anomaly.service  = payment-api                            │ │
│    │     duration_ms      = 2.1                                    │ │
│    │                                                               │ │
│    ├── [agent.diagnosis.diagnose]                                  │ │
│    │     diagnosis.confidence     = 0.82                           │ │
│    │     diagnosis.root_cause     = worker_pool_exhaustion         │ │
│    │     diagnosis.knowledge_refs = 3                              │ │
│    │     duration_ms              = 45.2                           │ │
│    │                                                               │ │
│    ├── [agent.remediation.generate_patch]                          │ │
│    │     patch.type        = config_change                         │ │
│    │     patch.code_files  = 1                                     │ │
│    │     duration_ms       = 12.8                                  │ │
│    │                                                               │ │
│    ├── [agent.validation.validate]                                 │ │
│    │     validation.risk_score    = 0.18                           │ │
│    │     validation.static_passed = true                           │ │
│    │     validation.sandbox_passed= false  ◄── FAILED HERE        │ │
│    │     validation.issues_count  = 1                              │ │
│    │     duration_ms              = 387.4                          │ │
│    │                                                               │ │
│    ├── [agent.deployment.deploy]                                   │ │
│    │     deployment.status        = manual_approval                │ │
│    │     deployment.health_passed = true                           │ │
│    │                                                               │ │
│    └── [pipeline.learning_store]                                   │ │
│          category = remediation_history                            │ │
│  ─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Complete Metrics Reference

### Counters

| Metric | Labels | Description |
|--------|--------|-------------|
| `aethelgard_pipeline_runs_total` | `scenario`, `status` | Every pipeline execution |
| `aethelgard_anomalies_detected_total` | `anomaly_type`, `severity`, `service` | Detection events |
| `aethelgard_remediations_total` | `patch_type`, `status` | Remediation outcomes |
| `aethelgard_sandbox_validations_total` | `result`, `reason` | Sandbox pass/fail/block/timeout |
| `aethelgard_policy_violations_total` | `violation_type`, `severity` | AST security catches |
| `aethelgard_learning_stores_total` | `category` | Knowledge base writes |
| `aethelgard_api_auth_failures_total` | `endpoint` | Unauthenticated requests |

### Histograms

| Metric | Labels | Buckets | Description |
|--------|--------|---------|-------------|
| `aethelgard_pipeline_duration_seconds` | `scenario` | 0.05→60s | Full pipeline latency |
| `aethelgard_agent_stage_duration_seconds` | `agent_type` | 0.001→5s | Per-agent execution time |
| `aethelgard_mttd_seconds` | `anomaly_type` | 0.001→30s | Time to detect |
| `aethelgard_mttr_seconds` | `anomaly_type` | 0.1→300s | Time to repair |
| `aethelgard_diagnosis_confidence` | `root_cause_category` | 0.1→1.0 | Confidence distribution |
| `aethelgard_validation_risk_score` | `patch_type` | 0.05→1.0 | Risk score distribution |
| `aethelgard_sandbox_duration_seconds` | `mode` | 0.01→30s | Sandbox execution time |
| `aethelgard_rag_query_duration_seconds` | `backend` | 0.001→1s | RAG query latency |

### Gauges

| Metric | Labels | Description |
|--------|--------|-------------|
| `aethelgard_active_pipeline_jobs` | — | Currently running jobs |
| `aethelgard_dedup_suppression_ratio` | — | Deduplicated triggers / total triggers |
| `aethelgard_knowledge_base_documents` | `category` | Documents per category |
| `aethelgard_autonomous_resolution_rate` | — | 0.0–1.0 autonomous rate |
| `aethelgard_engineering_hours_saved_total` | — | Cumulative hours |
| `aethelgard_roi_dollars_total` | — | Cumulative ROI |

### Canonical Remediation Status Labels

All remediation outcome telemetry now uses a strict enum:

- `success`
- `rolled_back`
- `validation_failed`
- `sandbox_failed`
- `deduplicated`

---

## 4. Debugging a Failed Remediation Run

### Step 1 — Check the Grafana Alert

On the **Remediation Outcomes** row:
- `Remediation Success Rate` drops below 90% → open Jaeger

### Step 2 — Find the Trace in Jaeger

```
Jaeger UI: http://localhost:16686
Service: aethelgard-v2
Operation: pipeline.run
Tags: pipeline.successful=false
```

Or filter by correlation_id from the API response:
```
Tags: correlation_id=job-abc12345
```

### Step 3 — Inspect the Span Tree

Look for spans with `ERROR` status (shown in red):

```
pipeline.run                          387ms  ✓
  agent.detection.analyze_metrics       2ms  ✓
  agent.diagnosis.diagnose             45ms  ✓
  agent.remediation.generate_patch     13ms  ✓
  agent.validation.validate           380ms  ✗ ERROR
    └── sandbox: subprocess timed out after 30s
  agent.deployment.deploy               1ms  manual_approval
```

**The span attributes tell you exactly what failed:**
```yaml
validation.risk_score:     0.18
validation.static_passed:  true
validation.policy_passed:  true
validation.sandbox_passed: false    # ← failed here
validation.issues_count:   1
agent.duration_ms:         380.4
```

### Step 4 — Correlate with Logs (trace_id injection)

Every log line emitted inside an active span carries `trace_id` and `span_id`:

```json
{
  "timestamp": "2026-03-07T00:45:00Z",
  "level": "warning",
  "event": "sandbox_execution_complete",
  "trace_id": "abc123def456789012345678901234ab",
  "span_id":  "0011223344556677",
  "correlation_id": "job-abc12345",
  "passed": false,
  "exit_code": -9,
  "reason": "timeout",
  "duration_seconds": 30.002
}
```

Query in Loki / Grafana Explore:
```logql
{service="aethelgard-v2"} | json | trace_id="abc123def456789012345678901234ab"
```

### Step 5 — Query Prometheus for Pattern Analysis

**Are sandbox failures increasing?**
```promql
rate(aethelgard_sandbox_validations_total{result="timeout"}[10m]) * 60
```

**Which anomaly types are failing remediation most?**
```promql
sum(aethelgard_remediations_total{status=~"validation_failed|sandbox_failed|rolled_back"}) by (patch_type)
  /
sum(aethelgard_remediations_total) by (patch_type)
```

**How aggressive is dedup suppression?**
```promql
aethelgard_dedup_suppression_ratio
```

**Is diagnosis confidence degrading (RAG quality drop)?**
```promql
histogram_quantile(0.50, rate(aethelgard_diagnosis_confidence_bucket[30m]))
```
> If this drops below 0.6, the RAG knowledge base may need more playbooks ingested.

**Which agent stage is the latency bottleneck?**
```promql
histogram_quantile(0.90,
  sum by (agent_type, le)(
    rate(aethelgard_agent_stage_duration_seconds_bucket[5m])
  )
)
```

### Step 6 — Reproduce & Test

Use the debug scenario with an intentionally long-running script:
```bash
curl -X POST http://localhost:8000/pipeline/run?scenario=payment_latency_spike \
  -H "X-API-Key: <your-api-key>"

# Poll result
curl http://localhost:8000/pipeline/jobs/<job_id>
```

---

## 5. Prometheus Alert Rules

```yaml
# infra/prometheus/alerts.yaml
groups:
  - name: aethelgard_slo
    interval: 30s
    rules:

      - alert: RemediationSuccessRateLow
        expr: |
          (
            sum(rate(aethelgard_remediations_total{status="deployed"}[10m]))
            /
            sum(rate(aethelgard_remediations_total[10m]))
          ) < 0.85
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Remediation success rate below 85%"
          description: "Only {{ $value | humanizePercentage }} of remediations deploying successfully"
          runbook_url: "https://wiki.internal/aethelgard/runbook#remediation-success-rate"

      - alert: PipelineLatencyHigh
        expr: |
          histogram_quantile(0.90,
            rate(aethelgard_pipeline_duration_seconds_bucket[5m])
          ) > 30
        for: 3m
        labels: { severity: warning }
        annotations:
          summary: "Pipeline p90 latency exceeds 30s"
          description: "p90 pipeline duration is {{ $value }}s — SLO target is <30s"

      - alert: SandboxSecurityViolations
        expr: |
          sum(rate(aethelgard_policy_violations_total{severity="critical"}[5m])) * 60 > 0
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "Critical security violations in generated patches"
          description: "AST analysis is blocking patches with critical violations — investigate LLM output"

      - alert: DiagnosisConfidenceLow
        expr: |
          histogram_quantile(0.50,
            rate(aethelgard_diagnosis_confidence_bucket[30m])
          ) < 0.5
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Diagnosis confidence p50 below 50%"
          description: "RAG knowledge base may need more playbooks — confidence median is {{ $value }}"

      - alert: AuthFailureSpike
        expr: |
          sum(rate(aethelgard_api_auth_failures_total[2m])) * 60 > 10
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "High API authentication failure rate"
          description: "Possible credential stuffing or misconfigured client — >10 auth failures/min"
```

---

## 6. Start the Full Observability Stack

```bash
# docker-compose.observability.yml starts:
#   Jaeger   → http://localhost:16686
#   Prometheus → http://localhost:9090
#   Grafana  → http://localhost:3000

docker compose -f infra/docker-compose.observability.yml up -d

# Set OTLP endpoint so Aethelgard exports traces:
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_CONSOLE_EXPORT=false

# Start API
python -m uvicorn api:app --host 0.0.0.0 --port 8000

# Prometheus scrapes /metrics/prometheus every 15s (configured in prometheus.yml)
# Import dashboard.json into Grafana via: Dashboards → Import
```
