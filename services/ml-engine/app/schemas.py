"""
LogSentinel — ML Engine: Pydantic Schemas
==========================================
Request and response models for the ML Engine API.

Models:
  FeatureVector        — input to /predict (single entry)
  PredictResponse      — output from /predict
  BatchPredictRequest  — input to /predict/batch
  BatchPredictResponse — output from /predict/batch
  ModelStatusResponse  — output from /model/status
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Input: Feature Vector
# ---------------------------------------------------------------------------


class FeatureVector(BaseModel):
    """
    The 6-dimensional feature vector used as input to the Isolation Forest model.

    All features must be present. Missing values should be defaulted to 0
    by the upstream log processor before sending to this endpoint.
    """

    hour_of_day: int = Field(
        ...,
        ge=0,
        le=23,
        description="Hour of the day (UTC) when the log was emitted (0–23)",
        examples=[3, 14],
    )

    response_time_ms: float = Field(
        ...,
        ge=0.0,
        description="Request or operation response time in milliseconds (>= 0)",
        examples=[145.3, 5000.0],
    )

    error_code: int = Field(
        ...,
        ge=0,
        le=5,
        description=(
            "Bucket-encoded error/status code category: "
            "0=none/unknown, 1=2xx success, 2=3xx redirect, "
            "3=4xx client error, 4=5xx server error, 5=other"
        ),
        examples=[1, 4],
    )

    log_level_encoded: int = Field(
        ...,
        ge=0,
        le=4,
        description=(
            "Encoded log severity level: DEBUG=0, INFO=1, WARN=2, ERROR=3, CRITICAL=4"
        ),
        examples=[1, 3],
    )

    request_count_last_60s: int = Field(
        ...,
        ge=0,
        description=(
            "Rolling count of requests from the same service in the last 60 seconds. "
            "Used to detect traffic spikes or sudden drops."
        ),
        examples=[120, 1500],
    )

    service_id_encoded: int = Field(
        ...,
        ge=0,
        description="Integer label encoding of the originating service name.",
        examples=[0, 3],
    )

    @field_validator("response_time_ms")
    @classmethod
    def cap_response_time(cls, v: float) -> float:
        """Cap response_time_ms at 300,000ms (5 minutes) to prevent outlier pollution."""
        return min(v, 300_000.0)

    model_config = {
        "json_schema_extra": {
            "example": {
                "hour_of_day": 3,
                "response_time_ms": 5000.0,
                "error_code": 4,
                "log_level_encoded": 3,
                "request_count_last_60s": 1245,
                "service_id_encoded": 2,
            }
        }
    }


# ---------------------------------------------------------------------------
# Output: Single Prediction
# ---------------------------------------------------------------------------


class PredictResponse(BaseModel):
    """
    Anomaly detection result for a single feature vector.

    Fields:
      prediction    — scikit-learn convention: 1=normal, -1=anomaly
      anomaly_score — raw decision function score (negative = anomaly)
      is_anomaly    — boolean classification based on threshold
      threshold_used — the decision threshold applied
    """

    prediction: int = Field(
        ...,
        description="Scikit-learn IsolationForest prediction: 1 = normal, -1 = anomaly",
    )

    anomaly_score: float = Field(
        ...,
        description=(
            "Raw decision function score from IsolationForest. "
            "Negative values indicate anomalies; more negative = more anomalous. "
            "Positive values indicate normal samples."
        ),
    )

    is_anomaly: bool = Field(
        ...,
        description=(
            "True if the sample is classified as an anomaly "
            "(anomaly_score < threshold_used)."
        ),
    )

    threshold_used: float = Field(
        ...,
        description="The decision score threshold used to classify this sample.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "prediction": -1,
                "anomaly_score": -0.3124,
                "is_anomaly": True,
                "threshold_used": 0.0,
            }
        }
    }


# ---------------------------------------------------------------------------
# Input: Batch Prediction Request
# ---------------------------------------------------------------------------


class BatchPredictRequest(BaseModel):
    """
    Request body for POST /predict/batch.
    Accepts between 1 and 500 feature vectors in a single request.
    """

    features: list[FeatureVector] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of feature vectors to score (1–500 per request)",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "features": [
                    {
                        "hour_of_day": 10,
                        "response_time_ms": 120.0,
                        "error_code": 1,
                        "log_level_encoded": 1,
                        "request_count_last_60s": 150,
                        "service_id_encoded": 0,
                    },
                    {
                        "hour_of_day": 3,
                        "response_time_ms": 8000.0,
                        "error_code": 4,
                        "log_level_encoded": 3,
                        "request_count_last_60s": 1800,
                        "service_id_encoded": 2,
                    },
                ]
            }
        }
    }


# ---------------------------------------------------------------------------
# Output: Batch Prediction Response
# ---------------------------------------------------------------------------


class BatchPredictResponse(BaseModel):
    """
    Response body for POST /predict/batch.
    Contains a result for each input feature vector, in the same order.
    """

    total: int = Field(
        ...,
        ge=0,
        description="Total number of feature vectors scored",
    )

    anomaly_count: int = Field(
        ...,
        ge=0,
        description="Number of entries classified as anomalies",
    )

    results: list[PredictResponse] = Field(
        ...,
        description=(
            "List of prediction results, one per input feature vector, "
            "in the same order as the request."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "total": 2,
                "anomaly_count": 1,
                "results": [
                    {
                        "prediction": 1,
                        "anomaly_score": 0.0821,
                        "is_anomaly": False,
                        "threshold_used": 0.0,
                    },
                    {
                        "prediction": -1,
                        "anomaly_score": -0.2943,
                        "is_anomaly": True,
                        "threshold_used": 0.0,
                    },
                ],
            }
        }
    }


# ---------------------------------------------------------------------------
# Output: Model Status
# ---------------------------------------------------------------------------


class ModelStatusResponse(BaseModel):
    """
    Response body for GET /model/status.
    Returns metadata about the currently loaded ML model.
    """

    status: str = Field(
        ...,
        description="Model load status: 'loaded' or 'not_loaded'",
    )

    model_type: str = Field(
        ...,
        description="Algorithm name (e.g. 'IsolationForest')",
    )

    n_estimators: int = Field(
        ...,
        ge=0,
        description="Number of isolation trees in the ensemble",
    )

    contamination: float | str = Field(
        ...,
        description=(
            "Contamination parameter — expected fraction of anomalies in training data. "
            "Can be a float (e.g. 0.05) or 'auto'."
        ),
    )

    n_features: int = Field(
        ...,
        ge=0,
        description="Number of input features the model expects",
    )

    trained_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 UTC timestamp when the model was trained (if available)",
    )

    model_path: str = Field(
        ...,
        description="Filesystem path from which the model was loaded",
    )

    scaler_path: Optional[str] = Field(
        default=None,
        description="Filesystem path from which the StandardScaler was loaded",
    )

    anomaly_threshold: float = Field(
        ...,
        description=(
            "The decision score threshold below which a sample is classified as anomalous."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "loaded",
                "model_type": "IsolationForest",
                "n_estimators": 100,
                "contamination": 0.05,
                "n_features": 6,
                "trained_at": "2024-01-15T02:00:00+00:00",
                "model_path": "/app/models/isolation_forest.joblib",
                "scaler_path": "/app/models/scaler.joblib",
                "anomaly_threshold": 0.0,
            }
        }
    }
