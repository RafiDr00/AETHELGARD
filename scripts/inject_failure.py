import httpx
import asyncio
import sys

async def inject_failure(scenario: str):
    base_url = "http://localhost:8001"
    
    async with httpx.AsyncClient() as client:
        if scenario == "latency":
            print("Injecting latency spike (2-3s delay) into payment-service...")
            await client.post(f"{base_url}/fault/latency?enabled=True")
        elif scenario == "error":
            print("Injecting high error rate (50%) into payment-service...")
            await client.post(f"{base_url}/fault/error?rate=0.5")
        elif scenario == "memory":
            print("Injecting 100MB memory leak into payment-service...")
            await client.post(f"{base_url}/fault/memory-leak?bytes={1024*1024*100}")
        elif scenario == "recovery":
            print("Resetting payment-service to healthy state...")
            await client.post(f"{base_url}/fault/latency?enabled=False")
            await client.post(f"{base_url}/fault/error?rate=0.0")
        else:
            print(f"Unknown scenario: {scenario}")
            print("Available: latency, error, memory, recovery")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inject_failure.py <scenario>")
        sys.exit(1)
        
    asyncio.run(inject_failure(sys.argv[1]))
