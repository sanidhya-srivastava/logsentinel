"""
LogSentinel — ML Engine
========================
FastAPI application that:
  1. Loads a pre-trained Isolation Forest model on startup
  2. Consumes from Kafka 'processed-logs' topic and scores each entry
  3. Publishes detected anomalies to Kafka 'anomaly-alerts' topic
  4. Exposes POST /predict and POST /predict/batch for on-demand inference
  5. Exposes GET /model/status for model health metadata
  6. Exposes GET /metrics for Prometheus scraping

Flow:
  Kafka[processed-logs] → Isolation Forest → score → if anomaly → Kafka[anomaly-alerts]
  POST /predict          → Isolation Forest → score → HTTP response
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.kafka_consumer import KafkaConsumerClient
from app.kafka_producer import KafkaProducerClient
from app.logger import get_logger
from app.metrics import (
    ANOMALIES_DETECTED,
    INFERENCE_DURATION,
    KAFKA_CONSUME_ERRORS,
    KAFKA_PUBLISH_ERRORS,
    KAFKA_PUBLISH_SUCCESS,
    MODEL_LOADED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from app.model_manager import ModelManager
from app.schemas import (
    BatchPredictRequest,
    BatchPredictResponse,
    FeatureVector,
    ModelStatusResponse,
    PredictResponse,
)
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
model_manager: ModelManager | None = None
kafka_consumer: KafkaConsumerClient | None = None
kafka_producer: KafkaProducerClient | None = None
_consumer_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global model_manager, kafka_consumer, kafka_producer, _consumer_task

    logger.info(
        "Starting ML Engine",
        extra={
            "service": settings.SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
            "model_path": settings.ML_MODEL_PATH,
        },
    )

    # --- Load ML model ---
    model_manager = ModelManager(
        model_path=settings.ML_MODEL_PATH,
        scaler_path=settings.ML_SCALER_PATH,
    )
    try:
        model_manager.load()
        MODEL_LOADED.set(1)
        logger.info(
            "Isolation Forest model loaded",
            extra={
                "model_path": settings.ML_MODEL_PATH,
                "n_estimators": model_manager.n_estimators,
                "contamination": model_manager.contamination,
            },
        )
    except Exception as exc:
        MODEL_LOADED.set(0)
        logger.error(
            "Failed to load ML model — predictions will be unavailable",
            extra={"error": str(exc)},
            exc_info=True,
        )

    # --- Start Kafka producer ---
    kafka_producer = KafkaProducerClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_ANOMALY_ALERTS,
    )
    try:
        await kafka_producer.start()
        logger.info("Kafka producer connected")
    except Exception as exc:
        logger.error("Failed to start Kafka producer", extra={"error": str(exc)})

    # --- Start Kafka consumer ---
    kafka_consumer = KafkaConsumerClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_PROCESSED_LOGS,
        group_id=settings.KAFKA_CONSUMER_GROUP,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
    )
    try:
        await kafka_consumer.start()
        logger.info(
            "Kafka consumer connected",
            extra={"topic": settings.KAFKA_TOPIC_PROCESSED_LOGS},
        )
        # Launch background consumer task
        _consumer_task = asyncio.create_task(
            _run_consumer_loop(),
            name="ml-engine-consumer",
        )
        logger.info("Background Kafka consumer task started")
    except Exception as exc:
        logger.error("Failed to start Kafka consumer", extra={"error": str(exc)})

    yield

    # --- Shutdown ---
    logger.info("Shutting down ML Engine")

    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await asyncio.wait_for(_consumer_task, timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("Consumer task stopped")

    for name, client in [
        ("kafka_consumer", kafka_consumer),
        ("kafka_producer", kafka_producer),
    ]:
        if client is not None:
            try:
                await client.stop()
                logger.info(f"{name} stopped")
            except Exception as exc:
                logger.error(f"Error stopping {name}", extra={"error": str(exc)})

    logger.info("ML Engine shut down cleanly")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="LogSentinel — ML Engine",
    description=(
        "Isolation Forest anomaly detection service. "
        "Consumes processed log events from Kafka, scores them for anomalies, "
        "and publishes detected anomalies to the anomaly-alerts topic. "
        "Also provides a synchronous REST inference API."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
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
# Mount Prometheus metrics
# ---------------------------------------------------------------------------
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ---------------------------------------------------------------------------
# Background Kafka consumer loop
# ---------------------------------------------------------------------------
async def _run_consumer_loop() -> None:
    """
    Background task: consume processed logs from Kafka, run inference,
    publish anomalies to anomaly-alerts topic.
    """
    logger.info("Kafka consumer loop started")
    shutdown = asyncio.Event()

    try:
        async for message in kafka_consumer.consume(shutdown_event=shutdown):
            await _score_and_route(message)
    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled — shutting down")
        shutdown.set()
    except Exception as exc:
        logger.error(
            "Fatal error in Kafka consumer loop",
            extra={"error": str(exc)},
            exc_info=True,
        )
    finally:
        logger.info("Kafka consumer loop exited")


async def _score_and_route(processed_log: dict[str, Any]) -> None:
    """
    Score a single processed log dict using the Isolation Forest model.
    If anomaly (-1), publish to anomaly-alerts Kafka topic.
    """
    log_id = processed_log.get("log_id", "unknown")

    if model_manager is None or not model_manager.is_loaded:
        logger.warning(
            "Model not loaded — skipping inference",
            extra={"log_id": log_id},
        )
        KAFKA_CONSUME_ERRORS.inc()
        return

    try:
        features_dict = processed_log.get("features", {})
        if not features_dict:
            logger.warning(
                "Processed log has no feature vector — skipping",
                extra={"log_id": log_id},
            )
            return

        feature_vector = FeatureVector(
            hour_of_day=features_dict.get("hour_of_day", 0),
            response_time_ms=features_dict.get("response_time_ms", 0.0),
            error_code=features_dict.get("error_code", 0),
            log_level_encoded=features_dict.get("log_level_encoded", 1),
            request_count_last_60s=features_dict.get("request_count_last_60s", 0),
            service_id_encoded=features_dict.get("service_id_encoded", 0),
        )

        start = time.perf_counter()
        prediction = model_manager.predict(feature_vector)
        duration = time.perf_counter() - start

        INFERENCE_DURATION.observe(duration)

        logger.debug(
            "Inference result",
            extra={
                "log_id": log_id,
                "prediction": prediction.prediction,
                "score": prediction.anomaly_score,
                "is_anomaly": prediction.is_anomaly,
                "duration_ms": round(duration * 1000, 2),
            },
        )

        if prediction.is_anomaly:
            ANOMALIES_DETECTED.labels(
                service=processed_log.get("service", "unknown"),
                level=processed_log.get("level", "UNKNOWN"),
            ).inc()

            alert = _build_anomaly_alert(processed_log, prediction)

            if kafka_producer and kafka_producer.is_connected:
                try:
                    await kafka_producer.send(alert)
                    KAFKA_PUBLISH_SUCCESS.inc()
                    logger.info(
                        "Anomaly published to anomaly-alerts",
                        extra={
                            "alert_id": alert["alert_id"],
                            "log_id": log_id,
                            "service": processed_log.get("service"),
                            "anomaly_score": prediction.anomaly_score,
                        },
                    )
                except Exception as exc:
                    KAFKA_PUBLISH_ERRORS.inc()
                    logger.error(
                        "Failed to publish anomaly alert",
                        extra={"log_id": log_id, "error": str(exc)},
                    )

    except Exception as exc:
        KAFKA_CONSUME_ERRORS.inc()
        logger.error(
            "Error during ML inference on Kafka message",
            extra={"log_id": log_id, "error": str(exc)},
            exc_info=True,
        )


def _build_anomaly_alert(
    processed_log: dict[str, Any],
    prediction: Any,
) -> dict[str, Any]:
    """Build the anomaly alert payload to publish to Kafka."""
    return {
        "alert_id": str(uuid.uuid4()),
        "log_id": processed_log.get("log_id"),
        "detected_at": datetime.now(timezone.utc).isoformat(),
        # Original log fields
        "service": processed_log.get("service"),
        "level": processed_log.get("level"),
        "message": processed_log.get("message"),
        "host": processed_log.get("host"),
        "timestamp": processed_log.get("timestamp"),
        "response_time_ms": processed_log.get("response_time_ms"),
        "error_code": processed_log.get("error_code"),
        # ML inference results
        "anomaly_score": prediction.anomaly_score,
        "prediction": prediction.prediction,
        "is_anomaly": prediction.is_anomaly,
        # Feature vector snapshot
        "features": processed_log.get("features", {}),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", tags=["Meta"])
async def root():
    return {
        "service": "LogSentinel ML Engine",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


@app.get("/health", tags=["Meta"])
async def health():
    """Liveness and readiness probe."""
    model_ok = model_manager is not None and model_manager.is_loaded
    kafka_consumer_ok = kafka_consumer is not None and kafka_consumer.is_connected
    kafka_producer_ok = kafka_producer is not None and kafka_producer.is_connected

    all_ok = model_ok and kafka_consumer_ok and kafka_producer_ok

    payload = {
        "status": "healthy" if all_ok else "degraded",
        "service": settings.SERVICE_NAME,
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "model": "loaded" if model_ok else "not_loaded",
            "kafka_consumer": "connected" if kafka_consumer_ok else "disconnected",
            "kafka_producer": "connected" if kafka_producer_ok else "disconnected",
        },
    }

    status_code = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload)


@app.get(
    "/model/status",
    response_model=ModelStatusResponse,
    summary="Get ML model metadata and health",
    tags=["Model"],
)
async def model_status():
    """Return metadata about the currently loaded Isolation Forest model."""
    if model_manager is None or not model_manager.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML model is not loaded. Check service logs for details.",
        )

    return ModelStatusResponse(
        status="loaded",
        model_type="IsolationForest",
        n_estimators=model_manager.n_estimators,
        contamination=model_manager.contamination,
        n_features=model_manager.n_features,
        trained_at=model_manager.trained_at,
        model_path=settings.ML_MODEL_PATH,
        scaler_path=settings.ML_SCALER_PATH,
        anomaly_threshold=settings.ML_ANOMALY_SCORE_THRESHOLD,
    )


@app.post(
    "/predict",
    response_model=PredictResponse,
    summary="Run anomaly detection on a single feature vector",
    tags=["Inference"],
    status_code=status.HTTP_200_OK,
)
async def predict(feature_vector: FeatureVector):
    """
    Perform synchronous anomaly detection on a single feature vector.

    Returns the raw anomaly score and a boolean classification.
    Score < 0 indicates an anomaly; the lower the score, the more anomalous.
    """
    if model_manager is None or not model_manager.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML model is not loaded.",
        )

    try:
        start = time.perf_counter()
        result = model_manager.predict(feature_vector)
        duration = time.perf_counter() - start

        INFERENCE_DURATION.observe(duration)

        if result.is_anomaly:
            ANOMALIES_DETECTED.labels(service="api-predict", level="UNKNOWN").inc()

        logger.info(
            "Synchronous prediction complete",
            extra={
                "prediction": result.prediction,
                "score": result.anomaly_score,
                "is_anomaly": result.is_anomaly,
                "duration_ms": round(duration * 1000, 2),
            },
        )

        return result

    except Exception as exc:
        logger.error(
            "Prediction error",
            extra={"error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(exc)}",
        ) from exc


@app.post(
    "/predict/batch",
    response_model=BatchPredictResponse,
    summary="Run anomaly detection on a batch of feature vectors",
    tags=["Inference"],
    status_code=status.HTTP_200_OK,
)
async def predict_batch(request: BatchPredictRequest):
    """
    Perform batch anomaly detection on up to 500 feature vectors.

    Results are returned in the same order as the input list.
    """
    if model_manager is None or not model_manager.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML model is not loaded.",
        )

    try:
        start = time.perf_counter()
        results = model_manager.predict_batch(request.features)
        duration = time.perf_counter() - start

        INFERENCE_DURATION.observe(duration)

        anomaly_count = sum(1 for r in results if r.is_anomaly)
        if anomaly_count > 0:
            ANOMALIES_DETECTED.labels(service="api-batch", level="UNKNOWN").inc(
                anomaly_count
            )

        logger.info(
            "Batch prediction complete",
            extra={
                "total": len(results),
                "anomalies": anomaly_count,
                "duration_ms": round(duration * 1000, 2),
            },
        )

        return BatchPredictResponse(
            total=len(results),
            anomaly_count=anomaly_count,
            results=results,
        )

    except Exception as exc:
        logger.error(
            "Batch prediction error",
            extra={"error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch prediction failed: {str(exc)}",
        ) from exc


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        extra={"path": request.url.path, "error": str(exc)},
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred."},
    )
