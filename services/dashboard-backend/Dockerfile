# =============================================================================
# LogSentinel — Dashboard Backend
# Multi-stage Dockerfile
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
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv ${VIRTUAL_ENV}

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="LogSentinel Team <team@logsentinel.io>" \
      org.opencontainers.image.title="LogSentinel Dashboard Backend" \
      org.opencontainers.image.description="FastAPI service providing dashboard query API" \
      org.opencontainers.image.version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    SERVICE_NAME="dashboard-backend" \
    ENVIRONMENT="production" \
    LOG_LEVEL="INFO" \
    DASHBOARD_API_HOST="0.0.0.0" \
    DASHBOARD_API_PORT="8002" \
    DASHBOARD_API_WORKERS="2"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

COPY --from=builder /opt/venv /opt/venv

RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser

WORKDIR /app
COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 8002

HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=20s \
    --retries=3 \
    CMD curl -f http://localhost:${DASHBOARD_API_PORT}/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["sh", "-c", \
     "exec uvicorn main:app \
        --host ${DASHBOARD_API_HOST} \
        --port ${DASHBOARD_API_PORT} \
        --workers ${DASHBOARD_API_WORKERS} \
        --proxy-headers \
        --forwarded-allow-ips='*' \
        --no-access-log"]
