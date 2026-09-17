"""
LogSentinel — Log Ingestion API
================================
FastAPI application that receives log entries via REST API,
validates them with Pydantic, and publishes to Kafka.

Endpoints:
  POST /ingest        — ingest a single log entry
  POST /ingest/batch  — ingest up to 100 log entries
  GET  /health        — liveness / readiness probe
  GET  /metrics       — Prometheus metrics
  GET  /              — API info
"""

import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from app.config import settings
from app.kafka_producer import KafkaProducerClient
from app.logger import get_logger
from app.metrics import (
    BATCH_SIZE_HISTOGRAM,
    KAFKA_PUBLISH_ERRORS,
    KAFKA_PUBLISH_SUCCESS,
    LOGS_INGESTED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from app.models import BatchIngestRequest, BatchIngestResponse, IngestResponse, LogEntry
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Kafka producer singleton (shared across requests)
# ---------------------------------------------------------------------------
kafka_producer: KafkaProducerClient | None = None


# ---------------------------------------------------------------------------
# Lifespan — startup & shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: start Kafka producer on startup, close on shutdown."""
    global kafka_producer

    logger.info(
        "Starting Log Ingestion API",
        extra={
            "service": settings.SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
            "kafka_bootstrap": settings.KAFKA_BOOTSTRAP_SERVERS,
        },
    )

    # --- Startup ---
    try:
        kafka_producer = KafkaProducerClient(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            topic=settings.KAFKA_TOPIC_RAW_LOGS,
        )
        await kafka_producer.start()
        logger.info(
            "Kafka producer connected",
            extra={"topic": settings.KAFKA_TOPIC_RAW_LOGS},
        )
    except Exception as exc:
        logger.error("Failed to connect Kafka producer on startup", exc_info=exc)
        # Allow service to start in degraded mode; health check will surface this.

    yield

    # --- Shutdown ---
    logger.info("Shutting down Log Ingestion API")
    if kafka_producer:
        try:
            await kafka_producer.stop()
            logger.info("Kafka producer stopped cleanly")
        except Exception as exc:
            logger.error("Error stopping Kafka producer", exc_info=exc)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="LogSentinel — Log Ingestion API",
    description=(
        "Receives structured log entries from application services, "
        "validates them, and publishes to Apache Kafka for downstream processing."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record request count and latency for every HTTP call."""
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(duration)

    return response


# ---------------------------------------------------------------------------
# Mount Prometheus metrics endpoint
# ---------------------------------------------------------------------------
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _enrich_log_entry(entry: LogEntry) -> dict:
    """
    Enrich a validated LogEntry with server-side fields:
      - log_id   : UUID v4 unique identifier
      - ingested_at: UTC timestamp of ingestion
    Returns a plain dict ready for JSON serialisation and Kafka publishing.
    """
    data = entry.model_dump(mode="json")
    data["log_id"] = str(uuid.uuid4())
    data["ingested_at"] = datetime.now(timezone.utc).isoformat()
    return data


async def _publish_to_kafka(payload: dict) -> None:
    """
    Publish a single enriched log payload to Kafka.
    Raises HTTPException(503) if Kafka is unavailable.
    """
    if kafka_producer is None or not kafka_producer.is_connected:
        KAFKA_PUBLISH_ERRORS.inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kafka producer is not available. Please retry shortly.",
        )
    try:
        await kafka_producer.send(payload)
        KAFKA_PUBLISH_SUCCESS.inc()
    except Exception as exc:
        KAFKA_PUBLISH_ERRORS.inc()
        logger.error(
            "Failed to publish log to Kafka",
            extra={"log_id": payload.get("log_id"), "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to publish log to Kafka. Please retry shortly.",
        ) from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get(
    "/",
    summary="API Info",
    tags=["Meta"],
    response_class=JSONResponse,
)
async def root():
    """Return basic API information."""
    return {
        "service": "LogSentinel Log Ingestion API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


@app.get(
    "/health",
    summary="Health Check",
    tags=["Meta"],
    response_class=JSONResponse,
)
async def health():
    """
    Liveness and readiness probe.
    Returns 200 when the service is healthy.
    Returns 503 when Kafka is disconnected.
    """
    kafka_ok = kafka_producer is not None and kafka_producer.is_connected

    payload = {
        "status": "healthy" if kafka_ok else "degraded",
        "service": settings.SERVICE_NAME,
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "kafka": "connected" if kafka_ok else "disconnected",
        },
    }

    if not kafka_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)


@app.post(
    "/ingest",
    summary="Ingest a single log entry",
    tags=["Ingestion"],
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_single(entry: LogEntry):
    """
    Accept a single structured log entry, enrich it with a unique ID and
    ingestion timestamp, and publish it to the Kafka `raw-logs` topic.

    **Request body:** JSON conforming to the `LogEntry` schema.

    **Response:** 202 Accepted with the assigned `log_id`.

    **Errors:**
    - 422 Unprocessable Entity — validation failed (missing/invalid fields)
    - 503 Service Unavailable  — Kafka is unreachable
    """
    enriched = _enrich_log_entry(entry)
    log_id = enriched["log_id"]

    logger.debug(
        "Ingesting single log entry",
        extra={
            "log_id": log_id,
            "service": enriched.get("service"),
            "level": enriched.get("level"),
        },
    )

    await _publish_to_kafka(enriched)
    LOGS_INGESTED.labels(service=entry.service, level=entry.level.value).inc()

    logger.info(
        "Log entry published to Kafka",
        extra={
            "log_id": log_id,
            "service": enriched.get("service"),
            "level": enriched.get("level"),
            "topic": settings.KAFKA_TOPIC_RAW_LOGS,
        },
    )

    return IngestResponse(
        log_id=log_id,
        status="accepted",
        message="Log entry accepted and queued for processing.",
        ingested_at=enriched["ingested_at"],
    )


@app.post(
    "/ingest/batch",
    summary="Ingest a batch of log entries (max 100)",
    tags=["Ingestion"],
    response_model=BatchIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_batch(request: BatchIngestRequest):
    """
    Accept a batch of up to 100 structured log entries and publish each
    to the Kafka `raw-logs` topic.

    **Request body:** JSON with a `logs` array (1–100 `LogEntry` objects).

    **Response:** 202 Accepted with counts of accepted and rejected entries.

    **Errors:**
    - 422 Unprocessable Entity — validation failed
    - 503 Service Unavailable  — Kafka is unreachable
    """
    entries = request.logs
    total = len(entries)

    BATCH_SIZE_HISTOGRAM.observe(total)

    logger.info(
        "Ingesting batch of log entries",
        extra={"batch_size": total},
    )

    accepted_ids: list[str] = []
    rejected: list[dict] = []

    for i, entry in enumerate(entries):
        enriched = _enrich_log_entry(entry)
        log_id = enriched["log_id"]
        try:
            await _publish_to_kafka(enriched)
            LOGS_INGESTED.labels(service=entry.service, level=entry.level.value).inc()
            accepted_ids.append(log_id)
        except HTTPException as exc:
            # Kafka unavailable — fail-fast for the rest of the batch too
            rejected.append({"index": i, "reason": exc.detail})
            logger.warning(
                "Batch entry rejected",
                extra={"index": i, "log_id": log_id, "reason": exc.detail},
            )
            # If Kafka is down, no point trying remaining entries
            for j in range(i + 1, total):
                rejected.append({"index": j, "reason": "Kafka unavailable — skipped"})
            break

    logger.info(
        "Batch ingest complete",
        extra={
            "total": total,
            "accepted": len(accepted_ids),
            "rejected": len(rejected),
        },
    )

    return BatchIngestResponse(
        accepted=len(accepted_ids),
        rejected=len(rejected),
        log_ids=accepted_ids,
        rejected_details=rejected if rejected else None,
        message=f"Batch processed: {len(accepted_ids)} accepted, {len(rejected)} rejected.",
    )


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all handler to prevent stack traces leaking to clients."""
    logger.error(
        "Unhandled exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error": str(exc),
        },
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred. Please contact support.",
            "path": request.url.path,
        },
    )
