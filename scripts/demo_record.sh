#!/bin/bash
# Demo recording script for Asciinema or fast terminal recording
set -e

echo "=========================================================="
echo "🛡  Aethelgard v2.0 - Incident Response Demo"
echo "=========================================================="
echo "Starting Aethelgard Infrastructure..."
cd infra && docker-compose up -d
cd ..

echo "Waiting for services to warm up..."
sleep 5

echo "Injecting SLOW API failure into 'payment-service'..."
curl -s -X POST "http://localhost:8001/fault/latency?enabled=true" > /dev/null

echo "Simulating organic traffic to trigger detection..."
for i in {1..35}; do
  curl -s "http://localhost:8001/payment" > /dev/null &
  sleep 0.1
done

echo ""
echo "Traffic simulated. Aethelgard Pipeline Execution Logs:"
echo "----------------------------------------------------------"
# Tail logs for the API specifically, since that's where the ReAct loop runs
cd infra
docker-compose logs --tail=50 -f aethelgard-api
