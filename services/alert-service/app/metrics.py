"""
LogSentinel — Alert Service: Prometheus Metrics
================================================
All Prometheus metrics definitions for the Alert Service.

Metrics exposed via a background HTTP server on METRICS_PORT (default: 9103):

  Counters:
    alert_service_alerts_processed_total    — total alerts consumed from Kafka
    alert_service_alerts_sent_total         — alerts sent, labelled by channel
    alert_service_alerts_deduplicated_total — suppressed duplicate alerts
    alert_service_send_errors_total         — notification send failures by channel

  Histograms:
    alert_service_processing_duration_seconds — end-to-end alert processing time

  Gauges:
    alert_service_kafka_consumer_connected — 1 if consumer is up, 0 if down
    alert_service_redis_connected          — 1 if Redis is up, 0 if down
    alert_service_db_connected             — 1 if PostgreSQL is up, 0 if down

Usage:
    from app.metrics import ALERTS_PROCESSED, ALERTS_SENT
    ALERTS_PROCESSED.inc()
    ALERTS_SENT.labels(channel="slack").inc()
"""

import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
_CHANNEL_LABEL = "channel"  # slack / email
_REASON_LABEL = "reason"  # failure reason / exception class

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

ALERTS_PROCESSED = Counter(
    name="alert_service_alerts_processed_total",
    documentation=(
        "Total number of anomaly alert messages consumed from the "
        "Kafka anomaly-alerts topic, regardless of deduplication status."
    ),
)

ALERTS_SENT = Counter(
    name="alert_service_alerts_sent_total",
    documentation=(
        "Total number of alert notifications successfully sent. "
        "Labelled by notification channel (slack, email). "
        "Only counts unique (non-deduplicated) alerts."
    ),
    labelnames=[_CHANNEL_LABEL],
)

ALERTS_DEDUPLICATED = Counter(
    name="alert_service_alerts_deduplicated_total",
    documentation=(
        "Total number of anomaly alerts suppressed by the Redis deduplicator "
        "because an identical alert was already sent within the TTL window. "
        "Deduplicated alerts are still persisted to PostgreSQL."
    ),
)

SEND_ERRORS = Counter(
    name="alert_service_send_errors_total",
    documentation=(
        "Total number of failed notification send attempts after all retries "
        "are exhausted. Labelled by notification channel and error type."
    ),
    labelnames=[_CHANNEL_LABEL, _REASON_LABEL],
)

DB_SAVE_ERRORS = Counter(
    name="alert_service_db_save_errors_total",
    documentation=(
        "Total number of failed PostgreSQL alert persistence operations. "
        "When this counter grows, alerts are being lost from the database."
    ),
)

KAFKA_CONSUME_ERRORS = Counter(
    name="alert_service_kafka_consume_errors_total",
    documentation=(
        "Total number of errors encountered while consuming from the "
        "Kafka anomaly-alerts topic. Includes deserialization failures."
    ),
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

PROCESSING_DURATION = Histogram(
    name="alert_service_processing_duration_seconds",
    documentation=(
        "End-to-end processing time in seconds for a single anomaly alert, "
        "from consumption off Kafka to completion of PostgreSQL persistence. "
        "Includes deduplication check, notification sends, and DB write."
    ),
    buckets=(
        0.005,  # 5ms
        0.010,  # 10ms
        0.025,  # 25ms
        0.050,  # 50ms
        0.100,  # 100ms
        0.250,  # 250ms
        0.500,  # 500ms
        1.0,  # 1s
        2.0,  # 2s
        5.0,  # 5s
        10.0,  # 10s
        30.0,  # 30s  (SMTP can be slow)
    ),
)

NOTIFICATION_DURATION = Histogram(
    name="alert_service_notification_duration_seconds",
    documentation=(
        "Time in seconds taken to send a single notification through a channel. "
        "Labelled by channel. Includes retry attempts."
    ),
    labelnames=[_CHANNEL_LABEL],
    buckets=(
        0.050,  # 50ms
        0.100,  # 100ms
        0.250,  # 250ms
        0.500,  # 500ms
        1.0,  # 1s
        2.0,  # 2s
        5.0,  # 5s
        10.0,  # 10s
        30.0,  # 30s
    ),
)

DEDUP_CHECK_DURATION = Histogram(
    name="alert_service_dedup_check_duration_seconds",
    documentation=(
        "Time in seconds taken for a single Redis deduplication check "
        "(EXISTS + optional SET NX). Measures Redis round-trip latency."
    ),
    buckets=(
        0.0005,  # 0.5ms
        0.001,  # 1ms
        0.002,  # 2ms
        0.005,  # 5ms
        0.010,  # 10ms
        0.025,  # 25ms
        0.050,  # 50ms
        0.100,  # 100ms
    ),
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

KAFKA_CONSUMER_CONNECTED = Gauge(
    name="alert_service_kafka_consumer_connected",
    documentation=(
        "Current connection state of the Kafka consumer "
        "(anomaly-alerts topic). 1 = connected, 0 = disconnected."
    ),
)

REDIS_CONNECTED = Gauge(
    name="alert_service_redis_connected",
    documentation=(
        "Current connection state of the Redis client used for "
        "alert deduplication. 1 = connected, 0 = disconnected."
    ),
)

DB_CONNECTED = Gauge(
    name="alert_service_db_connected",
    documentation=(
        "Current connection state of the PostgreSQL client used for "
        "alert persistence. 1 = connected, 0 = disconnected."
    ),
)

DEDUP_SUPPRESSION_RATE = Gauge(
    name="alert_service_dedup_suppression_rate",
    documentation=(
        "Rolling fraction of alerts that were suppressed as duplicates "
        "over the last processing batch. 0.0 = no suppression, "
        "1.0 = all alerts were duplicates."
    ),
)

# ---------------------------------------------------------------------------
# Initialise gauges to 0 (disconnected) at module load time
# ---------------------------------------------------------------------------
KAFKA_CONSUMER_CONNECTED.set(0)
REDIS_CONNECTED.set(0)
DB_CONNECTED.set(0)
DEDUP_SUPPRESSION_RATE.set(0.0)


# ---------------------------------------------------------------------------
# Metrics HTTP server
# ---------------------------------------------------------------------------


def start_metrics_server(port: int = 9103) -> None:
    """
    Start the Prometheus metrics HTTP server on the given port.

    This exposes all registered metrics at http://0.0.0.0:<port>/metrics
    for Prometheus to scrape.

    The alert service is a background worker (no FastAPI), so it uses
    prometheus_client's standalone HTTP server instead of /metrics route.

    Args:
        port: TCP port to listen on (default: 9103).

    Raises:
        OSError: If the port is already in use.
    """
    start_http_server(port)
    logger.info(
        "Prometheus metrics server started",
        extra={"port": port, "path": "/metrics"},
    )
