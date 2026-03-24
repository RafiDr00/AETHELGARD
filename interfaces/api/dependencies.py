import os
from typing import Optional
from fastapi import Request, Security, HTTPException, WebSocket
from fastapi.security import APIKeyHeader
from core.telemetry import API_AUTH_FAILURES_TOTAL
from core.logging_config import get_logger

logger = get_logger("aethelgard.api.dependencies")

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def _load_valid_api_keys() -> set:
    keys = set()
    primary = os.environ.get("AETHELGARD_API_KEY", "")
    if primary:
        keys.add(primary)
    extra = os.environ.get("AETHELGARD_API_KEYS", "")
    if extra:
        keys.update(k.strip() for k in extra.split(",") if k.strip())
    if not keys:
        raise RuntimeError(
            "AETHELGARD_API_KEY environment variable must be set. "
            "No API key is configured — refusing to start with an unsecured endpoint."
        )
    return keys

VALID_API_KEYS: set = _load_valid_api_keys()

async def require_api_key(x_api_key: Optional[str] = Security(_API_KEY_HEADER)) -> str:
    """Dependency: validates API key for write/action endpoints."""
    if not x_api_key or x_api_key not in VALID_API_KEYS:
        API_AUTH_FAILURES_TOTAL.labels(endpoint="unknown").inc()
        logger.warning("api_auth_failed", provided_key=x_api_key[:8] + "..." if x_api_key else "none")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key

def _resolve_websocket_api_key(websocket: WebSocket) -> Optional[str]:
    """Resolve API key for websocket auth from headers or subprotocols."""
    header_key = (websocket.headers.get("x-api-key") or "").strip()
    if header_key:
        return header_key

    auth_header = (websocket.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()
        if bearer:
            return bearer

    subprotocols = websocket.headers.get("sec-websocket-protocol") or ""
    for item in (p.strip() for p in subprotocols.split(",") if p.strip()):
        if item.startswith("api-key."):
            token = item[len("api-key."):].strip()
            if token:
                return token

    if os.environ.get("AETHELGARD_ALLOW_LEGACY_WS_QUERY_TOKEN", "false").lower() == "true":
        legacy = (websocket.query_params.get("token") or "").strip()
        if legacy:
            logger.warning("websocket_legacy_query_token_used")
            return legacy

    return None

def get_orchestrator(request: Request):
    """Dependency to retrieve the active workflow engine/orchestrator from app state."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service unavailable — orchestrator is not initialized.")
    if hasattr(orchestrator, "ready") and not orchestrator.ready:
        raise HTTPException(status_code=429, detail="Service not ready — orchestrator restore is still in progress.")
    return orchestrator
