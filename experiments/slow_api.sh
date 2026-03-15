#!/bin/bash
echo "🚀 Injecting 2s API Latency into payment-service..."
# Enable the latency fault mode
curl -s -X POST "http://localhost:8001/fault/latency?enabled=true" > /dev/null

echo "⏳ Simulating background traffic to trigger the anomaly..."
for i in {1..50}
do
  curl -s "http://localhost:8001/payment" > /dev/null &
  sleep 0.1
done

echo "✅ Slow API active. Watch Grafana for latency spikes."
