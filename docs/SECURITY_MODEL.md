# Aethelgard v2 — Security Model

## Table of Contents
1. [Threat Model](#threat-model)
2. [API Authentication](#api-authentication)
3. [Sandbox Security](#sandbox-security)
4. [Container Hardening](#container-hardening)
5. [Network Isolation](#network-isolation)
6. [Secrets Management](#secrets-management)
7. [Static Analysis Gates](#static-analysis-gates)
8. [Known Limitations](#known-limitations)

---

## Threat Model

| Threat | Vector | Mitigation |
|---|---|---|
| Unauthorized API access | HTTP | API key required on all write/action endpoints |
| Code injection via remediation | Sandbox exec | Docker isolation; no-network; read-only FS |
| Lateral movement from sandbox | Container escape | cap-drop ALL; no-new-privileges; pid limit |
| Redis data exfiltration | Internal network | Password-protected; bound to 127.0.0.1 in prod |
| Supply-chain attack (deps) | requirements.txt | Pinned versions; bandit SAST in CI; no vulnerable packages |
| Secrets leakage | Environment | `.env` in `.gitignore`; no secrets in image layers |
| DDoS / rate exhaustion | HTTP | CORS restricted; concurrency limits via uvicorn workers |
| Privilege escalation | OS | All containers run with `no-new-privileges` and `cap-drop ALL` |

---

## API Authentication

### Mechanism

All write and action endpoints require an `X-API-Key` header:

```
X-API-Key: <AETHELGARD_API_KEY>
```

Authentication is enforced in `api.py` via FastAPI's `Security` dependency:

```python
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
VALID_API_KEYS: set = _load_valid_api_keys()  # loaded from env at startup

async def require_api_key(x_api_key: Optional[str] = Security(_API_KEY_HEADER)) -> str:
    if not x_api_key or x_api_key not in VALID_API_KEYS:
        API_AUTH_FAILURES_TOTAL.labels(endpoint="unknown").inc()  # Prometheus counter
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key
```

Authentication failures are:
- Logged at WARNING level with structlog (truncated key, never full value)
- Counted in `aethelgard_api_auth_failures_total` Prometheus metric
- Returned as `401 Unauthorized` with `WWW-Authenticate: ApiKey` header

### Protected vs. Public endpoints

| Endpoint | Auth required |
|---|---|
| `GET /health` | No |
| `GET /ready` | No |
| `GET /metrics` | No |
| `GET /metrics/prometheus` | No |
| `GET /pipeline/jobs` | No |
| `GET /knowledge/search` | No |
| `POST /pipeline/run` | Yes |
| `POST /inject` | Yes |
| WebSocket `/api/remediation/{id}/timeline/ws` | No (unauthenticated) |

### Key requirements

- Minimum 32 characters
- Generated with `secrets.token_urlsafe(32)`
- Stored as environment variable only (`AETHELGARD_API_KEY`)
- Never logged, never in image, never in source code

---

## Sandbox Security

The sandbox executor (`sandbox/sandbox_executor.py`) runs arbitrary remediation code inside a Docker container with the following mandatory constraints:

### Docker flags (all required)

```bash
--network none          # no outbound/inbound network
--cap-drop ALL          # drop all Linux capabilities
--security-opt no-new-privileges   # prevent privilege escalation via setuid
--pids-limit 64         # prevent fork bombs
--memory 256m           # prevent memory exhaustion
--read-only             # immutable root filesystem
--tmpfs /tmp:size=100M,noexec      # writable scratch (non-executable)
```

### Contract enforcement

The `_require_container` attribute is asserted `True` in CI (Stage 7) and at startup:

```python
# Stage 7 CI check:
assert ex._require_container is True
```

If `_require_container` is `False` (e.g., Docker unavailable), the executor **raises** rather than falling back to subprocess. There is no unsafe fallback in production.

### Sandbox image

Built from `infra/Dockerfile.sandbox` — a minimal image with only the Python interpreter and no network tools, shells, or package managers.

---

## Container Hardening

All production containers share these hardening settings (declared in `infra/docker-compose.yml`):

```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
read_only: true      # API and Sandbox containers
tmpfs:
  - /tmp:size=64M    # writable scratch area
```

Additionally:
- Containers do **not** run as root (Dockerfile uses `USER aethelgard`)
- `restart: unless-stopped` ensures availability without compromising security
- Resource limits prevent noisy-neighbor and DoS within the same host

---

## Network Isolation

### Production network segmentation

```
Internet
    │  (port 8000, 8501 only)
    ▼
[ Reverse Proxy / Load Balancer — TLS termination ]
    │
    ▼
aethelgard-net (172.20.0.0/16)
    ├── aethelgard-api      ← can reach redis, prometheus
    ├── aethelgard-dashboard ← can reach api only
    ├── redis               ← 127.0.0.1:6379 only (not exposed to internet)
    ├── prometheus          ← 127.0.0.1:9090 only
    └── grafana             ← 127.0.0.1:3000 only

Sandbox containers
    └── --network none      ← completely isolated
```

### CORS policy

CORS is restricted to explicit origins in `api.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,        # list from AETHELGARD_CORS_ORIGINS env var
    allow_credentials=False,               # credentials=True with origins list forbidden
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)
```

Wildcard `*` is **never** used as an allowed origin.

---

## Secrets Management

### Rules

1. All secrets are passed via environment variables — never baked into Docker images
2. `.env` is in `.gitignore` and must never be committed
3. In Kubernetes, secrets are stored in `Secret` objects, not `ConfigMap`
4. Redis password is required in production (`REDIS_PASSWORD` has no safe default)
5. `GRAFANA_PASSWORD` causes compose to fail-fast if unset (`:?` syntax)

### Verification

Check no secrets are in the image:
```bash
docker history aethelgard:prod --no-trunc | grep -i "key\|password\|secret\|token"
# Must return nothing
```

---

## Static Analysis Gates

Run automatically in CI Stage 3:

```bash
bandit -r agents/ core/ sandbox/ api.py -q
```

Bandit checks include:
- Hardcoded passwords (`B105`, `B106`, `B107`)
- Use of `subprocess.shell=True` (`B602`, `B603`)
- Pickle deserialization (`B301`, `B302`)
- Insecure YAML (`B506`)
- SQL injection patterns (`B608`)
- `exec()` / `eval()` calls (`B102`)

CI fails on any `MEDIUM` or `HIGH` severity finding.

---

## Known Limitations

| Limitation | Risk | Mitigation |
|---|---|---|
| Single API key (no per-user auth) | Key rotation affects all clients | Rotate behind load balancer; use short-lived tokens if needed |
| No mTLS between services | Man-in-the-middle on internal network | Deploy behind VPN or service mesh (Istio/Linkerd) for multi-host |
| Sandbox image must be pre-built | Stale image may have CVEs | Pin `aethelgard-sandbox:latest` tag; scan with `docker scout` in CI |
| Redis Streams in-memory (with AOF) | Data loss on unclean shutdown | `appendfsync everysec` limits to 1-second of data loss |
| No audit log for API key hits | Forensics gap | Add structured log with request ID + endpoint (no key value) |
