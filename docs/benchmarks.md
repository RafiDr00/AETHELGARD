# Aethelgard Benchmarks

This document details the performance metrics of the Aethelgard Autonomous Incident Response Platform as well as the methodology used to record them.

## 📊 Real-World Benchmarks

| Metric | Measured |
|--------|----------|
| **Pipeline Latency (Detection to Patch)** | **~420ms** |
| **Event Throughput** | **~2,300 events/sec** |
| **Remediation Sandbox Runtime** | **~1.2s** |
| **Memory Footprint** | **~280MB** |

## 🧪 Benchmarking Methodology

To ensure results are credible, reproducible, and reflective of a real-world edge deployment, the benchmarks are executed under the following standardized conditions.

### Environment

* **Hardware**: 8-Core CPU (x86_64), 16GB RAM
* **OS**: Linux / Windows WSL2 (Ubuntu 22.04 LTS)
* **Python version**: Python 3.11.x
* **Redis version**: Redis 7.x Alpine
* **Docker version**: Docker Engine 24.x+

### Methodology Parameters

* **Load Generation Method**: We utilize custom Python benchmark scripts found in `scripts/benchmarks/` to directly invoke the target components concurrently, minimizing HTTP overhead while stressing the actual Python runtime and GIL.
* **Warmup Period**: 100-200 iterations or a 1-second burst is executed and discarded prior to the timer starting. This ensures Redis connection pools are saturated, JITs (if applicable) are active, and PyDantic schemas are fully compiled.
* **Measurement Window**: We execute 5000+ events for throughput, and 20-50 full pipeline executions for end-to-end latency to gather statistically significant means, medians, and P95 latency bands.

## 🚀 Running the Benchmarks

To reproduce these metrics on your own machine, you can utilize the included benchmark scripts. 
Make sure your infrastructure (`make up`) is running so Redis and Docker are available.

### Event Bus Throughput
Stresses the Redis stream ingestion rate:
```bash
python scripts/benchmarks/benchmark_event_bus.py
```

### Pipeline Latency
Measures the end-to-end autonomous decision loop (excluding sandbox):
```bash
python scripts/benchmarks/benchmark_pipeline_latency.py
```
