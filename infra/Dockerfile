# ============================================
# Aethelgard v2 — Application Dockerfile
# Multi-stage build for production
# ============================================

FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "main.py"]
