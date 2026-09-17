"""
LogSentinel — ML Engine: Prometheus Metrics
============================================
All Prometheus metrics definitions for the ML Engine service.

Metrics exposed at GET /metrics (Prometheus text format):

  Counters:
    anomalies_detected_total         — total anomalies detected, by service + level
    kafka_publish_success_total      — successful Kafka publishes to anomaly-alerts
    kafka_publish_errors_total       — failed Kafka publish attempts
    kafka_consume_errors_total       — errors during Kafka message consumption
    http_requests_total              — HTTP request count by method/path/status

  Histograms:
    model_inference_duration_seconds — ML inference latency per request
    http_request_duration_seconds    — HTTP request latency

  Gauges:
    model_loaded                     — 1 if model is loaded, 0 if not
    kafka_consumer_connected         — 1 if consumer is up, 0 if down
    kafka_producer_connected         — 1 if producer is up, 0 if down
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
_SERVICE_LABEL = "service"
_LEVEL_LABEL = "level"
_METHOD_LABEL = "method"
_ENDPOINT_LABEL = "endpoint"
_STATUS_LABEL = "status_code"

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

ANOMALIES_DETECTED = Counter(
    name="ml_engine_anomalies_detected_total",
    documentation=(
        "Total number of log entries classified as anomalies by the Isolation Forest model. "
        "Labelled by the originating service name and log severity level."
    ),
    labelnames=[_SERVICE_LABEL, _LEVEL_LABEL],
)

KAFKA_PUBLISH_SUCCESS = Counter(
    name="ml_engine_kafka_publish_success_total",
    documentation=(
        "Total number of anomaly alert messages successfully published "
        "to the Kafka anomaly-alerts topic."
    ),
)

KAFKA_PUBLISH_ERRORS = Counter(
    name="ml_engine_kafka_publish_errors_total",
    documentation=(
        "Total number of failed attempts to publish an anomaly alert to Kafka. "
        "Incremented after all retry attempts are exhausted."
    ),
)

KAFKA_CONSUME_ERRORS = Counter(
    name="ml_engine_kafka_consume_errors_total",
    documentation=(
        "Total number of errors encountered while consuming from the "
        "processed-logs Kafka topic. Includes deserialization failures "
        "and inference errors."
    ),
)

REQUEST_COUNT = Counter(
    name="ml_engine_http_requests_total",
    documentation=(
        "Total number of HTTP requests handled by the ML Engine API. "
        "Labelled by HTTP method, endpoint path, and response status code."
    ),
    labelnames=[_METHOD_LABEL, _ENDPOINT_LABEL, _STATUS_LABEL],
)

BATCH_PREDICTIONS_TOTAL = Counter(
    name="ml_engine_batch_predictions_total",
    documentation=(
        "Total number of individual feature vectors scored via "
        "POST /predict/batch endpoint."
    ),
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

INFERENCE_DURATION = Histogram(
    name="ml_engine_inference_duration_seconds",
    documentation=(
        "Time in seconds taken to run the Isolation Forest model inference "
        "on a single feature vector or batch. Includes numpy array construction "
        "and scaler transform time, but excludes Kafka I/O."
    ),
    buckets=(
        0.0001,  # 0.1ms
        0.0005,  # 0.5ms
        0.001,  # 1ms
        0.002,  # 2ms
        0.005,  # 5ms
        0.010,  # 10ms
        0.025,  # 25ms
        0.050,  # 50ms
        0.100,  # 100ms  <- p99 target
        0.250,  # 250ms
        0.500,  # 500ms
        1.0,  # 1s
    ),
)

REQUEST_LATENCY = Histogram(
    name="ml_engine_http_request_duration_seconds",
    documentation=(
        "HTTP request duration in seconds for the ML Engine API. "
        "Labelled by HTTP method and endpoint path."
    ),
    labelnames=[_METHOD_LABEL, _ENDPOINT_LABEL],
    buckets=(
        0.001,  # 1ms
        0.005,  # 5ms
        0.010,  # 10ms
        0.025,  # 25ms
        0.050,  # 50ms
        0.100,  # 100ms
        0.200,  # 200ms
        0.500,  # 500ms
        1.0,  # 1s
        2.5,  # 2.5s
        5.0,  # 5s
    ),
)

BATCH_SIZE_HISTOGRAM = Histogram(
    name="ml_engine_batch_predict_size",
    documentation=(
        "Distribution of the number of feature vectors per batch prediction request. "
        "Helps understand typical batch sizes from consumers."
    ),
    buckets=(1, 5, 10, 25, 50, 100, 250, 500),
)

KAFKA_CONSUMER_PROCESSING_DURATION = Histogram(
    name="ml_engine_kafka_message_processing_duration_seconds",
    documentation=(
        "End-to-end time in seconds to process a single message from the "
        "processed-logs Kafka topic: from consumption to anomaly-alerts publish "
        "(if anomaly detected)."
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
    ),
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

MODEL_LOADED = Gauge(
    name="ml_engine_model_loaded",
    documentation=(
        "Indicates whether the Isolation Forest model is currently loaded and ready. "
        "1 = model is loaded and predictions are available. "
        "0 = model is not loaded; /predict endpoints will return 503."
    ),
)

KAFKA_CONSUMER_CONNECTED = Gauge(
    name="ml_engine_kafka_consumer_connected",
    documentation=(
        "Current connection state of the Kafka consumer (processed-logs topic). "
        "1 = connected and consuming, 0 = disconnected."
    ),
)

KAFKA_PRODUCER_CONNECTED = Gauge(
    name="ml_engine_kafka_producer_connected",
    documentation=(
        "Current connection state of the Kafka producer (anomaly-alerts topic). "
        "1 = connected and ready, 0 = disconnected."
    ),
)

ANOMALY_RATE_GAUGE = Gauge(
    name="ml_engine_anomaly_rate_last_minute",
    documentation=(
        "Rolling anomaly rate over the last 60 seconds, expressed as a fraction "
        "of total messages processed. Updated after each batch poll cycle."
    ),
)

# ---------------------------------------------------------------------------
# Initialise gauges to 0 (not loaded / disconnected)
# ---------------------------------------------------------------------------
MODEL_LOADED.set(0)
KAFKA_CONSUMER_CONNECTED.set(0)
KAFKA_PRODUCER_CONNECTED.set(0)
ANOMALY_RATE_GAUGE.set(0.0)
