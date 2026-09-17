"""
LogSentinel — Integration Tests
================================
End-to-end tests using httpx against a running local docker-compose stack.
Also includes API contract tests that can run without a live backend.

Usage:
    # Against live services:
    pytest tests/integration/ -v -k "not live" --no-header

    # With live docker-compose stack:
    pytest tests/integration/ -v --no-header
"""

import json
import os
from datetime import datetime, timezone

import httpx
import pytest

BASE_URL_INGESTION = os.getenv("INGESTION_API_URL", "http://localhost:8000")
BASE_URL_DASHBOARD = os.getenv("DASHBOARD_API_URL", "http://localhost:8002")
BASE_URL_ML = os.getenv("ML_ENGINE_URL", "http://localhost:8001")

LIVE_SERVICES = os.getenv("LIVE_SERVICES", "false").lower() == "true"
skip_if_no_live = pytest.mark.skipif(not LIVE_SERVICES, reason="Requires live services")


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def log_payload():
    return {
        "service": "integration-test",
        "level": "ERROR",
        "message": "Integration test: simulated authentication failure",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": "test-host",
        "response_time_ms": 3500.0,
        "error_code": 503,
        "request_count_last_60s": 200,
    }


@pytest.fixture
def predict_payload():
    return {
        "hour_of_day": 3,
        "response_time_ms": 8000.0,
        "error_code": 500,
        "log_level_encoded": 3,
        "request_count_last_60s": 300,
        "service_id_encoded": 1,
    }


# ─── Log Ingestion API Tests ───────────────────────────────────────────────────


class TestIngestionAPIContract:
    """Contract/shape tests for the ingestion API (no live service needed)."""

    def test_payload_schema_valid(self, log_payload):
        """Payload dict should be JSON-serialisable."""
        serialised = json.dumps(log_payload)
        restored = json.loads(serialised)
        assert restored["service"] == log_payload["service"]

    def test_multiple_log_levels_valid(self):
        """Check all supported log levels."""
        for level in ["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"]:
            payload = {
                "service": "test",
                "level": level,
                "message": "Test message",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            assert json.dumps(payload)


class TestIngestionAPILive:
    """Live integration tests against a running ingestion API."""

    @skip_if_no_live
    def test_health_endpoint_returns_200(self):
        response = httpx.get(f"{BASE_URL_INGESTION}/health", timeout=5)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ["healthy", "degraded"]

    @skip_if_no_live
    def test_ingest_single_log(self, log_payload):
        response = httpx.post(
            f"{BASE_URL_INGESTION}/ingest",
            json=log_payload,
            timeout=10,
        )
        assert response.status_code == 202
        body = response.json()
        assert "log_id" in body

    @skip_if_no_live
    def test_ingest_batch_logs(self, log_payload):
        batch = {"logs": [log_payload] * 5}
        response = httpx.post(
            f"{BASE_URL_INGESTION}/ingest/batch",
            json=batch,
            timeout=15,
        )
        assert response.status_code in [200, 202]

    @skip_if_no_live
    def test_metrics_endpoint_reachable(self):
        response = httpx.get(f"{BASE_URL_INGESTION}/metrics", timeout=5)
        assert response.status_code == 200
        assert "ingestion_api_logs_ingested_total" in response.text

    @skip_if_no_live
    def test_invalid_log_returns_422(self):
        response = httpx.post(
            f"{BASE_URL_INGESTION}/ingest",
            json={"invalid": "data"},
            timeout=5,
        )
        assert response.status_code == 422


class TestMLEngineLive:
    """Live integration tests against the ML Engine API."""

    @skip_if_no_live
    def test_model_status_endpoint(self):
        response = httpx.get(f"{BASE_URL_ML}/model/status", timeout=10)
        assert response.status_code == 200
        body = response.json()
        assert "status" in body

    @skip_if_no_live
    def test_predict_endpoint(self, predict_payload):
        response = httpx.post(
            f"{BASE_URL_ML}/predict",
            json=predict_payload,
            timeout=10,
        )
        assert response.status_code == 200
        body = response.json()
        assert "prediction" in body
        assert body["prediction"] in [-1, 1]
        assert "anomaly_score" in body

    @skip_if_no_live
    def test_anomalous_features_detected(self, predict_payload):
        """Extremely anomalous features should return -1 prediction."""
        predict_payload.update(
            {
                "response_time_ms": 50000.0,
                "error_code": 503,
                "log_level_encoded": 4,
                "request_count_last_60s": 1000,
            }
        )
        response = httpx.post(
            f"{BASE_URL_ML}/predict",
            json=predict_payload,
            timeout=10,
        )
        assert response.status_code == 200
        # Score should be negative (anomalous)
        body = response.json()
        assert body["anomaly_score"] < 0


class TestDashboardAPILive:
    """Live integration tests against the Dashboard Backend API."""

    @skip_if_no_live
    def test_health_endpoint(self):
        response = httpx.get(f"{BASE_URL_DASHBOARD}/health", timeout=5)
        assert response.status_code in [200, 503]  # May be degraded w/o full stack

    @skip_if_no_live
    def test_logs_endpoint_paginated(self):
        response = httpx.get(
            f"{BASE_URL_DASHBOARD}/logs",
            params={"page": 1, "size": 10},
            timeout=10,
        )
        assert response.status_code == 200
        body = response.json()
        assert "page" in body
        assert "items" in body
        assert "total" in body
        assert len(body["items"]) <= 10

    @skip_if_no_live
    def test_anomalies_endpoint(self):
        response = httpx.get(f"{BASE_URL_DASHBOARD}/anomalies", timeout=10)
        assert response.status_code == 200
        body = response.json()
        assert "items" in body

    @skip_if_no_live
    def test_stats_endpoint(self):
        response = httpx.get(
            f"{BASE_URL_DASHBOARD}/stats",
            params={"window_minutes": 60},
            timeout=10,
        )
        assert response.status_code == 200
        body = response.json()
        assert "log_rate_per_second" in body
        assert "anomaly_rate_percent" in body
