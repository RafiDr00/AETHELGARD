import asyncio
import time
import statistics
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Supress excessive logging for benchmarks
logging.getLogger("aethelgard").setLevel(logging.CRITICAL)

from agents.orchestrator import AgentOrchestrator
from knowledge.rag_engine import RAGEngine
from sandbox.sandbox_executor import SandboxExecutor
from tools.docker_client import DockerRemediator
from core.models import ServiceMetric
from datetime import datetime, timezone

async def benchmark_pipeline_latency():
    print("starting pipeline latency benchmark...")
    
    knowledge = RAGEngine()
    await knowledge.initialize()
    
    sandbox = SandboxExecutor()
    await sandbox.initialize()
    
    docker_remediator = DockerRemediator()
    
    orchestrator = AgentOrchestrator(
        knowledge_engine=knowledge,
        sandbox_executor=sandbox,
        docker_remediator=docker_remediator
    )
    await orchestrator.initialize()
    
    # Warmup
    print("warming up...")
    metric = ServiceMetric(
        service_name="payment-api",
        metric_name="response_time_ms",
        value=200,
        unit="ms",
        timestamp=datetime.now(timezone.utc)
    )
    try:
        await orchestrator._detection_agent.analyze_metrics([metric])
    except Exception:
        pass
    
    time.sleep(1)
    
    # Benchmark
    total_runs = 20
    latencies = []
    
    print(f"running {total_runs} simulated pipeline executions...")
    
    start_time = time.time()
    
    for i in range(total_runs):
        t0 = time.time()
        # Force a high metric to trigger detection and the full pipeline
        anomaly_metric = ServiceMetric(
            service_name="payment-api",
            metric_name="response_time_ms",
            value=3500 + i, # Clearly anomalous
            unit="ms",
            timestamp=datetime.now(timezone.utc)
        )
        
        try:
            # wait for full pipeline run completion
            await orchestrator.run_full_pipeline(metrics=[anomaly_metric], scenario="benchmark")
        except Exception as e:
            print(f"Pipeline run failed: {e}")
            
        t1 = time.time()
        latencies.append((t1 - t0) * 1000) # in ms
        
    duration = time.time() - start_time
    
    mean = statistics.mean(latencies)
    median = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=100)[94] if hasattr(statistics, 'quantiles') else sorted(latencies)[int(0.95 * len(latencies))]
    minimum = min(latencies)
    maximum = max(latencies)
    throughput = total_runs / duration
    
    print("\n--- Pipeline Latency Benchmark Results ---")
    print(f"Total Pipeline Runs: {total_runs}")
    print(f"Total Time: {duration:.4f} seconds")
    print(f"Throughput: {throughput:.2f} runs/sec")
    print(f"Mean Latency: {mean:.2f} ms")
    print(f"P95 Latency:  {p95:.2f} ms")
    print(f"Min Latency:  {minimum:.2f} ms")
    print(f"Max Latency:  {maximum:.2f} ms")
    print("------------------------------------------")

if __name__ == "__main__":
    asyncio.run(benchmark_pipeline_latency())
