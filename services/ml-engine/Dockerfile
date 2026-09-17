# =============================================================================
# LogSentinel — ML Engine
# Multi-stage Dockerfile
# =============================================================================
# Stage 1 (builder): install Python dependencies into a venv
# Stage 2 (runtime): copy venv + source + model files — no build tooling
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 — Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

LABEL stage="builder"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# System build dependencies required to compile some ML packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
        libopenblas-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create the virtual environment
RUN python -m venv ${VIRTUAL_ENV}

WORKDIR /build

# Copy requirements first — maximises Docker layer cache reuse
COPY requirements.txt .

# Install all Python dependencies (scikit-learn, joblib, aiokafka, fastapi, etc.)
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="LogSentinel Team <team@logsentinel.io>" \
      org.opencontainers.image.title="LogSentinel ML Engine" \
      org.opencontainers.image.description="Isolation Forest anomaly detection API + Kafka consumer" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/your-org/logsentinel"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    # Application defaults — override via docker run -e or K8s ConfigMap/Secret
    SERVICE_NAME="ml-engine" \
    ENVIRONMENT="production" \
    LOG_LEVEL="INFO" \
    ML_ENGINE_HOST="0.0.0.0" \
    ML_ENGINE_PORT="8001" \
    ML_ENGINE_WORKERS="1" \
    KAFKA_BOOTSTRAP_SERVERS="kafka:9092" \
    KAFKA_TOPIC_PROCESSED_LOGS="processed-logs" \
    KAFKA_TOPIC_ANOMALY_ALERTS="anomaly-alerts" \
    KAFKA_CONSUMER_GROUP="ml-engine-group" \
    KAFKA_AUTO_OFFSET_RESET="earliest" \
    ML_MODEL_PATH="/app/models/isolation_forest.joblib" \
    ML_SCALER_PATH="/app/models/scaler.joblib" \
    ML_CONTAMINATION="0.05" \
    ML_ANOMALY_SCORE_THRESHOLD="0.0"

# Minimal runtime system packages only
RUN apt-get update && apt-get install -y --no-install-recommends \
        # curl for health check commands and K8s probes
        curl \
        # ca-certificates for TLS connections (Kafka, HTTPS)
        ca-certificates \
        # libopenblas for numpy/scikit-learn BLAS operations at runtime
        libopenblas0 \
        # tini: proper PID 1 init — handles signal forwarding & zombie reaping
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# ---------------------------------------------------------------------------
# Create a non-root user and group
# Running as root inside a container is a security risk
# ---------------------------------------------------------------------------
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser

# Set working directory
WORKDIR /app

# ---------------------------------------------------------------------------
# Create the models directory and set correct ownership.
# The model files (isolation_forest.joblib, scaler.joblib) are either:
#   - Baked into the image at build time via COPY below (if available), OR
#   - Mounted at runtime via a Kubernetes volume / Docker bind mount.
# Both patterns are supported.
# ---------------------------------------------------------------------------
RUN mkdir -p /app/models && chown -R appuser:appgroup /app/models

# Copy model files if they exist in the build context (ml/models/).
# The COPY --chown flag sets correct ownership in one layer.
# If the files are not present, Docker will skip this step without error
# when using BuildKit (--mount=type=bind) — but for standard builds we
# use a wildcard with a fallback to keep the Dockerfile portable.
COPY --chown=appuser:appgroup --from=builder /opt/venv /opt/venv

# Copy application source code
COPY --chown=appuser:appgroup . .

# Model files (isolation_forest.joblib, scaler.joblib) are mounted at
# runtime via the docker-compose volume or a Kubernetes PVC.
# The directory is already created above — nothing to COPY here.

# ---------------------------------------------------------------------------
# Switch to non-root user
# ---------------------------------------------------------------------------
USER appuser

# ---------------------------------------------------------------------------
# Expose the application port (informational)
# ---------------------------------------------------------------------------
EXPOSE 8001

# ---------------------------------------------------------------------------
# Health check
# Kubernetes also performs its own probes via the Deployment manifest.
# ---------------------------------------------------------------------------
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=30s \
    --retries=3 \
    CMD curl -f http://localhost:${ML_ENGINE_PORT}/health || exit 1

# ---------------------------------------------------------------------------
# Entrypoint — use tini as PID 1 for proper signal handling
# ---------------------------------------------------------------------------
ENTRYPOINT ["/usr/bin/tini", "--"]

# ---------------------------------------------------------------------------
# Default command — start Uvicorn serving the FastAPI app
#
# --host / --port     : bind address from environment variables
# --workers           : number of Uvicorn worker processes
# --proxy-headers     : trust X-Forwarded-* headers from ingress
# --no-access-log     : access logging handled by JSON middleware
# ---------------------------------------------------------------------------
CMD ["sh", "-c", \
     "exec uvicorn main:app \
        --host ${ML_ENGINE_HOST} \
        --port ${ML_ENGINE_PORT} \
        --workers ${ML_ENGINE_WORKERS} \
        --proxy-headers \
        --forwarded-allow-ips='*' \
        --no-access-log"]
