"""
LogSentinel — Load Tests (Locust)
==================================
Load testing for the Log Ingestion API and Dashboard Backend.

Usage:
    # Web UI (recommended for first run):
    locust -f tests/load/locustfile.py --host=http://localhost:8000

    # Headless (for CI):
    locust -f tests/load/locustfile.py \
        --host=http://localhost:8000 \
        --headless \
        --users=50 \
        --spawn-rate=10 \
        --run-time=60s \
        --html=tests/load/report.html
"""

import random
from datetime import datetime, timezone

from locust import HttpUser, TaskSet, between, task

# ─── Shared data generation ───────────────────────────────────────────────────

SERVICES = [
    "auth-service",
    "user-service",
    "payment-service",
    "order-service",
    "api-gateway",
]
LOG_LEVELS = ["DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR", "CRITICAL"]
ERROR_CODES = [200, 200, 200, 201, 302, 400, 401, 403, 404, 500, 503]
MESSAGES = [
    "User authenticated successfully",
    "Payment processed for order {}",
    "Database query executed in {}ms",
    "Cache miss for key: {}",
    "Connection timeout to upstream service",
    "Invalid JWT token signature",
    "Rate limit exceeded for client {}",
    "Unknown error during request processing",
    "Service temporarily unavailable",
    "Request completed successfully",
]


def random_log_payload() -> dict:
    """Generate a random but realistic log entry."""
    # ~5% should be anomalous
    is_anomaly = random.random() < 0.05
    service = random.choice(SERVICES)
    level = random.choice(["ERROR", "CRITICAL"] if is_anomaly else LOG_LEVELS)
    response_time = random.uniform(2000, 9000) if is_anomaly else random.gauss(180, 50)
    error_code = (
        random.choice([500, 503]) if is_anomaly else random.choice(ERROR_CODES[:8])
    )
    request_count = random.randint(200, 800) if is_anomaly else random.randint(1, 80)

    return {
        "service": service,
        "level": level,
        "message": random.choice(MESSAGES).format(random.randint(100, 9999)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": f"pod-{service}-{random.randint(1, 5)}",
        "response_time_ms": max(0.0, response_time),
        "error_code": error_code,
        "request_count_last_60s": request_count,
    }


def random_batch_payload(size: int = 10) -> dict:
    return {"logs": [random_log_payload() for _ in range(size)]}


# ─── Ingestion API Tasks ───────────────────────────────────────────────────────


class IngestionTasks(TaskSet):
    """Tasks targeting the Log Ingestion API."""

    @task(10)
    def ingest_single_log(self):
        """Single log ingestion — most common task."""
        payload = random_log_payload()
        with self.client.post(
            "/ingest",
            json=payload,
            headers={"Content-Type": "application/json"},
            name="POST /ingest (single)",
            catch_response=True,
        ) as response:
            if response.status_code in [200, 202]:
                response.success()
            elif response.status_code == 422:
                response.failure(f"Validation error: {response.text[:200]}")
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(2)
    def ingest_batch_logs(self):
        """Batch log ingestion."""
        payload = random_batch_payload(size=random.randint(5, 20))
        with self.client.post(
            "/ingest/batch",
            json=payload,
            headers={"Content-Type": "application/json"},
            name="POST /ingest/batch",
            catch_response=True,
        ) as response:
            if response.status_code in [200, 202]:
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")

    @task(1)
    def check_health(self):
        """Health check — low frequency."""
        self.client.get("/health", name="GET /health")

    @task(1)
    def check_metrics(self):
        """Prometheus metrics — low frequency."""
        self.client.get("/metrics", name="GET /metrics")


class DashboardTasks(TaskSet):
    """Tasks targeting the Dashboard Backend API."""

    @task(5)
    def get_logs_paginated(self):
        page = random.randint(1, 10)
        size = random.choice([10, 20, 50])
        level = random.choice(["INFO", "ERROR", None, None])
        params = {"page": page, "size": size}
        if level:
            params["level"] = level
        with self.client.get(
            "/logs",
            params=params,
            name="GET /logs",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")

    @task(3)
    def get_anomalies(self):
        self.client.get(
            "/anomalies", params={"page": 1, "size": 20}, name="GET /anomalies"
        )

    @task(2)
    def get_stats(self):
        window = random.choice([15, 30, 60, 120])
        self.client.get("/stats", params={"window_minutes": window}, name="GET /stats")

    @task(1)
    def health_check(self):
        self.client.get("/health", name="GET /health")


# ─── User classes ──────────────────────────────────────────────────────────────


class IngestionApiUser(HttpUser):
    """
    Simulates application services pushing logs to the Ingestion API.
    High concurrency, frequent requests.
    """

    tasks = [IngestionTasks]
    wait_time = between(0.1, 0.5)  # 2–10 requests/second per user
    host = "http://localhost:8000"


class DashboardApiUser(HttpUser):
    """
    Simulates dashboard viewers querying log statistics.
    Lower frequency, read-heavy.
    """

    tasks = [DashboardTasks]
    wait_time = between(1, 5)
    host = "http://localhost:8002"
