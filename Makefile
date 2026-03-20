.PHONY: up down logs inject-failure inject-memory-leak inject-api-latency inject-db-overload

up:
	@echo "🚀 Starting Aethelgard Autonomous Incident Response Platform..."
	cd infra && docker compose up -d --build
	@echo "=========================================================="
	@echo "✅ Aethelgard is running!"
	@echo "📈 Metrics (Grafana):     http://localhost:3001 (admin/admin)"
	@echo "🔌 API Docs (FastAPI):    http://localhost:8000/docs"
	@echo "=========================================================="

down:
	@echo "🛑 Stopping Aethelgard..."
	cd infra && docker compose down -v

logs:
	cd infra && docker compose logs -f

# Default demo failure injection
inject-failure: inject-api-latency

inject-memory-leak:
	@bash experiments/memory_leak.sh

inject-api-latency:
	@bash experiments/slow_api.sh

inject-db-overload:
	@bash experiments/db_overload.sh
