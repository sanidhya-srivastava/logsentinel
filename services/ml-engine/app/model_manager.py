"""
LogSentinel — ML Engine: Model Manager
=======================================
Manages the lifecycle of the Isolation Forest model:
  - Loading model + scaler from disk (joblib)
  - Running single and batch inference
  - Exposing model metadata for the /model/status endpoint
  - Supporting hot-reload without service restart

The model and scaler are loaded once at startup and cached as instance
attributes. All inference is synchronous (scikit-learn is not async),
run inside a thread pool executor to avoid blocking the event loop.

Usage:
    manager = ModelManager(
        model_path="/app/models/isolation_forest.joblib",
        scaler_path="/app/models/scaler.joblib",
    )
    manager.load()
    result = manager.predict(feature_vector)
    results = manager.predict_batch(feature_vectors)
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from app.schemas import FeatureVector, PredictResponse
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature order — MUST match training feature order exactly
# ---------------------------------------------------------------------------
FEATURE_COLUMNS: list[str] = [
    "hour_of_day",
    "response_time_ms",
    "error_code",
    "log_level_encoded",
    "request_count_last_60s",
    "service_id_encoded",
]

# ---------------------------------------------------------------------------
# Anomaly threshold
# Decision scores below this value are classified as anomalies.
# IsolationForest.decision_function() returns negative values for anomalies.
# The default scikit-learn threshold is 0.0, but we allow override via config.
# ---------------------------------------------------------------------------
DEFAULT_ANOMALY_THRESHOLD: float = 0.0


# ---------------------------------------------------------------------------
# Model metadata container
# ---------------------------------------------------------------------------


@dataclass
class ModelMetadata:
    """Stores metadata about a loaded model file."""

    model_path: str
    scaler_path: str | None
    loaded_at: str  # ISO 8601 UTC string
    n_estimators: int
    contamination: float | str
    n_features: int
    max_samples: int | str
    trained_at: str | None = None  # Set if model file stores this metadata
    model_version: str | None = None


# ---------------------------------------------------------------------------
# Model Manager
# ---------------------------------------------------------------------------


class ModelManager:
    """
    Thread-safe manager for the Isolation Forest anomaly detection model.

    Attributes:
        model_path:  Path to the joblib-serialised IsolationForest model file.
        scaler_path: Path to the joblib-serialised StandardScaler file.
                     If None or missing, features are passed to the model raw.
        threshold:   Decision score threshold below which a sample is an anomaly.
                     Default: 0.0 (scikit-learn's default decision boundary).

    Thread safety:
        A threading.RLock protects the model and scaler references during
        hot-reload so that in-flight requests complete before the model swap.
    """

    def __init__(
        self,
        model_path: str,
        scaler_path: str | None = None,
        threshold: float = DEFAULT_ANOMALY_THRESHOLD,
    ) -> None:
        self._model_path = str(model_path)
        self._scaler_path = str(scaler_path) if scaler_path else None
        self._threshold = threshold

        self._model: IsolationForest | None = None
        self._scaler: StandardScaler | None = None
        self._metadata: ModelMetadata | None = None
        self._lock = threading.RLock()

        logger.debug(
            "ModelManager initialised",
            extra={
                "model_path": self._model_path,
                "scaler_path": self._scaler_path,
                "threshold": self._threshold,
            },
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """True if the model has been loaded successfully."""
        with self._lock:
            return self._model is not None

    @property
    def n_estimators(self) -> int:
        """Number of trees in the Isolation Forest."""
        with self._lock:
            if self._model is None:
                return 0
            return int(getattr(self._model, "n_estimators", 0))

    @property
    def contamination(self) -> float | str:
        """Contamination parameter of the Isolation Forest."""
        with self._lock:
            if self._model is None:
                return 0.0
            return getattr(self._model, "contamination", 0.0)

    @property
    def n_features(self) -> int:
        """Number of input features the model expects."""
        with self._lock:
            if self._model is None:
                return len(FEATURE_COLUMNS)
            return int(getattr(self._model, "n_features_in_", len(FEATURE_COLUMNS)))

    @property
    def trained_at(self) -> str | None:
        """ISO 8601 timestamp when the model was trained (if available)."""
        with self._lock:
            if self._metadata is None:
                return None
            return self._metadata.trained_at

    @property
    def threshold(self) -> float:
        """Current anomaly decision threshold."""
        return self._threshold

    # ------------------------------------------------------------------
    # Load / Reload
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Load the Isolation Forest model (and optional scaler) from disk.

        Acquires the RLock during the swap so in-flight predictions using
        the old model complete cleanly before the new model is installed.

        Raises:
            FileNotFoundError: If the model file does not exist.
            ValueError:        If the loaded object is not an IsolationForest.
            Exception:         Any joblib / pickle deserialization error.
        """
        model_path = Path(self._model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Model file not found: {self._model_path}. "
                "Run 'make train' to generate the model file."
            )

        logger.info(
            "Loading Isolation Forest model",
            extra={"model_path": self._model_path},
        )

        start = time.perf_counter()

        # --- Load model ---
        loaded_model = joblib.load(model_path)
        if not isinstance(loaded_model, IsolationForest):
            raise ValueError(
                f"Expected an IsolationForest model, got {type(loaded_model).__name__}. "
                f"Re-run 'make train' to regenerate the model file."
            )

        # --- Load scaler (optional) ---
        loaded_scaler: StandardScaler | None = None
        if self._scaler_path:
            scaler_path = Path(self._scaler_path)
            if scaler_path.exists():
                loaded_scaler = joblib.load(scaler_path)
                if not isinstance(loaded_scaler, StandardScaler):
                    logger.warning(
                        "Scaler file does not contain a StandardScaler — ignoring",
                        extra={"scaler_path": self._scaler_path},
                    )
                    loaded_scaler = None
                else:
                    logger.info(
                        "StandardScaler loaded",
                        extra={"scaler_path": self._scaler_path},
                    )
            else:
                logger.warning(
                    "Scaler file not found — running without feature scaling",
                    extra={"scaler_path": self._scaler_path},
                )

        # --- Extract metadata ---
        n_estimators = int(getattr(loaded_model, "n_estimators", 100))
        contamination = getattr(loaded_model, "contamination", 0.05)
        n_features = int(getattr(loaded_model, "n_features_in_", len(FEATURE_COLUMNS)))
        max_samples = getattr(loaded_model, "max_samples", "auto")

        # Retrieve training timestamp if stored in model attributes
        trained_at: str | None = getattr(loaded_model, "_trained_at", None)

        metadata = ModelMetadata(
            model_path=self._model_path,
            scaler_path=self._scaler_path,
            loaded_at=datetime.now(timezone.utc).isoformat(),
            n_estimators=n_estimators,
            contamination=contamination,
            n_features=n_features,
            max_samples=max_samples,
            trained_at=trained_at,
        )

        # --- Atomic swap under lock ---
        with self._lock:
            self._model = loaded_model
            self._scaler = loaded_scaler
            self._metadata = metadata

        duration = time.perf_counter() - start
        logger.info(
            "Model loaded successfully",
            extra={
                "n_estimators": n_estimators,
                "contamination": contamination,
                "n_features": n_features,
                "load_duration_ms": round(duration * 1000, 2),
                "trained_at": trained_at or "unknown",
            },
        )

    def reload(self) -> None:
        """
        Hot-reload the model from disk without restarting the service.

        Useful for deploying a newly trained model.
        Delegates to load() which handles the thread-safe swap.
        """
        logger.info("Hot-reloading ML model")
        self.load()
        logger.info("Model hot-reload complete")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, feature_vector: FeatureVector) -> PredictResponse:
        """
        Run anomaly detection on a single feature vector.

        Args:
            feature_vector: A FeatureVector Pydantic model with all 6 features.

        Returns:
            PredictResponse with:
              - prediction      : int  — 1 (normal) or -1 (anomaly)
              - anomaly_score   : float — raw decision function score
              - is_anomaly      : bool
              - threshold_used  : float — the decision threshold applied

        Raises:
            RuntimeError: If the model is not loaded.
            ValueError:   If the feature vector cannot be converted to a numpy array.
        """
        with self._lock:
            if self._model is None:
                raise RuntimeError("Model is not loaded. Call load() before predict().")
            model = self._model
            scaler = self._scaler

        X = _feature_vector_to_numpy(feature_vector)

        # Apply scaler if available
        if scaler is not None:
            try:
                X = scaler.transform(X)
            except Exception as exc:
                logger.warning(
                    "Scaler transform failed — using raw features",
                    extra={"error": str(exc)},
                )

        # IsolationForest.predict() returns 1 (normal) or -1 (anomaly)
        prediction_raw: int = int(model.predict(X)[0])

        # decision_function returns the mean anomaly score of the trees.
        # Negative = anomaly, positive = normal. Range is not bounded to [-1, 1].
        decision_score: float = float(model.decision_function(X)[0])

        is_anomaly = decision_score < self._threshold

        logger.debug(
            "Single prediction",
            extra={
                "prediction": prediction_raw,
                "decision_score": round(decision_score, 4),
                "is_anomaly": is_anomaly,
                "threshold": self._threshold,
            },
        )

        return PredictResponse(
            prediction=prediction_raw,
            anomaly_score=round(decision_score, 6),
            is_anomaly=is_anomaly,
            threshold_used=self._threshold,
        )

    def predict_batch(
        self, feature_vectors: list[FeatureVector]
    ) -> list[PredictResponse]:
        """
        Run anomaly detection on a batch of feature vectors.

        Processes the entire batch in a single numpy matrix operation
        for maximum throughput efficiency.

        Args:
            feature_vectors: List of FeatureVector Pydantic models.

        Returns:
            List of PredictResponse objects in the same order as input.

        Raises:
            RuntimeError: If the model is not loaded.
            ValueError:   If the batch is empty.
        """
        if not feature_vectors:
            raise ValueError("feature_vectors list must not be empty")

        with self._lock:
            if self._model is None:
                raise RuntimeError(
                    "Model is not loaded. Call load() before predict_batch()."
                )
            model = self._model
            scaler = self._scaler

        # Stack all feature vectors into a single (N, 6) matrix
        X = np.vstack([_feature_vector_to_numpy(fv) for fv in feature_vectors])

        # Apply scaler if available
        if scaler is not None:
            try:
                X = scaler.transform(X)
            except Exception as exc:
                logger.warning(
                    "Scaler transform failed on batch — using raw features",
                    extra={"error": str(exc)},
                )

        predictions_raw: np.ndarray = model.predict(X)
        decision_scores: np.ndarray = model.decision_function(X)

        results: list[PredictResponse] = []
        for pred, score in zip(predictions_raw, decision_scores):
            is_anomaly = float(score) < self._threshold
            results.append(
                PredictResponse(
                    prediction=int(pred),
                    anomaly_score=round(float(score), 6),
                    is_anomaly=is_anomaly,
                    threshold_used=self._threshold,
                )
            )

        anomaly_count = sum(1 for r in results if r.is_anomaly)
        logger.debug(
            "Batch prediction complete",
            extra={
                "batch_size": len(feature_vectors),
                "anomaly_count": anomaly_count,
                "anomaly_rate": round(anomaly_count / len(feature_vectors), 3),
            },
        )

        return results

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_metadata(self) -> ModelMetadata | None:
        """Return the metadata of the currently loaded model."""
        with self._lock:
            return self._metadata

    def __repr__(self) -> str:
        return (
            f"ModelManager("
            f"model_path={self._model_path!r}, "
            f"loaded={self.is_loaded}, "
            f"n_estimators={self.n_estimators}, "
            f"contamination={self.contamination})"
        )


# ---------------------------------------------------------------------------
# Helper: FeatureVector → numpy array
# ---------------------------------------------------------------------------


def _feature_vector_to_numpy(fv: FeatureVector) -> np.ndarray:
    """
    Convert a FeatureVector Pydantic model to a (1, 6) numpy float64 array.

    Feature order is fixed and MUST match the order used during training.
    See FEATURE_COLUMNS for the canonical order.
    """
    values = [
        float(fv.hour_of_day),
        float(fv.response_time_ms),
        float(fv.error_code),
        float(fv.log_level_encoded),
        float(fv.request_count_last_60s),
        float(fv.service_id_encoded),
    ]
    return np.array(values, dtype=np.float64).reshape(1, -1)
