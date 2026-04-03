import asyncio
import time
import json
import statistics
import logging
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Supress excessive logging for benchmarks
logging.getLogger("aethelgard").setLevel(logging.CRITICAL)

from infrastructure.redis_streams import RedisEventBus
from core.models import EventType, Event
from core.config import get_settings

async def benchmark_event_bus():
    print("starting event bus benchmark...")
    bus = RedisEventBus()
    await bus.connect()
    
    # Warmup
    print("warming up...")
    for i in range(100):
        await bus.publish(EventType.METRIC_RECEIVED, {"warmup": i})
    
    time.sleep(1)
    
    # Benchmark
    total_events = 5000
    latencies = []
    
    print(f"publishing {total_events} events...")
    
    start_time = time.time()
    
    for i in range(total_events):
        t0 = time.time()
        await bus.publish(EventType.METRIC_RECEIVED, {"iteration": i, "value": 42})
        t1 = time.time()
        latencies.append((t1 - t0) * 1000) # in ms
        
    duration = time.time() - start_time
    
    mean = statistics.mean(latencies)
    median = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=100)[94] if hasattr(statistics, 'quantiles') else sorted(latencies)[int(0.95 * len(latencies))]
    minimum = min(latencies)
    maximum = max(latencies)
    throughput = total_events / duration
    
    print("\n--- Event Bus Benchmark Results ---")
    print(f"Total Events Published: {total_events}")
    print(f"Total Time: {duration:.4f} seconds")
    print(f"Throughput: {throughput:.2f} events/sec")
    print(f"Mean Latency: {mean:.2f} ms")
    print(f"P95 Latency:  {p95:.2f} ms")
    print(f"Min Latency:  {minimum:.2f} ms")
    print(f"Max Latency:  {maximum:.2f} ms")
    print("-----------------------------------")
    
    await bus.disconnect()

if __name__ == "__main__":
    asyncio.run(benchmark_event_bus())
