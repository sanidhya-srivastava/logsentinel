# =============================================================================
# LogSentinel — Log Ingestion API
# Multi-stage Dockerfile
# =============================================================================
# Stage 1 (builder): install dependencies into a venv
# Stage 2 (runtime): copy only the venv + source — no build tooling in prod
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 — Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Build-time metadata
LABEL stage="builder"

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    # Place the venv inside the image at a known path
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Install system build dependencies needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create the virtual environment
RUN python -m venv ${VIRTUAL_ENV}

# Copy only the requirements file first to maximise Docker layer cache reuse.
# The venv layer is only rebuilt when requirements.txt changes.
WORKDIR /build
COPY requirements.txt .

# Install all Python dependencies into the venv
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Runtime metadata
LABEL maintainer="LogSentinel Team <team@logsentinel.io>" \
      org.opencontainers.image.title="LogSentinel Log Ingestion API" \
      org.opencontainers.image.description="FastAPI service that receives log entries and publishes to Kafka" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/your-org/logsentinel"

# Runtime environment variables — all overridable at container start
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Use the venv from the builder stage
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    # Application defaults (override via docker run -e or K8s ConfigMap)
    SERVICE_NAME="log-ingestion-api" \
    ENVIRONMENT="production" \
    LOG_LEVEL="INFO" \
    INGESTION_API_HOST="0.0.0.0" \
    INGESTION_API_PORT="8000" \
    INGESTION_API_WORKERS="1" \
    KAFKA_BOOTSTRAP_SERVERS="kafka:9092" \
    KAFKA_TOPIC_RAW_LOGS="raw-logs"

# Install only the minimal runtime system libraries
# (no build tools — keeps the image lean and reduces attack surface)
RUN apt-get update && apt-get install -y --no-install-recommends \
        # curl is needed for Docker/K8s health check commands
        curl \
        # ca-certificates for TLS connections (Kafka, HTTPS)
        ca-certificates \
        # tini: proper PID 1 init process — handles signal forwarding & zombie reaping
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# ---------------------------------------------------------------------------
# Create a non-root user and group for running the application
# Running as root inside a container is a security risk.
# ---------------------------------------------------------------------------
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser

# Set working directory
WORKDIR /app

# Copy application source code
# Ownership set to appuser at copy time — avoids a separate chown layer
COPY --chown=appuser:appgroup . .

# ---------------------------------------------------------------------------
# Switch to non-root user for all subsequent commands and at runtime
# ---------------------------------------------------------------------------
USER appuser

# ---------------------------------------------------------------------------
# Expose the application port
# (informational — actual port binding is done by docker run / K8s service)
# ---------------------------------------------------------------------------
EXPOSE 8000

# ---------------------------------------------------------------------------
# Health check
# Kubernetes also performs its own probes via the Deployment manifest,
# but this Docker-native check is useful for docker compose and local testing.
# ---------------------------------------------------------------------------
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=15s \
    --retries=3 \
    CMD curl -f http://localhost:${INGESTION_API_PORT}/health || exit 1

# ---------------------------------------------------------------------------
# Entrypoint — use tini as PID 1 for proper signal handling
# ---------------------------------------------------------------------------
ENTRYPOINT ["/usr/bin/tini", "--"]

# ---------------------------------------------------------------------------
# Default command — start Uvicorn
#
# --host / --port   : bind address from environment (passed as shell variable
#                     expansion via exec form wrapper)
# --workers         : number of Uvicorn worker processes
# --proxy-headers   : trust X-Forwarded-* headers from the ingress/load balancer
# --forwarded-allow-ips: trust all upstream proxies (set appropriately in prod)
# --no-access-log   : access logging handled by the middleware + JSON logger
#                     to avoid double-logging
# ---------------------------------------------------------------------------
CMD ["sh", "-c", \
     "exec uvicorn main:app \
        --host ${INGESTION_API_HOST} \
        --port ${INGESTION_API_PORT} \
        --workers ${INGESTION_API_WORKERS} \
        --proxy-headers \
        --forwarded-allow-ips='*' \
        --no-access-log"]
