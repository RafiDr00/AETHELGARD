# Aethelgard — Operations Runbook

## Table of Contents
1. [Service Health Checks](#service-health-checks)
2. [Common Alerts and Responses](#common-alerts-and-responses)
3. [Log Analysis](#log-analysis)
4. [Scaling](#scaling)
5. [Backup and Restore](#backup-and-restore)
6. [Certificate Renewal](#certificate-renewal)
7. [Dependency Updates](#dependency-updates)
8. [Emergency Procedures](#emergency-procedures)

---

## Service Health Checks

### Quick status

```bash
# All containers
docker compose -f infra/docker-compose.yml ps

# API health
curl -sf http://localhost:8000/health | python -m json.tool

# Redis
docker exec aethelgard-redis redis-cli -a "$REDIS_PASSWORD" ping
# Expected: PONG

# Prometheus targets
curl -s http://localhost:9090/api/v1/targets | python -m json.tool | grep '"health"'
# All should be "up"
```

### Deep health check

```bash
# Metrics endpoint
curl -s http://localhost:8000/metrics | grep -E "^aethelgard_"

# Pipeline jobs (no auth required for listing)
curl http://localhost:8000/pipeline/jobs

# Redis stream lengths
docker exec aethelgard-redis-prod redis-cli -a "$REDIS_PASSWORD" \
  XLEN events:anomalies XLEN events:diagnosed XLEN events:remediation
```

---

## Common Alerts and Responses

### Alert: API returning 5xx

**Symptoms**: Prometheus alert on `aethelgard_requests_total{status="5xx"}` > threshold

**Diagnosis**:
```bash
# Recent error logs
docker logs aethelgard-api-prod --since 10m | grep '"level":"error"'

# Check Python tracebacks
docker logs aethelgard-api-prod --since 10m | grep -A5 "Traceback"
```

**Response**:
1. If Redis-related: check Redis connectivity (see below)
2. If OOM: increase memory limit in `docker-compose.prod.yml` → redeploy
3. If code bug: roll back (see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#rollback-procedure))

---

### Alert: Redis disconnected

**Symptoms**: API health endpoint reports `"redis": "disconnected"`

**Diagnosis**:
```bash
docker inspect aethelgard-redis-prod | grep '"Status"'
docker logs aethelgard-redis-prod --tail 50
```

**Response**:
```bash
# Attempt graceful restart
docker compose -f infra/docker-compose.prod.yml restart redis

# Wait for healthy
docker inspect --format='{{.State.Health.Status}}' aethelgard-redis-prod
# → healthy

# API will auto-reconnect (redis[asyncio] has retry backoff)
```

---

### Alert: Sandbox execution failures spiking

**Symptoms**: `aethelgard_sandbox_executions_total{status="failed"}` increasing

**Diagnosis**:
```bash
# Check sandbox container logs
docker logs aethelgard-sandbox-prod --since 10m

# Verify Docker socket is accessible
docker exec aethelgard-api-prod docker version 2>&1 || echo "DOCKER_UNAVAILABLE"

# Check available disk (sandbox images need space)
df -h /var/lib/docker
```

**Response**:
1. If Docker socket unavailable: `systemctl restart docker` (Linux) or restart Docker Desktop
2. If disk full: prune unused images `docker image prune -f`
3. If sandbox image missing: `docker build -f infra/Dockerfile.sandbox -t aethelgard-sandbox:latest .`

---

### Alert: High memory on API container

**Symptoms**: Container approaching memory limit (> 800 MB)

**Diagnosis**:
```bash
docker stats aethelgard-api-prod --no-stream

# Check FAISS index size
docker exec aethelgard-api-prod du -sh /app/data/faiss_index/
```

**Response**:
- Short-term: `docker compose -f infra/docker-compose.prod.yml restart aethelgard-api`
- Long-term: increase memory limit in compose file (`1G` → `2G`) or reduce embedding model size

---

### Alert: Prometheus scrape failing

**Symptoms**: Grafana dashboard shows "No data"

**Diagnosis**:
```bash
# Check Prometheus
curl -s http://localhost:9090/-/ready

# Check target health
curl -s 'http://localhost:9090/api/v1/targets' | python -m json.tool
```

**Response**:
```bash
docker compose -f infra/docker-compose.prod.yml restart prometheus
```

---

## Log Analysis

### Structured log queries

All logs are JSON. Use `jq` for filtering:

```bash
# Errors in last hour
docker logs aethelgard-api-prod --since 1h 2>&1 \
  | grep '"level":"error"' | jq '.message'

# Slow requests (> 1s)
docker logs aethelgard-api-prod --since 1h 2>&1 \
  | jq 'select(.duration_ms > 1000) | {path, duration_ms, status}'

# Auth failures
docker logs aethelgard-api-prod --since 1h 2>&1 \
  | jq 'select(.event == "auth_failure")'

# Remediation events
docker logs aethelgard-api-prod --since 1h 2>&1 \
  | jq 'select(.event | contains("remediation")) | {event, service, status}'
```

### Log rotation

Managed by Docker's json-file driver (configured in compose):
```yaml
logging:
  driver: json-file
  options:
    max-size: "20m"
    max-file: "5"
```

To view rotated logs: `docker logs aethelgard-api-prod`

---

## Scaling

### Horizontal scaling (multiple API replicas)

```bash
# Scale API to 3 replicas
docker compose -f infra/docker-compose.yml up -d --scale aethelgard-api=3
```

> Requires a load balancer in front (nginx/Traefik). Redis Streams consumer groups ensure each replica gets a distinct share of work.

### Vertical scaling

Edit memory/CPU limits in `infra/docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      cpus: "4.0"    # increase
      memory: 2G     # increase
```

Then:
```bash
docker compose -f infra/docker-compose.prod.yml up -d aethelgard-api
```

---

## Backup and Restore

### Redis (event streams + state)

**Backup** (AOF is on by default):
```bash
# Trigger AOF rewrite/snapshot
docker exec aethelgard-redis-prod redis-cli -a "$REDIS_PASSWORD" BGSAVE

# Copy RDB snapshot
docker cp aethelgard-redis-prod:/data/dump.rdb ./backups/redis-$(date +%Y%m%d-%H%M%S).rdb
```

**Restore**:
```bash
# Stop redis
docker compose -f infra/docker-compose.prod.yml stop redis

# Copy backup into volume
docker run --rm -v aethelgard_redis-data:/data \
  -v ./backups:/backup \
  alpine cp /backup/redis-YYYYMMDD-HHMMSS.rdb /data/dump.rdb

# Restart
docker compose -f infra/docker-compose.prod.yml start redis
```

### FAISS index (knowledge base)

```bash
# Backup
docker cp aethelgard-api-prod:/app/data/faiss_index ./backups/faiss-$(date +%Y%m%d)

# Restore
docker cp ./backups/faiss-YYYYMMDD aethelgard-api-prod:/app/data/faiss_index
docker compose -f infra/docker-compose.prod.yml restart aethelgard-api
```

---

## Certificate Renewal

If using Caddy (recommended) as a reverse proxy, certificates auto-renew. For manual nginx + certbot:

```bash
certbot renew --nginx
systemctl reload nginx
```

No Aethelgard service restart required — TLS terminates at the reverse proxy.

---

## Dependency Updates

### Python packages

```bash
# Check for outdated packages
pip list --outdated

# Update requirements.txt (preserves pinned versions)
pip install pip-tools
pip-compile --upgrade requirements.in -o requirements.txt

# Run tests after update
python -m pytest -q --tb=short
```

### Docker base images

```bash
# Pull latest patch versions
docker pull python:3.11-slim
docker pull redis:7-alpine
docker pull prom/prometheus:1.0
docker pull grafana/grafana:10.4.0

# Rebuild
docker compose -f infra/docker-compose.prod.yml build --no-cache
docker compose -f infra/docker-compose.prod.yml up -d
```

---

## Emergency Procedures

### Full platform restart

```bash
docker compose -f infra/docker-compose.prod.yml down
docker compose -f infra/docker-compose.prod.yml up -d
# Wait for health checks
sleep 20
curl -sf http://localhost:8000/health
```

### Nuclear option (data-preserving)

```bash
# Stop all containers (volumes preserved)
docker compose -f infra/docker-compose.prod.yml down

# Remove and recreate containers only
docker compose -f infra/docker-compose.prod.yml up -d --force-recreate

# Verify volumes intact
docker volume ls | grep aethelgard
```

### Emergency agent pipeline drain

If the anomaly pipeline is stuck in a loop:
```bash
# Flush all agent input streams
docker exec aethelgard-redis redis-cli -a "$REDIS_PASSWORD" \
  DEL events:anomalies events:diagnosed events:remediation events:validated events:deployed

# Restart API to clear in-memory state
docker compose -f infra/docker-compose.yml restart aethelgard-api
```

### Escalation contacts

Document your escalation contacts here:

| Role | Contact | When to escalate |
|---|---|---|
| On-call engineer | `#oncall` Slack channel | API down > 5 minutes |
| Platform lead | — | Data loss, security incident |
| Security team | — | Auth failures spike, suspected breach |
