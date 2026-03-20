# 🏗️ Aethelgard v2 — Autonomous Incident Response Platform

> A production-grade **Autonomous Incident Response Platform**. Core capability: **detect → diagnose → remediate → validate → learn**. Think of it as a mini Datadog / PagerDuty automation engine that automatically resolves infrastructure incidents.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 What It Does

Aethelgard v2 is a fully autonomous multi-agent system that:

1. **Observes distributed telemetry**: Prometheus metrics, Real-time log ingestion.
2. **Detects performance anomalies**: Statistical z-score, rolling threshold analysis.
3. **Diagnoses root causes**: ReAct reasoning loop, pattern matching, RAG.
4. **Generates infrastructure patches**: Knowledge-augmented configuration/code gen.
5. **Validates patches safely**: 5-stage safety pipeline + high-fidelity sandbox.
6. **Remediates infrastructure**: Autonomous deployment and orchestration.
7. **Refines knowledge base**: Autonomous playbook ingestion & history learning.

For detailed documentation on the inner workings, see:
- [Architecture](docs/architecture.md)
- [Agents](docs/agents.md)
- [Infrastructure](docs/infrastructure.md)
- [Benchmarks](docs/benchmarks.md)

### ⚠️ Simulation Transparency
**Safety Disclaimer**: All infrastructure deployment is simulated. The final Kubernetes rollout occurs strictly in a controlled sandbox environment.
This simulation approach is used for safety, to guarantee that autonomous AI systems do not execute catastrophic or untested actions on live production targets while still demonstrating full end-to-end capabilities.

---

## 🏛️ Architecture

```text
                   ┌──────────────────────┐
                   │   Microservices      │
                   │ (sample workload)    │
                   └──────────┬───────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  Log Ingestion    │
                    │  (FluentBit)      │
                    └─────────┬─────────┘
                              │
                              ▼
                   ┌────────────────────┐
                   │ Redis Event Bus    │
                   │ (Streams)          │
                   └─────────┬──────────┘
                             │
      ┌──────────────────────┼───────────────────────┐
      ▼                      ▼                       ▼
Detection Agent        Diagnosis Agent        Knowledge RAG
(anomaly)              (root cause)           (playbooks)

      ▼
Remediation Agent
(generate fix)

      ▼
Validation Agent
(sandbox test)

      ▼
Deployment Agent
(simulated rollout)

      ▼
Metrics
(Grafana)
```

---

## 🎬 Live Demo Scenario

The easiest way to experience the autonomous response is through the 1-Command Demo.

### 1. Start the Platform
```bash
make up
```

### 2. Inject a Failure
You can trigger failures via the CLI or utilizing the failure injection API:
```bash
make inject-failure
# Or specifically:
make inject-memory-leak
make inject-api-latency
```
Alternatively, using the API:
```bash
curl -X POST "http://localhost:8000/api/v1/inject" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: YOUR_API_KEY" \
     -d '{"scenario": "payment_latency_spike"}'
```

### 3. Observe the Response
Watch the system automatically detect, diagnose, remediate, validate, and simulate deployment exactly as configured.

---

## ✅ Verified End-to-End Pipeline

An execution of a full pipeline run yields the following sequence (detection → diagnosis → remediation → validation → deployment).

```text
[AETHELGARD] 🔍 Detection:  API response_time_ms = 2752ms exceeds critical threshold 2000ms
[AETHELGARD] 🧠 Diagnosis:  Analyze worker pool configuration on payment-api
[AETHELGARD] 🧠 Diagnosis:  Worker pool saturated — async workers=2, queue depth=847
[AETHELGARD] 🔧 Remediation: Increase workers from 2 → 8, enable uvloop, add connection pooling
[AETHELGARD] 🔧 Remediation: Patch config file + FastAPI server configuration
[AETHELGARD] 🛡 Validation: Static analysis ✓ | Policy engine ✓ | Sandbox ✓ | Risk: 0.00 (SAFE)
[AETHELGARD] 🚀 Deployment: Rolling update → payment-api:patch-1772798190 | Health check ✓
[AETHELGARD] 📈 Resolution: Pipeline complete. Mean Time To Repair (MTTR) calculated.
```

---

## 🚀 Quick Start Instructions

1. **Install Dependencies**
   ```bash
      pip install pydantic pydantic-settings structlog rich numpy fastapi uvicorn
   ```

2. **Launch Infrastructure**
   ```bash
   make up
   ```

3. **Open Observability Tools**
      - Ops Console: `http://localhost:8000/ops`
      - Grafana Metrics: `http://localhost:3001`
      - Prometheus UI: `http://localhost:9090`

4. **Run Live Demo Script (CLI)**
   ```bash
   python -X utf8 scripts/demo.py
   ```

---

## 🛠️ Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI, asyncio |
| **AI Reasoning** | ReAct loop, RAG, vector embeddings |
| **Knowledge** | FAISS (optional), hash embeddings (fallback) |
| **Event Bus** | Redis Streams (with consumer groups + DLQ) |
| **Sandbox** | Docker containers (simulated fallback) |
| **Infrastructure** | Docker, Docker Compose, Kubernetes |
| **Logging** | structlog (structured JSON) |
