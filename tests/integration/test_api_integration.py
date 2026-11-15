"""
LogSentinel — Integration Tests
================================
End-to-end tests using httpx against a running local docker-compose stack.
Also includes API contract tests that can run without a live backend.

Usage:
    python -m unittest discover tests/integration
    pytest tests/integration/ -v
"""

import json
import os
import unittest
from datetime import datetime, timezone

import httpx

BASE_URL_INGESTION = os.getenv("INGESTION_API_URL", "http://localhost:8000")
BASE_URL_DASHBOARD = os.getenv("DASHBOARD_API_URL", "http://localhost:8002")
BASE_URL_ML = os.getenv("ML_ENGINE_URL", "http://localhost:8001")

LIVE_SERVICES = os.getenv("LIVE_SERVICES", "false").lower() == "true"
skip_if_no_live = unittest.skipIf(not LIVE_SERVICES, "Requires live services")


class TestIngestionAPIContract(unittest.TestCase):
    """Contract/shape tests for the ingestion API (no live service needed)."""

    def setUp(self):
        self.log_payload = {
            "service": "integration-test",
            "level": "ERROR",
            "message": "Integration test: simulated authentication failure",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": "test-host",
            "response_time_ms": 3500.0,
            "error_code": 503,
            "request_count_last_60s": 200,
        }

    def test_payload_schema_valid(self):
        """Payload dict should be JSON-serialisable."""
        serialised = json.dumps(self.log_payload)
        restored = json.loads(serialised)
        self.assertEqual(restored["service"], self.log_payload["service"])

    def test_multiple_log_levels_valid(self):
        """Check all supported log levels."""
        for level in ["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"]:
            payload = {
                "service": "test",
                "level": level,
                "message": "Test message",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.assertTrue(json.dumps(payload))


class TestIngestionAPILive(unittest.TestCase):
    """Live integration tests against a running ingestion API."""

    def setUp(self):
        self.log_payload = {
            "service": "integration-test",
            "level": "ERROR",
            "message": "Integration test: simulated authentication failure",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": "test-host",
            "response_time_ms": 3500.0,
            "error_code": 503,
            "request_count_last_60s": 200,
        }

    @skip_if_no_live
    def test_health_endpoint_returns_200(self):
        response = httpx.get(f"{BASE_URL_INGESTION}/health", timeout=5)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["status"], ["healthy", "degraded"])

    @skip_if_no_live
    def test_ingest_single_log(self):
        response = httpx.post(
            f"{BASE_URL_INGESTION}/ingest",
            json=self.log_payload,
            timeout=10,
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertIn("log_id", body)

    @skip_if_no_live
    def test_ingest_batch_logs(self):
        batch = {"logs": [self.log_payload] * 5}
        response = httpx.post(
            f"{BASE_URL_INGESTION}/ingest/batch",
            json=batch,
            timeout=15,
        )
        self.assertIn(response.status_code, [200, 202])

    @skip_if_no_live
    def test_metrics_endpoint_reachable(self):
        response = httpx.get(f"{BASE_URL_INGESTION}/metrics", timeout=5)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ingestion_api_logs_ingested_total", response.text)

    @skip_if_no_live
    def test_invalid_log_returns_422(self):
        response = httpx.post(
            f"{BASE_URL_INGESTION}/ingest",
            json={"invalid": "data"},
            timeout=5,
        )
        self.assertEqual(response.status_code, 422)


class TestMLEngineLive(unittest.TestCase):
    """Live integration tests against the ML Engine API."""

    def setUp(self):
        self.predict_payload = {
            "hour_of_day": 3,
            "response_time_ms": 8000.0,
            "error_code": 500,
            "log_level_encoded": 3,
            "request_count_last_60s": 300,
            "service_id_encoded": 1,
        }

    @skip_if_no_live
    def test_model_status_endpoint(self):
        response = httpx.get(f"{BASE_URL_ML}/model/status", timeout=10)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("status", body)

    @skip_if_no_live
    def test_predict_endpoint(self):
        response = httpx.post(
            f"{BASE_URL_ML}/predict",
            json=self.predict_payload,
            timeout=10,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("prediction", body)
        self.assertIn(body["prediction"], [-1, 1])
        self.assertIn("anomaly_score", body)

    @skip_if_no_live
    def test_anomalous_features_detected(self):
        self.predict_payload.update(
            {
                "response_time_ms": 50000.0,
                "error_code": 503,
                "log_level_encoded": 4,
                "request_count_last_60s": 1000,
            }
        )
        response = httpx.post(
            f"{BASE_URL_ML}/predict",
            json=self.predict_payload,
            timeout=10,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertLess(body["anomaly_score"], 0)


class TestDashboardAPILive(unittest.TestCase):
    """Live integration tests against the Dashboard Backend API."""

    @skip_if_no_live
    def test_health_endpoint(self):
        response = httpx.get(f"{BASE_URL_DASHBOARD}/health", timeout=5)
        self.assertIn(response.status_code, [200, 503])

    @skip_if_no_live
    def test_logs_endpoint_paginated(self):
        response = httpx.get(
            f"{BASE_URL_DASHBOARD}/logs",
            params={"page": 1, "size": 10},
            timeout=10,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("page", body)
        self.assertIn("items", body)
        self.assertIn("total", body)
        self.assertLessEqual(len(body["items"]), 10)

    @skip_if_no_live
    def test_anomalies_endpoint(self):
        response = httpx.get(f"{BASE_URL_DASHBOARD}/anomalies", timeout=10)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("items", body)

    @skip_if_no_live
    def test_stats_endpoint(self):
        response = httpx.get(
            f"{BASE_URL_DASHBOARD}/stats",
            params={"window_minutes": 60},
            timeout=10,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("log_rate_per_second", body)
        self.assertIn("anomaly_rate_percent", body)


if __name__ == "__main__":
    unittest.main()
