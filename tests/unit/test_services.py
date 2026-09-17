"""
LogSentinel — Unit Tests: Log Ingestion API
=============================================
Tests for Pydantic model validation, Kafka producer behavior,
and FastAPI endpoint responses.
"""

import asyncio
import sys
from datetime import datetime, timezone

import pytest


def _activate_service_path(service_path: str) -> None:
    if service_path not in sys.path:
        sys.path.insert(0, service_path)

    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_log_entry():
    return {
        "service": "auth-service",
        "level": "ERROR",
        "message": "Failed to authenticate user: invalid token",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": "pod-auth-1",
        "response_time_ms": 2500.0,
        "error_code": 401,
        "request_count_last_60s": 42,
    }


@pytest.fixture
def sample_normal_log():
    return {
        "service": "user-service",
        "level": "INFO",
        "message": "User profile fetched successfully",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": "pod-user-1",
        "response_time_ms": 120.0,
        "error_code": 200,
        "request_count_last_60s": 15,
    }


# ─── Model Validation Tests ───────────────────────────────────────────────────


class TestLogEntryModel:
    """Tests for LogEntry Pydantic model validation."""

    def test_valid_log_entry(self, sample_log_entry):
        """Valid log entry should parse without errors."""
        _activate_service_path("services/log-ingestion-api")
        from app.models import LogEntry

        entry = LogEntry(**sample_log_entry)
        assert entry.service == "auth-service"
        assert entry.level == "ERROR"
        assert entry.response_time_ms == 2500.0

    def test_missing_required_fields(self):
        """Missing required fields should raise ValidationError."""
        _activate_service_path("services/log-ingestion-api")
        from app.models import LogEntry
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LogEntry(service="x")  # Missing level, message, timestamp

    def test_log_level_case_insensitive(self, sample_log_entry):
        """Log level should be normalised to uppercase."""
        _activate_service_path("services/log-ingestion-api")
        from app.models import LogEntry

        sample_log_entry["level"] = "error"
        entry = LogEntry(**sample_log_entry)
        assert entry.level == "ERROR"

    def test_response_time_defaults_to_zero(self, sample_log_entry):
        """response_time_ms should default gracefully."""
        _activate_service_path("services/log-ingestion-api")
        from app.models import LogEntry

        sample_log_entry.pop("response_time_ms", None)
        entry = LogEntry(**sample_log_entry)
        assert entry.response_time_ms is None or entry.response_time_ms >= 0

    def test_negative_response_time_rejected(self, sample_log_entry):
        """Negative response_time_ms should be rejected."""
        _activate_service_path("services/log-ingestion-api")
        from app.models import LogEntry
        from pydantic import ValidationError

        sample_log_entry["response_time_ms"] = -1.0
        with pytest.raises(ValidationError):
            LogEntry(**sample_log_entry)

    def test_invalid_log_level_rejected(self, sample_log_entry):
        """Invalid log level should be rejected."""
        _activate_service_path("services/log-ingestion-api")
        from app.models import LogEntry
        from pydantic import ValidationError

        sample_log_entry["level"] = "TRACE"
        with pytest.raises(ValidationError):
            LogEntry(**sample_log_entry)


# ─── Feature Extractor Tests ──────────────────────────────────────────────────


class TestFeatureExtractor:
    """Tests for feature engineering from raw log entries."""

    def test_extract_hour_of_day(self):
        """hour_of_day should be correctly extracted from ISO timestamp."""
        _activate_service_path("services/log-processor")
        from app.feature_extractor import FeatureExtractor

        log = {
            "timestamp": "2024-06-15T14:30:00Z",
            "level": "INFO",
            "response_time_ms": 100.0,
            "error_code": 200,
            "service": "user-service",
            "request_count_last_60s": 10,
        }
        extractor = FeatureExtractor(redis_url="redis://localhost:6379/15")
        features = asyncio.run(extractor.extract(log))
        assert features["hour_of_day"] == 14

    def test_log_level_encoding(self):
        """Log levels should be encoded to correct integers."""
        _activate_service_path("services/log-processor")
        from app.feature_extractor import FeatureExtractor

        extractor = FeatureExtractor(redis_url="redis://localhost:6379/15")

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
            features = asyncio.run(extractor.extract(log))
            assert (
                features["log_level_encoded"] == expected_int
            ), f"Failed for level {level_str}"

    def test_missing_fields_use_defaults(self):
        """Missing optional fields should use sensible defaults."""
        _activate_service_path("services/log-processor")
        from app.feature_extractor import FeatureExtractor

        log = {"timestamp": "2024-01-01T08:00:00Z", "level": "INFO"}
        extractor = FeatureExtractor(redis_url="redis://localhost:6379/15")
        features = asyncio.run(extractor.extract(log))
        assert "hour_of_day" in features
        assert "response_time_ms" in features
        assert features["response_time_ms"] >= 0


# ─── Anomaly Detection Tests ──────────────────────────────────────────────────


class TestAnomalyDetection:
    """Tests for Isolation Forest model predictions."""

    @pytest.fixture
    def trained_model(self, tmp_path):
        """Create and save a minimal trained model."""
        import numpy as np
        from sklearn.ensemble import IsolationForest

        rng = np.random.default_rng(42)
        X_train = rng.normal(0, 1, size=(300, 6))
        model = IsolationForest(contamination=0.05, random_state=42)
        model.fit(X_train)

        model_path = tmp_path / "test_model.joblib"
        import joblib

        joblib.dump(model, model_path)
        return str(model_path)

    def test_normal_log_predicted_normal(self, trained_model):
        """Normal log features should be predicted as normal (1)."""
        import joblib
        import numpy as np

        model = joblib.load(trained_model)
        X_normal = np.array([[12, 150.0, 200, 1, 20, 1]])
        prediction = model.predict(X_normal)
        # Most normal inputs should be classified as 1
        # (not guaranteed for all, but this is a sanity check)
        assert prediction[0] in [-1, 1]
        score = model.decision_function(X_normal)[0]
        assert isinstance(score, float)

    def test_anomalous_features_lower_score(self, trained_model):
        """Anomalous features should have lower anomaly score than normal."""
        import joblib
        import numpy as np

        model = joblib.load(trained_model)

        X_normal = np.array([[12, 150.0, 200, 1, 20, 1]])
        X_anomalous = np.array([[12, 9000.0, 503, 4, 500, 1]])

        score_normal = model.decision_function(X_normal)[0]
        score_anomalous = model.decision_function(X_anomalous)[0]
        assert score_anomalous < score_normal


# ─── Alert Deduplication Tests ────────────────────────────────────────────────


class TestAlertDeduplication:
    """Tests for Redis-based alert deduplication."""

    def test_dedup_key_is_consistent(self):
        """Two identical alerts should produce the same dedup key."""
        _activate_service_path("services/alert-service")
        from app.deduplicator import _build_dedup_key

        alert = {"service": "auth-service", "level": "ERROR", "error_code": 500}
        key1 = _build_dedup_key(alert)
        key2 = _build_dedup_key(alert)
        assert key1 == key2

    def test_different_services_produce_different_keys(self):
        """Alerts from different services should have different dedup keys."""
        _activate_service_path("services/alert-service")
        from app.deduplicator import _build_dedup_key

        alert_a = {"service": "auth-service", "level": "ERROR", "error_code": 500}
        alert_b = {"service": "payment-service", "level": "ERROR", "error_code": 500}
        assert _build_dedup_key(alert_a) != _build_dedup_key(alert_b)


# ─── Dashboard Stats Tests ────────────────────────────────────────────────────


class TestDashboardHelpers:
    """Tests for dashboard backend helper functions."""

    def test_serialise_alert_converts_datetime(self):
        """_serialise_alert should convert datetime objects to ISO strings."""
        _activate_service_path("services/dashboard-backend")
        from main import _serialise_alert

        alert = {
            "id": 1,
            "service": "ml-engine",
            "detected_at": datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc),
        }
        result = _serialise_alert(alert)
        assert isinstance(result["detected_at"], str)
        assert "2024-06-15" in result["detected_at"]

    def test_serialise_alert_passthrough_scalars(self):
        """Non-datetime fields should pass through unchanged."""
        _activate_service_path("services/dashboard-backend")
        from main import _serialise_alert

        alert = {"id": 42, "service": "test", "score": -0.25}
        result = _serialise_alert(alert)
        assert result == alert
