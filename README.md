# Aethelgard — Incident Response Engine

Aethelgard is a multi-agent system for automated infrastructure incident response. It handles the full feedback loop from initial detection through to validation and recovery.

## Overview

The system operates across several distinct stages:

1. **Detection**: Statistical analysis of service telemetry (latency, errors, resource usage).
2. **Diagnosis**: Reasoning over logs and traces to identify root causes.
3. **Remediation**: Generating infrastructure patches or configuration changes.
4. **Validation**: Safety testing within a sandboxed environment.
5. **Recovery**: Managed rollout with rollback capabilities.

## Architecture

```text
       ┌───────────────┐
       │ Microservices │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ Event Stream  │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │  Agent Logic  │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │  Recovery Hub │
       └───────────────┘
```

## Setup

1. **Install Dependencies**
   ```bash
   pip install pydantic pydantic-settings structlog rich numpy fastapi uvicorn
   ```

2. **Launch Services**
   ```bash
   make up
   ```

3. **Access Internal Tools**
   - Console: `http://localhost:8000/ops`
   - Metrics: `http://localhost:3001`

4. **Run Simulation**
   ```bash
   python scripts/demo.py
   ```

## Disclaimer

All infrastructure deployment is simulated within a sandbox. This ensures safe execution for demonstration purposes while maintaining a complete end-to-end workflow.
