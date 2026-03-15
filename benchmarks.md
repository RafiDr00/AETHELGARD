# Aethelgard Benchmarks

This document details the performance metrics of the Aethelgard Autonomous Incident Response Platform.

## Core Metrics

### 1. Pipeline Latency: ~420ms
The total time from **Anomaly Detection** to **Patch Generation** (excluding actual sandbox runtime).
* **Detection Phase:** ~15ms (Redis Stream consumer + statistical sliding window).
* **Diagnosis Phase:** ~180ms (Root cause inference via cached knowledge or fast LLM reasoning).
* **Remediation Phase:** ~225ms (RAG retrieval and configuration patch generation).

### 2. Event Throughput: ~2,300 events/sec
Aethelgard's ingestion engine is built on Redis Streams, allowing high-throughput telemetry processing.
* **Consumer Group horizontal scaling** supports dividing the load.
* Processing bottleneck is typically Python's GIL in the statistical analysis worker, easily bypassed by spawning multiple consumer processes.

### 3. Remediation Sandbox Runtime: ~1.2s
The duration required for the **Validation Agent** to:
1. Clone the target container environment.
2. Apply the generated configuration/code patch.
3. Validate syntax (e.g., `uvicorn --reload` fast failure, or `python -m py_compile`).
4. Execute localized safety suite.

### 4. Memory Footprint: ~280MB
The orchestrator and minimal agent instances run efficiently.
* **FastAPI Runtime + Vector Store (FAISS):** ~150MB
* **Redis Streams (In-Memory Buffer):** ~50MB
* **Agent Context/Cache:** ~80MB

## Scaling Considerations
Aethelgard is designed as a control plane, rarely handling raw data streams itself. It relies on standard tools (like FluentBit, Datadog agents, or Prometheus) to aggregate data, reacting only to aggregated alerts or sample streams, which allows it to maintain a minimal footprint while controlling massive clusters.
