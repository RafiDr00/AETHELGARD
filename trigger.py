import time
import os
import requests

API_KEY = os.environ.get("AETHELGARD_API_KEY", "")
URL = "http://localhost:8080/api/v1/pipeline/run?scenario=payment_latency_spike"

if not API_KEY:
    raise SystemExit("Set AETHELGARD_API_KEY before running trigger.py")

print("Waiting for server to fully start...")
time.sleep(3)

for i in range(5):
    try:
        response = requests.post(URL, headers={"X-API-Key": API_KEY})
        print(f"Trigger {i+1}: Status Code: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Trigger {i+1} failed: {e}")
    time.sleep(10)

print("Done triggering.")
