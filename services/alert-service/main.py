"""
LogSentinel — Alert Service
============================
Kafka consumer service that:
  1. Consumes anomaly alerts from the 'anomaly-alerts' Kafka topic
  2. Deduplicates alerts using Redis (TTL-based suppression)
  3. Sends Slack webhook notifications
  4. Sends Email notifications via SMTP
  5. Persists all alerts (including duplicates) to PostgreSQL

Flow:
  Kafka[anomaly-alerts] → deduplicate (Redis) → notify (Slack + Email) → persist (PostgreSQL)
"""

import asyncio
import signal
import sys

from app.alerter import AlertRouter
from app.config import settings
from app.database import DatabaseClient
from app.deduplicator import AlertDeduplicator
from app.kafka_consumer import KafkaConsumerClient
from app.logger import get_logger
from app.metrics import (
    ALERTS_DEDUPLICATED,
    ALERTS_PROCESSED,
    ALERTS_SENT,
    PROCESSING_DURATION,
    start_metrics_server,
)
from app.notifiers.email_notifier import EmailNotifier
from app.notifiers.slack_notifier import SlackNotifier

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()


def _handle_shutdown_signal(sig, frame):
    logger.info(
        "Shutdown signal received",
        extra={"signal": signal.Signals(sig).name},
    )
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Alert processing
# ---------------------------------------------------------------------------


async def _process_alert(
    alert: dict,
    deduplicator: "AlertDeduplicator",
    router: "AlertRouter",
    db: "DatabaseClient",
) -> None:
    """
    Process a single anomaly alert:
      1. Check deduplication
      2. Send notifications if unique
      3. Persist to PostgreSQL
    """
    import time

    start = time.perf_counter()

    alert_id = alert.get("alert_id", "unknown")
    log_id = alert.get("log_id", "unknown")
    service = alert.get("service", "unknown")
    level = alert.get("level", "UNKNOWN")
    score = alert.get("anomaly_score", 0.0)

    logger.info(
        "Processing anomaly alert",
        extra={
            "alert_id": alert_id,
            "log_id": log_id,
            "service": service,
            "level": level,
            "anomaly_score": score,
        },
    )

    # --- Deduplication ---
    is_duplicate = await deduplicator.is_duplicate(alert)
    alert["deduplicated"] = is_duplicate
    alert["notification_sent"] = False
    alert["notification_channels"] = []

    if is_duplicate:
        ALERTS_DEDUPLICATED.inc()
        logger.info(
            "Alert is a duplicate — suppressing notifications",
            extra={"alert_id": alert_id, "service": service},
        )
    else:
        # Mark as seen in Redis
        await deduplicator.mark_seen(alert)

        # --- Send notifications ---
        channels = await router.send(alert)
        alert["notification_sent"] = len(channels) > 0
        alert["notification_channels"] = channels

        for channel in channels:
            ALERTS_SENT.labels(channel=channel).inc()

    # --- Persist to PostgreSQL ---
    try:
        await db.save_alert(alert)
    except Exception as exc:
        logger.error(
            "Failed to persist alert to PostgreSQL",
            extra={"alert_id": alert_id, "error": str(exc)},
        )

    duration = time.perf_counter() - start
    PROCESSING_DURATION.observe(duration)
    ALERTS_PROCESSED.inc()

    logger.info(
        "Alert processing complete",
        extra={
            "alert_id": alert_id,
            "service": service,
            "is_duplicate": is_duplicate,
            "notification_sent": alert["notification_sent"],
            "channels": alert["notification_channels"],
            "duration_ms": round(duration * 1000, 2),
        },
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def run_alert_service():
    """
    Main async entry point.
    Initialises all clients and runs the Kafka consume loop.
    """
    logger.info(
        "Starting Alert Service",
        extra={
            "service": settings.SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
            "kafka_bootstrap": settings.KAFKA_BOOTSTRAP_SERVERS,
            "consume_topic": settings.KAFKA_TOPIC_ANOMALY_ALERTS,
            "slack_enabled": settings.SLACK_ENABLED,
            "smtp_enabled": settings.SMTP_ENABLED,
        },
    )

    # --- Initialise clients ---
    consumer = KafkaConsumerClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_ANOMALY_ALERTS,
        group_id=settings.KAFKA_CONSUMER_GROUP,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
    )

    deduplicator = AlertDeduplicator(
        redis_url=settings.REDIS_URL,
        ttl_seconds=settings.ALERT_DEDUP_TTL_SECONDS,
    )

    slack_notifier = SlackNotifier(
        webhook_url=settings.SLACK_WEBHOOK_URL,
        channel=settings.SLACK_CHANNEL,
        username=settings.SLACK_USERNAME,
        icon_emoji=settings.SLACK_ICON_EMOJI,
        enabled=settings.SLACK_ENABLED,
        max_retries=settings.ALERT_MAX_RETRIES,
        retry_backoff_seconds=settings.ALERT_RETRY_BACKOFF_SECONDS,
    )

    email_notifier = EmailNotifier(
        smtp_host=settings.SMTP_HOST,
        smtp_port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
        from_email=settings.SMTP_FROM_EMAIL,
        from_name=settings.SMTP_FROM_NAME,
        to_emails=settings.smtp_to_emails_list,
        use_tls=settings.SMTP_USE_TLS,
        enabled=settings.SMTP_ENABLED,
        max_retries=settings.ALERT_MAX_RETRIES,
        retry_backoff_seconds=settings.ALERT_RETRY_BACKOFF_SECONDS,
    )

    router = AlertRouter(
        notifiers=[slack_notifier, email_notifier],
    )

    db = DatabaseClient(
        database_url=settings.DATABASE_URL,
    )

    # --- Start all clients ---
    try:
        await consumer.start()
        logger.info("Kafka consumer started")

        await deduplicator.start()
        logger.info("Deduplicator (Redis) connected")

        await db.start()
        logger.info("Database (PostgreSQL) connected")

        await db.ensure_tables()
        logger.info("Database tables verified/created")

    except Exception as exc:
        logger.error(
            "Failed to initialise one or more clients — aborting",
            extra={"error": str(exc)},
            exc_info=True,
        )
        await _cleanup(consumer, deduplicator, db)
        sys.exit(1)

    logger.info("Alert Service is running — consuming from anomaly-alerts")

    # --- Main consume loop ---
    try:
        async for alert_message in consumer.consume(shutdown_event=_shutdown_event):
            await _process_alert(
                alert=alert_message,
                deduplicator=deduplicator,
                router=router,
                db=db,
            )
    except Exception as exc:
        logger.error(
            "Fatal error in consumer loop",
            extra={"error": str(exc)},
            exc_info=True,
        )
    finally:
        logger.info("Consumer loop exited — cleaning up")
        await _cleanup(consumer, deduplicator, db)

    logger.info("Alert Service stopped cleanly")


async def _cleanup(consumer, deduplicator, db) -> None:
    """Shut down all clients in reverse initialisation order."""
    for name, client in [
        ("database", db),
        ("deduplicator", deduplicator),
        ("kafka_consumer", consumer),
    ]:
        try:
            if client is not None and hasattr(client, "stop"):
                await client.stop()
                logger.info(f"{name} stopped")
        except Exception as exc:
            logger.error(f"Error stopping {name}", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Configure signal handlers and launch the async event loop."""
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    # Start background Prometheus metrics HTTP server on port 9103
    try:
        start_metrics_server(port=settings.METRICS_PORT)
        logger.info(
            "Prometheus metrics server started",
            extra={"port": settings.METRICS_PORT},
        )
    except Exception as exc:
        logger.warning(
            "Failed to start metrics server — metrics will not be scraped",
            extra={"error": str(exc)},
        )

    logger.info(
        "Launching Alert Service event loop",
        extra={"python_version": sys.version.split()[0]},
    )

    try:
        asyncio.run(run_alert_service())
    except KeyboardInterrupt:
        logger.info("Alert Service stopped via keyboard interrupt")
    except Exception as exc:
        logger.critical(
            "Alert Service crashed with unhandled exception",
            extra={"error": str(exc)},
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
