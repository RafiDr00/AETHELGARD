import time
import random
import threading
import os
from fastapi import FastAPI, Response, Request
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="Payment Service (Aethelgard Target)")

# --- Prometheus Metrics ---
REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"]
)
MEMORY_USAGE_GAUGE = Gauge("service_memory_usage_bytes", "Service memory usage in bytes")
DB_CONNECTIONS = Gauge("db_connection_pool_active", "Active DB connections")

# --- Fault States ---
FAULT_LATENCY = False
FAULT_ERROR_RATE = 0.0
MEMORY_LEAK_DATA = []

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start_time = time.monotonic()
    
    # Simulate DB connection pool usage
    DB_CONNECTIONS.set(random.randint(10, 85 if not FAULT_LATENCY else 98))
    
    # Inject latency
    if FAULT_LATENCY:
        time.sleep(random.uniform(1.5, 3.0))
        
    # Inject errors
    if random.random() < FAULT_ERROR_RATE:
        response = Response(content="Internal Server Error", status_code=500)
    else:
        response = await call_next(request)
        
    duration = time.monotonic() - start_time
    
    status_code = response.status_code
    REQUESTS_TOTAL.labels(method=request.method, endpoint=request.url.path, http_status=status_code).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=request.url.path).observe(duration)
    
    return response

@app.get("/payment")
async def process_payment():
    # Regular workload
    time.sleep(random.uniform(0.01, 0.1))
    return {"status": "success", "transaction_id": random.randint(1000, 9999)}

@app.get("/metrics")
async def metrics():
    # Update memory gauge
    import psutil
    process = psutil.Process(os.getpid())
    MEMORY_USAGE_GAUGE.set(process.memory_info().rss)
    
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# --- Fault Injection Endpoints ---

@app.post("/fault/latency")
async def toggle_latency(enabled: bool):
    global FAULT_LATENCY
    FAULT_LATENCY = enabled
    return {"status": "ok", "fault_latency": FAULT_LATENCY}

@app.post("/fault/error")
async def set_error_rate(rate: float):
    global FAULT_ERROR_RATE
    FAULT_ERROR_RATE = rate
    return {"status": "ok", "fault_error_rate": FAULT_ERROR_RATE}

@app.post("/fault/memory-leak")
async def trigger_memory_leak(bytes: int = 1024 * 1024 * 10): # 10MB
    def leak():
        global MEMORY_LEAK_DATA
        MEMORY_LEAK_DATA.append(" " * bytes)
    
    threading.Thread(target=leak).start()
    return {"status": "ok", "message": f"Leaked {bytes} bytes"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
