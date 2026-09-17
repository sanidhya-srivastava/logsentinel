"""
LogSentinel — Log Processor
============================
Kafka consumer service that reads from the 'raw-logs' topic,
cleans and structures log data, extracts ML features,
indexes logs into Elasticsearch, and publishes to 'processed-logs'.

Flow:
  Kafka[raw-logs] → parse → feature extraction → Elasticsearch + Kafka[processed-logs]
"""

import asyncio
import signal
import sys

from app.config import settings
from app.elasticsearch_client import ElasticsearchClient
from app.feature_extractor import FeatureExtractor
from app.kafka_consumer import KafkaConsumerClient
from app.kafka_producer import KafkaProducerClient
from app.logger import get_logger
from app.metrics import (
    ES_INDEX_ERRORS,
    ES_INDEX_SUCCESS,
    LOGS_FAILED_TOTAL,
    LOGS_PROCESSED_TOTAL,
    PROCESSING_DURATION,
)
from app.processor import LogProcessor

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown flag
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()


def _handle_shutdown_signal(sig, frame):
    """Handle SIGTERM / SIGINT for graceful shutdown."""
    logger.info(
        "Shutdown signal received",
        extra={"signal": signal.Signals(sig).name},
    )
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Main consumer loop
# ---------------------------------------------------------------------------


async def run_processor():
    """
    Main async entry point.
    Initialises all clients and runs the consume → process → publish loop.
    """
    logger.info(
        "Starting Log Processor",
        extra={
            "service": settings.SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
            "kafka_bootstrap": settings.KAFKA_BOOTSTRAP_SERVERS,
            "consume_topic": settings.KAFKA_TOPIC_RAW_LOGS,
            "publish_topic": settings.KAFKA_TOPIC_PROCESSED_LOGS,
            "es_host": settings.ELASTICSEARCH_HOST,
        },
    )

    # --- Initialise clients ---
    consumer = KafkaConsumerClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_RAW_LOGS,
        group_id=settings.KAFKA_CONSUMER_GROUP,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
    )

    producer = KafkaProducerClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_PROCESSED_LOGS,
    )

    es_client = ElasticsearchClient(
        host=settings.ELASTICSEARCH_HOST,
        port=settings.ELASTICSEARCH_PORT,
        scheme=settings.ELASTICSEARCH_SCHEME,
        username=settings.ELASTICSEARCH_USERNAME,
        password=settings.ELASTICSEARCH_PASSWORD,
    )

    feature_extractor = FeatureExtractor(
        redis_url=settings.REDIS_URL,
    )

    processor = LogProcessor(
        feature_extractor=feature_extractor,
    )

    # --- Start all clients ---
    try:
        await producer.start()
        logger.info("Kafka producer started")

        await consumer.start()
        logger.info(
            "Kafka consumer started", extra={"topic": settings.KAFKA_TOPIC_RAW_LOGS}
        )

        await es_client.start()
        logger.info("Elasticsearch client connected")

        await feature_extractor.start()
        logger.info("Feature extractor initialised (Redis connected)")

        # Ensure Elasticsearch index template exists
        await es_client.ensure_index_template()
        logger.info("Elasticsearch index template verified")

    except Exception as exc:
        logger.error(
            "Failed to initialise one or more clients — aborting startup",
            extra={"error": str(exc)},
            exc_info=True,
        )
        # Attempt cleanup before exit
        await _cleanup(consumer, producer, es_client, feature_extractor)
        sys.exit(1)

    logger.info("Log Processor is running — consuming messages")

    # --- Main processing loop ---
    try:
        async for raw_message in consumer.consume(shutdown_event=_shutdown_event):
            await _process_message(
                raw_message=raw_message,
                processor=processor,
                producer=producer,
                es_client=es_client,
            )
    except Exception as exc:
        logger.error(
            "Fatal error in consumer loop",
            extra={"error": str(exc)},
            exc_info=True,
        )
    finally:
        logger.info("Consumer loop exited — cleaning up")
        await _cleanup(consumer, producer, es_client, feature_extractor)

    logger.info("Log Processor stopped cleanly")


async def _process_message(
    raw_message: dict,
    processor: "LogProcessor",
    producer: "KafkaProducerClient",
    es_client: "ElasticsearchClient",
) -> None:
    """
    Process a single raw log message from Kafka:
      1. Parse and validate the raw log dict
      2. Normalise log level and extract features
      3. Index into Elasticsearch
      4. Publish processed log to Kafka 'processed-logs'

    Errors are caught and logged — the consumer offset is still committed
    so malformed messages do not block the pipeline.
    """
    import time

    start = time.perf_counter()
    log_id = raw_message.get("log_id", "unknown")

    try:
        logger.debug(
            "Processing log message",
            extra={"log_id": log_id, "service": raw_message.get("service")},
        )

        # --- Step 1: Process (normalise + extract features) ---
        processed = await processor.process(raw_message)

        # --- Step 2: Index into Elasticsearch ---
        try:
            await es_client.index_log(processed)
            ES_INDEX_SUCCESS.inc()
        except Exception as es_exc:
            ES_INDEX_ERRORS.inc()
            logger.error(
                "Failed to index log in Elasticsearch — continuing pipeline",
                extra={"log_id": log_id, "error": str(es_exc)},
            )
            # Non-fatal: continue to Kafka publish even if ES indexing fails

        # --- Step 3: Publish to processed-logs topic ---
        await producer.send(processed)

        duration = time.perf_counter() - start
        PROCESSING_DURATION.observe(duration)
        LOGS_PROCESSED_TOTAL.labels(
            service=processed.get("service", "unknown"),
            level=processed.get("level", "UNKNOWN"),
        ).inc()

        logger.info(
            "Log message processed successfully",
            extra={
                "log_id": log_id,
                "service": processed.get("service"),
                "level": processed.get("level"),
                "duration_ms": round(duration * 1000, 2),
            },
        )

    except Exception as exc:
        duration = time.perf_counter() - start
        LOGS_FAILED_TOTAL.labels(reason=type(exc).__name__).inc()

        logger.error(
            "Failed to process log message — skipping",
            extra={
                "log_id": log_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "duration_ms": round(duration * 1000, 2),
            },
            exc_info=True,
        )
        # Message is intentionally skipped — offset committed by consumer


async def _cleanup(consumer, producer, es_client, feature_extractor) -> None:
    """Gracefully shut down all clients in reverse initialisation order."""
    logger.info("Shutting down clients")

    for name, client in [
        ("feature_extractor", feature_extractor),
        ("elasticsearch", es_client),
        ("kafka_producer", producer),
        ("kafka_consumer", consumer),
    ]:
        try:
            if hasattr(client, "stop"):
                await client.stop()
                logger.info(f"{name} stopped")
        except Exception as exc:
            logger.error(f"Error stopping {name}", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Configure signal handlers and launch the async event loop."""
    # Register shutdown signal handlers
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    logger.info(
        "Launching Log Processor event loop",
        extra={"python_version": sys.version.split()[0]},
    )

    try:
        asyncio.run(run_processor())
    except KeyboardInterrupt:
        logger.info("Log Processor stopped via keyboard interrupt")
    except Exception as exc:
        logger.critical(
            "Log Processor crashed with unhandled exception",
            extra={"error": str(exc)},
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
