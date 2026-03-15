#!/bin/bash
echo "🚀 Simulating Database Overload (Traffic Spike + Errors)..."
# Set error rate to simulating failing queries
curl -s -X POST "http://localhost:8001/fault/error?rate=0.8" > /dev/null

echo "💣 Hitting endpoint with simulated pgbench stress..."
for i in {1..200}
do
  curl -s "http://localhost:8001/payment" > /dev/null &
  if [ $((i % 10)) -eq 0 ]; then
    sleep 0.05
  fi
done

echo "✅ DB Overload active. Watch Grafana for error rate spikes."
