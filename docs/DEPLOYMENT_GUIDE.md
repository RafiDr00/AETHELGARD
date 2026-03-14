# Aethelgard v2 — Deployment Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Environment Variables](#environment-variables)
3. [Local Development](#local-development)
4. [Production Deployment](#production-deployment)
5. [Kubernetes Deployment](#kubernetes-deployment)
6. [Post-Deploy Validation](#post-deploy-validation)
7. [Rollback Procedure](#rollback-procedure)

---

## Prerequisites

| Tool | Minimum Version | Notes |
|---|---|---|
| Docker | 24.x | With BuildKit enabled |
| Docker Compose | 2.20.x | Plugin form (`docker compose`) |
| Python | 3.11 | For local runs / scripts (`requires-python = ">=3.11"`) |
| pip | 23.x | `pip install --upgrade pip` |
| Redis | 7.x | Provided via Docker |
| curl | any | For health checks |

---

## Environment Variables

Create a `.env` file (never commit it) or export these before running:

```bash
# ─── Required ─────────────────────────────────────────────
AETHELGARD_API_KEY=<strong-random-secret>   # min 32 chars
GRAFANA_PASSWORD=<strong-grafana-password>

# ─── Recommended in Production ────────────────────────────
REDIS_PASSWORD=<strong-redis-password>
GRAFANA_ROOT_URL=https://grafana.your-domain.com
IMAGE_TAG=v2.0.0                             # pin image tag

# ─── Optional Overrides ───────────────────────────────────
APP_ENV=production                           # development | staging | production
LOG_LEVEL=INFO                               # DEBUG | INFO | WARNING | ERROR
REDIS_HOST=redis
REDIS_PORT=6379

# ─── OpenTelemetry (optional) ─────────────────────────────
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=aethelgard
```

Generate a secure API key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Local Development

### 1. Clone and install

```bash
git clone <repo-url> aethelgard
cd aethelgard
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Start services (dev mode)

```bash
# From repo root — starts api + dashboard + redis + sandbox
docker compose -f infra/docker-compose.yml up -d

# Follow logs
docker compose -f infra/docker-compose.yml logs -f aethelgard-api
```

### 3. Seed the knowledge base

```bash
python scripts/seed_knowledge.py
```

### 4. Run the test suite

```bash
python -m pytest -q --tb=short
```

### 5. Access endpoints

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |
| Dashboard | http://localhost:8501 |

---

## Production Deployment

### 1. Build the production image

```bash
docker build -t aethelgard:$(git rev-parse --short HEAD) .
# or tag explicitly:
docker build -t aethelgard:v2.0.0 .
```

### 2. Create the .env file

```bash
cp .env.example .env   # fill in required secrets
```

### 3. Deploy with production compose

```bash
cd infra
docker compose -f docker-compose.prod.yml up -d
```

### 4. Verify health

```bash
# API
curl -f http://localhost:8000/health

# Metrics endpoint
curl -s http://localhost:8000/metrics | head -20

# Redis connectivity
docker exec aethelgard-redis-prod redis-cli -a "$REDIS_PASSWORD" ping
```

### 5. Seed knowledge base (first deploy only)

```bash
docker exec aethelgard-api-prod python scripts/seed_knowledge.py
```

### 6. Verify services

```bash
docker compose -f infra/docker-compose.prod.yml ps
```

All services should show `healthy` or `running`.

---

## Kubernetes Deployment

Manifests are in `infra/kubernetes/`.

### Apply in order

```bash
# 1. Namespace
kubectl apply -f infra/kubernetes/namespace.yaml

# 2. ConfigMap
kubectl apply -f infra/kubernetes/configmap.yaml

# 3. Deployment
kubectl apply -f infra/kubernetes/deployment.yaml

# 4. Service
kubectl apply -f infra/kubernetes/service.yaml
```

### Create the API key Secret

```bash
kubectl create secret generic aethelgard-secrets \
  --namespace=aethelgard \
  --from-literal=api-key="$AETHELGARD_API_KEY" \
  --from-literal=redis-password="$REDIS_PASSWORD"
```

### Check rollout

```bash
kubectl rollout status deployment/aethelgard -n aethelgard
kubectl get pods -n aethelgard
```

### Port-forward for local access

```bash
kubectl port-forward svc/aethelgard-service 8000:8000 -n aethelgard
```

---

## Post-Deploy Validation

Run the full validation script:

```bash
python scripts/validate_fixes.py
python scripts/verify_fixes.py
```

Manual smoke checks:

```bash
# Health
curl http://localhost:8000/health

# Authenticated endpoint
curl -H "X-API-Key: $AETHELGARD_API_KEY" http://localhost:8000/pipeline/status

# Metrics
curl -s http://localhost:8000/metrics | grep aethelgard_requests_total
```

Expected health response:
```json
{
  "status": "healthy",
  "uptime_seconds": 12.3,
  "redis": "connected",
  "agents": "running"
}
```

---

## Rollback Procedure

### Docker Compose

```bash
# Pin previous image tag in .env:
IMAGE_TAG=v1.9.0

# Re-deploy
docker compose -f infra/docker-compose.prod.yml up -d --no-build

# Verify
curl -f http://localhost:8000/health
```

### Kubernetes

```bash
# Roll back to previous revision
kubectl rollout undo deployment/aethelgard -n aethelgard

# Check rollout
kubectl rollout status deployment/aethelgard -n aethelgard
```

### Redis state

If a bad deploy corrupted Redis Streams, flush the agent input streams:

```bash
docker exec aethelgard-redis-prod redis-cli -a "$REDIS_PASSWORD" \
  DEL events:anomalies events:diagnosed events:remediation events:validated events:deployed
```

> **Warning**: This discards all in-flight events. Only do this when the pipeline is stopped.
