#!/bin/bash
echo "🚀 Injecting Memory Leak into payment-service..."
# Call the endpoint to leak 50MB of memory 10 times (500MB total)
for i in {1..10}
do
  curl -s -X POST "http://localhost:8001/fault/memory-leak?bytes=52428800" > /dev/null
  echo "💧 Leaked 50MB..."
  sleep 1
done
echo "✅ Memory Leak active. Watch Grafana for memory_usage spikes."
