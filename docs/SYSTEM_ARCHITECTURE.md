# Aethelgard v2 — System Architecture

## Table of Contents
1. [Overview](#overview)
2. [Component Inventory](#component-inventory)
3. [Data Flow](#data-flow)
4. [Agent Pipeline](#agent-pipeline)
5. [Observability Stack](#observability-stack)
6. [Infrastructure Topology](#infrastructure-topology)
7. [Key Design Decisions](#key-design-decisions)

---

## Overview

Aethelgard is a **multi-agent AIOps platform** that ingests telemetry from running services, detects anomalies, diagnoses root causes, proposes and validates remediations, and executes them inside a hardened sandbox — all with a full observability layer and a REST API surface.

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Aethelgard v2                                  │
│                                                                        │
│  ┌──────────┐    ┌─────────────────────────────────────────────────┐  │
│  │ REST API │───▶│                Agent Orchestrator               │  │
│  │ (FastAPI)│    │  Detection → Diagnosis → Remediation →          │  │
│  └──────────┘    │  Validation → Deployment → Sandbox Exec        │  │
│       │          └─────────────────────────────────────────────────┘  │
│       │                           │                                    │
│  ┌────▼────┐    ┌──────────┐  ┌───▼──────┐   ┌────────────────────┐  │
│  │Metrics  │    │  Redis   │  │   RAG    │   │  Sandbox Executor  │  │
│  │Listener │    │ Streams  │  │  Engine  │   │  (Docker, isolated)│  │
│  └─────────┘    └──────────┘  └──────────┘   └────────────────────┘  │
│                                                                        │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐             │
│  │  Prometheus  │   │   Grafana    │   │   OTel Traces │             │
│  └──────────────┘   └──────────────┘   └───────────────┘             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Component Inventory

| Component | Module | Responsibility |
|---|---|---|
| **API Server** | `api.py` | FastAPI REST + WebSocket; API-key auth; metrics endpoint |
| **Agent Orchestrator** | `agents/orchestrator.py` | Coordinates pipeline stages; deduplicates anomaly fingerprints |
| **Detection Agent** | `agents/detection_agent.py` | Consumes metrics stream; produces anomaly events |
| **Diagnosis Agent** | `agents/diagnosis_agent.py` | Root-cause analysis using RAG + heuristics |
| **Remediation Agent** | `agents/remediation_agent.py` | Generates remediation plans; mutex per service |
| **Validation Agent** | `agents/validation_agent.py` | Verifies proposed fixes before execution |
| **Deployment Agent** | `agents/deployment_agent.py` | Applies validated remediations |
| **Sandbox Executor** | `sandbox/sandbox_executor.py` | Executes code in hardened Docker container |
| **RAG Engine** | `knowledge/rag_engine.py` | FAISS vector store + sentence-transformers embeddings |
| **Event Bus** | `event_bus/redis_streams.py` | Redis Streams; consumer groups; back-pressure |
| **Metrics Engine** | `metrics/metrics_engine.py` | Aggregates + exposes Prometheus metrics |
| **Log Listener** | `listener/log_listener.py` | Tails `logs/aethelgard.json`; feeds detection pipeline |
| **Real Metrics** | `listener/real_metrics.py` | Live host metrics via psutil |
| **Telemetry** | `core/telemetry.py` | OpenTelemetry SDK; OTLP exporter; custom counters |
| **Config** | `core/config.py` | Pydantic Settings; env-var binding; validation |
| **Dashboard** | `dashboard/streamlit_app.py` | Streamlit real-time UI |

---

## Data Flow

```
External Services / Host OS
        │
        │  (JSON logs / psutil metrics)
        ▼
  ┌─────────────────┐
  │  Log Listener   │   listener/log_listener.py
  │  Real Metrics   │   listener/real_metrics.py
  └────────┬────────┘
           │  anomaly candidates
           ▼
  ┌─────────────────┐
  │ Detection Agent │   Threshold + statistical checks
  └────────┬────────┘
           │  AnomalyEvent
           ▼
  ┌─────────────────┐   lookup playbooks via
  │ Diagnosis Agent │──▶ RAG Engine (FAISS + sentence-transformers)
  └────────┬────────┘
           │  DiagnosisResult
           ▼
  ┌──────────────────────┐
  │ Remediation Agent    │   per-service asyncio.Lock
  │ (mutex per service)  │
  └────────┬─────────────┘
           │  RemediationPlan
           ▼
  ┌──────────────────┐
  │ Validation Agent │   dry-run checks + playbook conformance
  └────────┬─────────┘
           │  validated plan
           ▼
  ┌──────────────────┐
  │ Deployment Agent │
  └────────┬─────────┘
           │  execute fix
           ▼
  ┌────────────────────┐
  │  Sandbox Executor  │   Docker: --network none, --cap-drop ALL,
  │  (hardened)        │          --read-only, --pids-limit 64
  └────────────────────┘
```

All inter-agent communication is mediated by **Redis Streams** consumer groups, giving persistent, ordered, replayable message delivery.

---

## Agent Pipeline

Each stage is implemented as an independent async agent inheriting from `BaseAgent`:

```python
class BaseAgent:
    async def process(self, event: dict) -> dict: ...
    async def start(self): ...           # subscribe to input stream
    async def stop(self): ...            # drain + unsubscribe
```

The `AgentOrchestrator` manages lifecycle, fingerprint deduplication (`seen_fingerprints: set`), and per-service remediation locks to prevent concurrent conflicting actions.

### Pipeline stages (in order)

| Stage | Input stream | Output stream |
|---|---|---|
| Detection | `metrics:raw` | `events:anomalies` |
| Diagnosis | `events:anomalies` | `events:diagnosed` |
| Remediation | `events:diagnosed` | `events:remediation` |
| Validation | `events:remediation` | `events:validated` |
| Deployment | `events:validated` | `events:deployed` |

---

## Observability Stack

### Metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `aethelgard_requests_total` | Counter | `method`, `endpoint`, `status` |
| `aethelgard_request_duration_seconds` | Histogram | `method`, `endpoint` |
| `aethelgard_anomalies_detected_total` | Counter | `severity` |
| `aethelgard_remediation_success_total` | Counter | `service` |
| `aethelgard_remediation_failure_total` | Counter | `service` |
| `aethelgard_api_auth_failures_total` | Counter | — |
| `aethelgard_sandbox_executions_total` | Counter | `status` |

Scraped at `http://aethelgard-api:8000/metrics`.

### Traces (OpenTelemetry)

OTLP gRPC exporter targets `OTEL_EXPORTER_OTLP_ENDPOINT` (default: `http://localhost:4317`). Span instrumentation covers:
- FastAPI request lifecycle (via `FastAPIInstrumentor`)
- Agent `process()` calls
- Sandbox execution

### Structured Logging (structlog)

All log output is structured JSON, written to `logs/aethelgard.json` and stdout. Log level controlled by `LOG_LEVEL` env var.

---

## Infrastructure Topology

```
Production Host
│
├── docker network: aethelgard-net (172.20.0.0/16)
│   ├── aethelgard-api:8000      (exposed: 0.0.0.0:8000)
│   ├── aethelgard-dashboard:8501 (exposed: 0.0.0.0:8501)
│   ├── redis:6379               (exposed: 127.0.0.1:6379 only)
│   ├── prometheus:9090          (exposed: 127.0.0.1:9090 only)
│   └── grafana:3000             (exposed: 127.0.0.1:3000 only)
│
└── sandbox containers           (ephemeral, no persistent network)
```

Prometheus and Grafana ports are bound to `127.0.0.1` only; expose them via a reverse proxy (nginx/Caddy) with TLS in public deployments.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Redis Streams** over Kafka | Lower operational complexity for single-host deployments; supports consumer groups + ACK semantics |
| **FAISS** over vector DB service | Zero infra; sub-millisecond local lookup; index fits in RAM for knowledge base size |
| **sentence-transformers/all-MiniLM-L6-v2** | 384-dim embeddings; fast CPU inference; good semantic quality for English DevOps text |
| **Docker sandbox** over subprocess | Hard isolation boundary; prevents breakout through file system, network, or process namespace |
| **asyncio.Lock per service** (remediation) | Prevents duplicate concurrent remediations for the same service while pipeline remains non-blocking |
| **Fingerprint deduplication** (orchestrator) | `sha256(service:metric_name:threshold_pct)` prevents thundering-herd of identical anomaly events |
| **Pydantic Settings** | Type-safe, validated config with automatic env-var binding; fail-fast at startup |
