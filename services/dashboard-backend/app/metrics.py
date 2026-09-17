"""
LogSentinel — Dashboard Backend: Prometheus Metrics
====================================================
All prometheus_client counters, histograms, and gauges for the
Dashboard Backend service.
"""

from prometheus_client import Counter, Gauge, Histogram

# HTTP request metrics
REQUEST_COUNT = Counter(
    "dashboard_backend_requests_total",
    "Total HTTP requests received",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "dashboard_backend_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Elasticsearch query metrics
ES_QUERY_COUNT = Counter(
    "dashboard_backend_es_queries_total",
    "Total Elasticsearch queries executed",
    ["operation"],
)

ES_QUERY_LATENCY = Histogram(
    "dashboard_backend_es_query_duration_seconds",
    "Elasticsearch query duration in seconds",
    ["operation"],
)

# Database query metrics
DB_QUERY_COUNT = Counter(
    "dashboard_backend_db_queries_total",
    "Total PostgreSQL queries executed",
    ["operation"],
)

DB_QUERY_LATENCY = Histogram(
    "dashboard_backend_db_query_duration_seconds",
    "PostgreSQL query duration in seconds",
    ["operation"],
)

# Cache metrics
CACHE_HIT_COUNT = Counter(
    "dashboard_backend_cache_hits_total",
    "Number of Redis cache hits",
)

CACHE_MISS_COUNT = Counter(
    "dashboard_backend_cache_misses_total",
    "Number of Redis cache misses",
)

# Health status
SERVICE_UP = Gauge(
    "dashboard_backend_up",
    "1 if the service is healthy, 0 otherwise",
)
SERVICE_UP.set(1)
