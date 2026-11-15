"""
LogSentinel — Unit Tests
========================
Tests for Pydantic models, FeatureExtractor, ML Anomaly Detection,
Alert Deduplication, and Dashboard helpers.

Can be run via:
    python -m unittest discover tests/unit
    python tests/unit/test_services.py
    pytest tests/unit/test_services.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


def _activate_service_path(service_path: str) -> None:
    abs_path = os.path.abspath(service_path)
    if abs_path not in sys.path:
        sys.path.insert(0, abs_path)

    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


def _run_async(coro):
    """Run an async coroutine synchronously without event loop deadlock."""
    try:
        return coro.send(None)
    except StopIteration as e:
        return e.value


class TestLogEntryModel(unittest.TestCase):
    """Tests for LogEntry Pydantic model validation."""

    def setUp(self):
        _activate_service_path("services/log-ingestion-api")
        self.sample_log = {
            "service": "auth-service",
            "level": "ERROR",
            "message": "Failed to authenticate user: invalid token",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": "pod-auth-1",
            "response_time_ms": 2500.0,
            "error_code": 401,
            "request_count_last_60s": 42,
        }

    def test_valid_log_entry(self):
        from app.models import LogEntry

        entry = LogEntry(**self.sample_log)
        self.assertEqual(entry.service, "auth-service")
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.response_time_ms, 2500.0)

    def test_missing_required_fields(self):
        from app.models import LogEntry
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            LogEntry(service="x")

    def test_log_level_case_insensitive(self):
        from app.models import LogEntry

        self.sample_log["level"] = "error"
        entry = LogEntry(**self.sample_log)
        self.assertEqual(entry.level, "ERROR")

    def test_response_time_defaults_to_zero(self):
        from app.models import LogEntry

        self.sample_log.pop("response_time_ms", None)
        entry = LogEntry(**self.sample_log)
        self.assertTrue(entry.response_time_ms is None or entry.response_time_ms >= 0)

    def test_negative_response_time_rejected(self):
        from app.models import LogEntry
        from pydantic import ValidationError

        self.sample_log["response_time_ms"] = -1.0
        with self.assertRaises(ValidationError):
            LogEntry(**self.sample_log)

    def test_invalid_log_level_rejected(self):
        from app.models import LogEntry
        from pydantic import ValidationError

        self.sample_log["level"] = "TRACE"
        with self.assertRaises(ValidationError):
            LogEntry(**self.sample_log)


class TestFeatureExtractor(unittest.TestCase):
    """Tests for feature engineering from raw log entries."""

    def setUp(self):
        _activate_service_path("services/log-processor")
        from app.feature_extractor import FeatureExtractor

        self.extractor = FeatureExtractor(redis_url="redis://localhost:6379/15")

    def test_extract_hour_of_day(self):
        log = {
            "timestamp": "2024-06-15T14:30:00Z",
            "level": "INFO",
            "response_time_ms": 100.0,
            "error_code": 200,
            "service": "user-service",
            "request_count_last_60s": 10,
        }
        features = _run_async(self.extractor.extract(log))
        self.assertEqual(features["hour_of_day"], 14)

    def test_log_level_encoding(self):
        expected = {
            "DEBUG": 0,
            "INFO": 1,
            "WARN": 2,
            "WARNING": 2,
            "ERROR": 3,
            "CRITICAL": 4,
        }
        for level_str, expected_int in expected.items():
            log = {
                "timestamp": "2024-01-01T12:00:00Z",
                "level": level_str,
                "response_time_ms": 50.0,
                "error_code": 200,
                "service": "api-gateway",
                "request_count_last_60s": 5,
            }
            features = _run_async(self.extractor.extract(log))
            self.assertEqual(
                features["log_level_encoded"],
                expected_int,
                f"Failed for level {level_str}",
            )

    def test_missing_fields_use_defaults(self):
        log = {"timestamp": "2024-01-01T08:00:00Z", "level": "INFO"}
        features = _run_async(self.extractor.extract(log))
        self.assertIn("hour_of_day", features)
        self.assertIn("response_time_ms", features)
        self.assertGreaterEqual(features["response_time_ms"], 0)


class TestAnomalyDetection(unittest.TestCase):
    """Tests for Isolation Forest model predictions."""

    @classmethod
    def setUpClass(cls):
        import joblib
        import numpy as np
        from sklearn.ensemble import IsolationForest

        rng = np.random.default_rng(42)
        X_train = rng.normal(0, 1, size=(200, 6))
        cls.model = IsolationForest(contamination=0.05, random_state=42)
        cls.model.fit(X_train)

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.model_path = os.path.join(cls.temp_dir.name, "test_model.joblib")
        joblib.dump(cls.model, cls.model_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_normal_log_predicted_normal(self):
        import joblib
        import numpy as np

        model = joblib.load(self.model_path)
        X_normal = np.array([[12, 150.0, 200, 1, 20, 1]])
        prediction = model.predict(X_normal)
        self.assertIn(prediction[0], [-1, 1])
        score = model.decision_function(X_normal)[0]
        self.assertIsInstance(float(score), float)

    def test_anomalous_features_lower_score(self):
        import joblib
        import numpy as np

        model = joblib.load(self.model_path)
        X_normal = np.array([[12, 150.0, 200, 1, 20, 1]])
        X_anomalous = np.array([[12, 9000.0, 503, 4, 500, 1]])

        score_normal = model.decision_function(X_normal)[0]
        score_anomalous = model.decision_function(X_anomalous)[0]
        self.assertLess(score_anomalous, score_normal)


class TestAlertDeduplication(unittest.TestCase):
    """Tests for Redis-based alert deduplication."""

    def test_dedup_key_is_consistent(self):
        _activate_service_path("services/alert-service")
        from app.deduplicator import _build_dedup_key

        alert = {"service": "auth-service", "level": "ERROR", "error_code": 500}
        key1 = _build_dedup_key(alert)
        key2 = _build_dedup_key(alert)
        self.assertEqual(key1, key2)

    def test_different_services_produce_different_keys(self):
        _activate_service_path("services/alert-service")
        from app.deduplicator import _build_dedup_key

        alert_a = {"service": "auth-service", "level": "ERROR", "error_code": 500}
        alert_b = {"service": "payment-service", "level": "ERROR", "error_code": 500}
        self.assertNotEqual(_build_dedup_key(alert_a), _build_dedup_key(alert_b))


class TestDashboardHelpers(unittest.TestCase):
    """Tests for dashboard backend helper functions."""

    def test_serialise_alert_converts_datetime(self):
        _activate_service_path("services/dashboard-backend")
        from main import _serialise_alert

        alert = {
            "id": 1,
            "service": "ml-engine",
            "detected_at": datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc),
        }
        result = _serialise_alert(alert)
        self.assertIsInstance(result["detected_at"], str)
        self.assertIn("2024-06-15", result["detected_at"])

    def test_serialise_alert_passthrough_scalars(self):
        _activate_service_path("services/dashboard-backend")
        from main import _serialise_alert

        alert = {"id": 42, "service": "test", "score": -0.25}
        result = _serialise_alert(alert)
        self.assertEqual(result, alert)

    def test_serialise_alert_parses_json_features_and_maps_score(self):
        import uuid

        _activate_service_path("services/dashboard-backend")
        from main import _serialise_alert

        alert_uuid = uuid.uuid4()
        alert = {
            "id": 7,
            "alert_id": alert_uuid,
            "anomaly_score": -0.34,
            "features": '{"hour_of_day": 3, "error_code": 4}',
        }
        result = _serialise_alert(alert)
        self.assertEqual(result["alert_id"], str(alert_uuid))
        self.assertEqual(result["score"], -0.34)
        self.assertEqual(result["features"], {"hour_of_day": 3, "error_code": 4})

    def test_dashboard_db_schema_and_disconnected_safety(self):
        _activate_service_path("services/dashboard-backend")
        from app.database import DashboardDB

        db = DashboardDB("postgresql://localhost:5432/logsentinel")
        self.assertIn("anomaly_score", db._ALERT_COLS)
        self.assertIn("notification_channels", db._ALERT_COLS)
        self.assertEqual(_run_async(db.get_recent_alerts()), [])
        self.assertEqual(_run_async(db.count_alerts()), 0)
        self.assertEqual(_run_async(db.count_alerts_last_hour()), 0)
        self.assertIsNone(_run_async(db.get_alert_by_id("missing")))

    def test_dashboard_endpoints_live_contract(self):
        _activate_service_path("services/dashboard-backend")
        import main as dash_main

        class _FakeES:
            is_connected = True

            async def count_logs(self, query=None):
                return 12

            async def search_logs(self, query=None, page=1, size=20):
                return {
                    "total": 1,
                    "hits": [{"service": "auth-service", "level": "ERROR", "message": "timeout"}],
                }

        class _FakeDB:
            is_connected = True

            async def get_recent_alerts(self, limit=20, offset=0):
                return [{"id": 1, "service": "auth-service", "anomaly_score": -0.42, "level": "ERROR"}]

            async def count_alerts(self):
                return 1

            async def count_alerts_last_hour(self):
                return 1

        orig_es, orig_db, orig_cache = dash_main.es_client, dash_main.db_client, dash_main.cache
        try:
            dash_main.es_client = _FakeES()
            dash_main.db_client = _FakeDB()
            dash_main.cache = None

            stats = _run_async(dash_main.get_stats(window_minutes=60, nocache=True))
            logs = _run_async(dash_main.get_logs(page=1, size=20, level=None, service=None, start=None, end=None, q=None))
            anomalies = _run_async(dash_main.get_anomalies(page=1, size=20, service=None, start=None, end=None))

            self.assertEqual(stats["logs_last_hour"], 12)
            self.assertEqual(stats["total_anomalies"], 1)
            self.assertEqual(logs["total"], 1)
            self.assertEqual(logs["items"][0]["service"], "auth-service")
            self.assertEqual(anomalies["total"], 1)
            self.assertEqual(anomalies["items"][0]["score"], -0.42)
        finally:
            dash_main.es_client, dash_main.db_client, dash_main.cache = orig_es, orig_db, orig_cache


if __name__ == "__main__":
    unittest.main()
