"""
LogSentinel — Log Processor: Prometheus Metrics
================================================
All Prometheus metrics definitions for the Log Processor service.

Metrics exposed (scraped by Prometheus via a background HTTP server
or read directly via prometheus_client):

  Counters:
    logs_processed_total          — successfully processed log messages
    logs_failed_total             — messages that failed processing
    es_index_success_total        — successful Elasticsearch index ops
    es_index_errors_total         — failed Elasticsearch index ops
    kafka_messages_consumed_total — total messages consumed from Kafka

  Histograms:
    log_processing_duration_seconds — end-to-end processing time per message

  Gauges:
    kafka_consumer_connected       — 1 if consumer is up, 0 if down
    kafka_consumer_lag             — estimated consumer lag (messages behind)

Usage:
    from app.metrics import LOGS_PROCESSED_TOTAL, PROCESSING_DURATION
    LOGS_PROCESSED_TOTAL.labels(service="auth", level="ERROR").inc()
    PROCESSING_DURATION.observe(0.045)
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
_SERVICE_LABEL = "service"
_LEVEL_LABEL = "level"
_REASON_LABEL = "reason"
_TOPIC_LABEL = "topic"

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

LOGS_PROCESSED_TOTAL = Counter(
    name="log_processor_messages_processed_total",
    documentation=(
        "Total number of raw log messages successfully consumed from Kafka, "
        "processed (normalised + feature extracted), indexed in Elasticsearch, "
        "and published to the processed-logs topic. "
        "Labelled by originating service name and normalised log level."
    ),
    labelnames=[_SERVICE_LABEL, _LEVEL_LABEL],
)

LOGS_FAILED_TOTAL = Counter(
    name="log_processor_messages_failed_total",
    documentation=(
        "Total number of raw log messages that failed processing and were skipped. "
        "Labelled by the exception type (reason) that caused the failure."
    ),
    labelnames=[_REASON_LABEL],
)

ES_INDEX_SUCCESS = Counter(
    name="log_processor_es_index_success_total",
    documentation=(
        "Total number of log documents successfully indexed into Elasticsearch."
    ),
)

ES_INDEX_ERRORS = Counter(
    name="log_processor_es_index_errors_total",
    documentation=(
        "Total number of failed Elasticsearch index operations. "
        "Failures here are non-fatal — the message is still forwarded "
        "to the processed-logs Kafka topic."
    ),
)

KAFKA_MESSAGES_CONSUMED = Counter(
    name="log_processor_kafka_messages_consumed_total",
    documentation=(
        "Total number of raw log messages consumed from the Kafka raw-logs topic. "
        "This is incremented before processing, so it includes both successful "
        "and failed messages."
    ),
    labelnames=[_TOPIC_LABEL],
)

KAFKA_PUBLISH_SUCCESS = Counter(
    name="log_processor_kafka_publish_success_total",
    documentation=(
        "Total number of processed log messages successfully published "
        "to the Kafka processed-logs topic."
    ),
)

KAFKA_PUBLISH_ERRORS = Counter(
    name="log_processor_kafka_publish_errors_total",
    documentation=(
        "Total number of failed publish attempts to the Kafka processed-logs topic."
    ),
)

FEATURE_EXTRACTION_ERRORS = Counter(
    name="log_processor_feature_extraction_errors_total",
    documentation=(
        "Total number of feature extraction failures. "
        "When extraction fails, a zero-vector fallback is used so the "
        "message is not dropped entirely."
    ),
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

PROCESSING_DURATION = Histogram(
    name="log_processor_message_processing_duration_seconds",
    documentation=(
        "End-to-end processing time in seconds for a single raw log message, "
        "from consumption off Kafka to successful publish of the processed message. "
        "Includes feature extraction, Elasticsearch indexing, and Kafka publish."
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
        2.5,  # 2.5s
        5.0,  # 5s
        10.0,  # 10s
    ),
)

ES_INDEX_DURATION = Histogram(
    name="log_processor_es_index_duration_seconds",
    documentation=(
        "Time in seconds taken to index a single log document into Elasticsearch, "
        "including retries."
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
    ),
)

FEATURE_EXTRACTION_DURATION = Histogram(
    name="log_processor_feature_extraction_duration_seconds",
    documentation=(
        "Time in seconds taken to extract ML feature vectors from a single log entry, "
        "including Redis calls for rolling counter and service ID lookup."
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
    name="log_processor_kafka_consumer_connected",
    documentation=(
        "Current connection state of the Kafka consumer. "
        "1 = connected and consuming, 0 = disconnected."
    ),
)

KAFKA_CONSUME_LAG = Gauge(
    name="log_processor_kafka_consumer_lag",
    documentation=(
        "Estimated consumer lag: the number of messages in the raw-logs topic "
        "that have not yet been consumed by this service. "
        "A growing lag indicates the processor is falling behind ingestion rate."
    ),
    labelnames=[_TOPIC_LABEL],
)

ES_CONNECTED = Gauge(
    name="log_processor_elasticsearch_connected",
    documentation=(
        "Current connection state of the Elasticsearch client. "
        "1 = connected, 0 = disconnected."
    ),
)

REDIS_CONNECTED = Gauge(
    name="log_processor_redis_connected",
    documentation=(
        "Current connection state of the Redis client used for "
        "rolling counters and service ID mapping. "
        "1 = connected, 0 = disconnected."
    ),
)

# Initialise gauges to 0 (disconnected) at startup
KAFKA_CONSUMER_CONNECTED.set(0)
ES_CONNECTED.set(0)
REDIS_CONNECTED.set(0)
