# ============================================
# Aethelgard v2 — Application Dockerfile
# Root-level Dockerfile for CI build context
# ============================================

FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# ML deps first: ~2 GB layer that changes rarely — cached unless requirements-ml.txt is edited.
COPY requirements-ml.txt .
RUN pip install --use-deprecated=legacy-resolver --no-cache-dir --prefix=/install -r requirements-ml.txt

# Core deps: smaller, changes more often — rebuilds without touching the ML layer above.
COPY requirements.txt .
RUN pip install --use-deprecated=legacy-resolver --no-cache-dir --prefix=/install -r requirements.txt

# ─────────────────────────────────────
# Production stage
# ─────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Security: non-root user
RUN groupadd -r aethelgard && useradd -r -g aethelgard aethelgard

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p /app/data /app/logs && \
    chown -R aethelgard:aethelgard /app

USER aethelgard

# Runtime env: bind to all interfaces, dev mode skips DinD preflight
ENV APP_HOST="0.0.0.0" \
    APP_ENV="development"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "main.py"]
