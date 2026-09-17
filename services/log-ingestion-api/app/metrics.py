"""
LogSentinel — Log Ingestion API: Prometheus Metrics
====================================================
All Prometheus metrics definitions for the Log Ingestion API service.

Metrics exposed at GET /metrics (Prometheus text format):

  Counters:
    logs_ingested_total            — total logs received, by service + level
    kafka_publish_success_total    — successful Kafka publishes
    kafka_publish_errors_total     — failed Kafka publish attempts
    http_requests_total            — HTTP request count by method/path/status

  Histograms:
    http_request_duration_seconds  — HTTP request latency
    batch_size                     — distribution of batch ingest sizes

  Gauges:
    kafka_producer_connected       — 1 if producer is up, 0 if down

Usage:
    from app.metrics import LOGS_INGESTED, KAFKA_PUBLISH_ERRORS
    LOGS_INGESTED.labels(service="auth", level="ERROR").inc()
    KAFKA_PUBLISH_ERRORS.inc()
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
# Keep label cardinality low — never use unbounded values (e.g. user IDs,
# log messages, UUIDs) as label values.

_SERVICE_LABEL = "service"  # originating service name (auth-service, etc.)
_LEVEL_LABEL = "level"  # log severity level (INFO, ERROR, etc.)
_METHOD_LABEL = "method"  # HTTP method (GET, POST, etc.)
_ENDPOINT_LABEL = "endpoint"  # HTTP path (/ingest, /health, etc.)
_STATUS_LABEL = "status_code"  # HTTP response status code

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

LOGS_INGESTED = Counter(
    name="logs_ingested_total",
    documentation=(
        "Total number of log entries successfully accepted and published to Kafka. "
        "Labelled by originating service name and log severity level."
    ),
    labelnames=[_SERVICE_LABEL, _LEVEL_LABEL],
)

KAFKA_PUBLISH_SUCCESS = Counter(
    name="kafka_publish_success_total",
    documentation=(
        "Total number of log messages successfully published to the Kafka raw-logs topic. "
        "Incremented once per successful send_and_wait() call."
    ),
)

KAFKA_PUBLISH_ERRORS = Counter(
    name="kafka_publish_errors_total",
    documentation=(
        "Total number of failed attempts to publish a log message to Kafka. "
        "Incremented after all retry attempts are exhausted, or when the "
        "producer is not connected."
    ),
)

REQUEST_COUNT = Counter(
    name="http_requests_total",
    documentation=(
        "Total number of HTTP requests handled by the Log Ingestion API. "
        "Labelled by HTTP method, endpoint path, and response status code."
    ),
    labelnames=[_METHOD_LABEL, _ENDPOINT_LABEL, _STATUS_LABEL],
)

BATCH_INGEST_TOTAL = Counter(
    name="batch_ingest_requests_total",
    documentation=(
        "Total number of batch ingest requests received at POST /ingest/batch."
    ),
)

BATCH_REJECTED_TOTAL = Counter(
    name="batch_entries_rejected_total",
    documentation=(
        "Total number of individual log entries rejected within batch ingest requests. "
        "Typically caused by Kafka being unavailable during batch processing."
    ),
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

REQUEST_LATENCY = Histogram(
    name="http_request_duration_seconds",
    documentation=(
        "HTTP request duration in seconds for the Log Ingestion API. "
        "Labelled by HTTP method and endpoint path."
    ),
    labelnames=[_METHOD_LABEL, _ENDPOINT_LABEL],
    buckets=(
        0.001,  # 1ms
        0.005,  # 5ms
        0.010,  # 10ms
        0.025,  # 25ms
        0.050,  # 50ms
        0.075,  # 75ms
        0.100,  # 100ms
        0.150,  # 150ms
        0.200,  # 200ms   ← p99 target for /ingest
        0.300,  # 300ms
        0.500,  # 500ms
        1.0,  # 1s
        2.5,  # 2.5s
        5.0,  # 5s
        10.0,  # 10s     ← anything above is very slow
    ),
)

BATCH_SIZE_HISTOGRAM = Histogram(
    name="batch_ingest_size",
    documentation=(
        "Distribution of the number of log entries per batch ingest request. "
        "Helps understand typical batch sizes from clients."
    ),
    buckets=(1, 5, 10, 20, 50, 75, 100),
)

KAFKA_PUBLISH_LATENCY = Histogram(
    name="kafka_publish_duration_seconds",
    documentation=(
        "Time in seconds taken to publish a single message to Kafka "
        "(including retries). Measures end-to-end producer latency."
    ),
    buckets=(
        0.001,  # 1ms
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
    ),
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

KAFKA_PRODUCER_CONNECTED = Gauge(
    name="kafka_producer_connected",
    documentation=(
        "Current connection state of the Kafka producer. "
        "1 = connected and healthy, 0 = disconnected or not yet started."
    ),
)

# Initialise to 0 (disconnected) — will be set to 1 after successful start
KAFKA_PRODUCER_CONNECTED.set(0)
