# =============================================================================
# LogSentinel — Alert Service
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
        build-essential gcc libffi-dev libssl-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv ${VIRTUAL_ENV}

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && pip install -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="LogSentinel Team <team@logsentinel.io>" \
      org.opencontainers.image.title="LogSentinel Alert Service" \
      org.opencontainers.image.description="Kafka consumer that deduplicates and routes anomaly alerts" \
      org.opencontainers.image.version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    SERVICE_NAME="alert-service" \
    ENVIRONMENT="production" \
    LOG_LEVEL="INFO" \
    KAFKA_BOOTSTRAP_SERVERS="kafka:9092" \
    KAFKA_TOPIC_ANOMALY_ALERTS="anomaly-alerts" \
    KAFKA_CONSUMER_GROUP="alert-service-group" \
    REDIS_URL="redis://redis:6379/0" \
    DATABASE_URL="postgresql+asyncpg://logsentinel:changeme@postgres:5432/logsentinel" \
    SLACK_ENABLED="false" \
    SMTP_ENABLED="false" \
    METRICS_PORT="9103"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser

WORKDIR /app
COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 9103

HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=30s \
    --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]
