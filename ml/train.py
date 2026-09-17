"""
LogSentinel — ML Model Training Script
=======================================
Generates synthetic log feature data, trains an Isolation Forest
anomaly detection model, and saves the model + scaler to disk.

Usage:
    python ml/train.py
    # or via Makefile:
    make train

Output files (saved to ml/models/):
    isolation_forest.joblib  — trained IsolationForest model
    scaler.joblib            — fitted StandardScaler
    training_metadata.json   — training run metadata

Feature vector schema (6 features):
    hour_of_day             int   0–23
    response_time_ms        float milliseconds
    error_code              int   bucket-encoded (0–5)
    log_level_encoded       int   DEBUG=0 INFO=1 WARN=2 ERROR=3 CRITICAL=4
    request_count_last_60s  int   rolling 60s window count
    service_id_encoded      int   label-encoded service ID
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("logsentinel.ml.train")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
MODELS_DIR = SCRIPT_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODELS_DIR / "isolation_forest.joblib"
SCALER_PATH = MODELS_DIR / "scaler.joblib"
METADATA_PATH = MODELS_DIR / "training_metadata.json"

# ---------------------------------------------------------------------------
# Feature column names (order is canonical — must match inference)
# ---------------------------------------------------------------------------
FEATURE_COLUMNS = [
    "hour_of_day",
    "response_time_ms",
    "error_code",
    "log_level_encoded",
    "request_count_last_60s",
    "service_id_encoded",
]

# ---------------------------------------------------------------------------
# Default hyperparameters
# ---------------------------------------------------------------------------
DEFAULT_N_SAMPLES_NORMAL = 47_500  # 95% normal traffic
DEFAULT_N_SAMPLES_ANOMALY = 2_500  # 5% anomalous traffic
DEFAULT_N_ESTIMATORS = 100
DEFAULT_CONTAMINATION = 0.05
DEFAULT_MAX_SAMPLES = "auto"
DEFAULT_RANDOM_STATE = 42


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------


def generate_normal_traffic(
    n_samples: int,
    rng: np.random.Generator,
    n_services: int = 10,
) -> pd.DataFrame:
    """
    Generate synthetic feature vectors representing normal system behaviour.

    Normal traffic characteristics:
      - Requests spread across all hours (peak during business hours 8–18)
      - Response times mostly under 500ms (right-skewed, realistic)
      - Mostly success (2xx) responses → error_code bucket = 1
      - Mostly INFO level logs
      - Steady request counts (50–300/min)
      - All known services
    """
    n = n_samples

    # hour_of_day: bimodal distribution — business hours peak
    # Mix of uniform background + Gaussian peaks at 10 and 15
    hour_uniform = rng.integers(0, 24, size=n)
    hour_peak_morning = np.clip(
        rng.normal(loc=10, scale=2.5, size=n).astype(int), 0, 23
    )
    hour_peak_afternoon = np.clip(
        rng.normal(loc=15, scale=2.0, size=n).astype(int), 0, 23
    )
    mask_morning = rng.random(n) < 0.35
    mask_afternoon = rng.random(n) < 0.30
    hour_of_day = hour_uniform.copy()
    hour_of_day[mask_morning] = hour_peak_morning[mask_morning]
    hour_of_day[mask_afternoon] = hour_peak_afternoon[mask_afternoon]
    hour_of_day = np.clip(hour_of_day, 0, 23)

    # response_time_ms: log-normal distribution centred around 100ms
    # Most requests: 10ms–400ms; rare slow outliers up to ~1000ms
    response_time_ms = np.clip(
        rng.lognormal(mean=4.5, sigma=0.8, size=n),  # median ~90ms
        1.0,
        2000.0,
    )

    # error_code: mostly success (bucket 1 = 2xx)
    # Small fraction of 4xx (bucket 3) and 5xx (bucket 4)
    error_code_probs = [0.02, 0.88, 0.02, 0.05, 0.02, 0.01]  # buckets 0–5
    error_code = rng.choice(6, size=n, p=error_code_probs)

    # log_level_encoded: mostly INFO (1), some DEBUG (0), few WARN (2)
    level_probs = [0.10, 0.72, 0.12, 0.05, 0.01]  # DEBUG INFO WARN ERROR CRITICAL
    log_level_encoded = rng.choice(5, size=n, p=level_probs)

    # request_count_last_60s: steady moderate load
    request_count_last_60s = np.clip(
        rng.normal(loc=150, scale=60, size=n).astype(int),
        1,
        500,
    )

    # service_id_encoded: distributed across known services
    service_id_encoded = rng.integers(0, n_services, size=n)

    return pd.DataFrame(
        {
            "hour_of_day": hour_of_day.astype(int),
            "response_time_ms": response_time_ms.astype(float),
            "error_code": error_code.astype(int),
            "log_level_encoded": log_level_encoded.astype(int),
            "request_count_last_60s": request_count_last_60s.astype(int),
            "service_id_encoded": service_id_encoded.astype(int),
        }
    )


def generate_anomalous_traffic(
    n_samples: int,
    rng: np.random.Generator,
    n_services: int = 10,
) -> pd.DataFrame:
    """
    Generate synthetic feature vectors representing anomalous system behaviour.

    Anomaly types injected:
      Type A (30%): Latency spike — extremely high response times
      Type B (25%): Error storm  — sudden burst of 5xx errors + high log level
      Type C (20%): Traffic spike — abnormally high request rate
      Type D (15%): Off-hours activity — unusual hour + elevated errors
      Type E (10%): Service degradation — combined latency + errors + low traffic
    """
    n = n_samples
    anomaly_types = rng.choice(
        ["A", "B", "C", "D", "E"], size=n, p=[0.30, 0.25, 0.20, 0.15, 0.10]
    )

    records = []

    for anomaly_type in anomaly_types:
        if anomaly_type == "A":
            # Latency spike
            record = {
                "hour_of_day": int(rng.integers(8, 18)),
                "response_time_ms": float(
                    np.clip(rng.lognormal(mean=8.0, sigma=0.7), 3000.0, 60000.0)
                ),
                "error_code": int(rng.choice([0, 4], p=[0.4, 0.6])),
                "log_level_encoded": int(rng.choice([2, 3, 4], p=[0.3, 0.5, 0.2])),
                "request_count_last_60s": int(np.clip(rng.normal(120, 40), 1, 400)),
                "service_id_encoded": int(rng.integers(0, n_services)),
            }
        elif anomaly_type == "B":
            # Error storm
            record = {
                "hour_of_day": int(rng.integers(0, 24)),
                "response_time_ms": float(
                    np.clip(rng.lognormal(mean=6.0, sigma=1.0), 200.0, 10000.0)
                ),
                "error_code": 4,  # 5xx bucket
                "log_level_encoded": int(rng.choice([3, 4], p=[0.6, 0.4])),
                "request_count_last_60s": int(np.clip(rng.normal(100, 50), 1, 300)),
                "service_id_encoded": int(rng.integers(0, n_services)),
            }
        elif anomaly_type == "C":
            # Traffic spike
            record = {
                "hour_of_day": int(rng.integers(0, 24)),
                "response_time_ms": float(
                    np.clip(rng.lognormal(mean=5.5, sigma=0.9), 100.0, 5000.0)
                ),
                "error_code": int(rng.choice([1, 3, 4], p=[0.5, 0.3, 0.2])),
                "log_level_encoded": int(rng.choice([1, 2, 3], p=[0.4, 0.4, 0.2])),
                "request_count_last_60s": int(
                    np.clip(rng.normal(loc=900, scale=200), 600, 3000)
                ),
                "service_id_encoded": int(rng.integers(0, n_services)),
            }
        elif anomaly_type == "D":
            # Off-hours unusual activity
            hour = int(rng.choice([1, 2, 3, 4, 23], p=[0.2, 0.2, 0.2, 0.2, 0.2]))
            record = {
                "hour_of_day": hour,
                "response_time_ms": float(
                    np.clip(rng.lognormal(mean=7.0, sigma=0.8), 500.0, 20000.0)
                ),
                "error_code": int(rng.choice([3, 4], p=[0.5, 0.5])),
                "log_level_encoded": int(rng.choice([2, 3, 4], p=[0.2, 0.5, 0.3])),
                "request_count_last_60s": int(np.clip(rng.normal(50, 30), 1, 200)),
                "service_id_encoded": int(rng.integers(0, n_services)),
            }
        else:  # type E
            # Service degradation
            record = {
                "hour_of_day": int(rng.integers(0, 24)),
                "response_time_ms": float(
                    np.clip(rng.lognormal(mean=7.5, sigma=0.5), 2000.0, 30000.0)
                ),
                "error_code": 4,  # 5xx bucket
                "log_level_encoded": int(rng.choice([3, 4], p=[0.5, 0.5])),
                "request_count_last_60s": int(np.clip(rng.normal(20, 15), 0, 80)),
                "service_id_encoded": int(rng.integers(0, n_services)),
            }

        records.append(record)

    return pd.DataFrame(records)


def generate_training_data(
    n_normal: int,
    n_anomaly: int,
    random_state: int = 42,
) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Generate the full training dataset (normal + anomalous samples).

    Returns:
        X: Feature DataFrame (n_samples, 6)
        y: Label array — 1 = normal, -1 = anomaly (sklearn convention)
    """
    rng = np.random.default_rng(random_state)

    logger.info(
        "Generating synthetic training data",
        extra={
            "n_normal": n_normal,
            "n_anomaly": n_anomaly,
            "total": n_normal + n_anomaly,
        },
    )

    df_normal = generate_normal_traffic(n_normal, rng)
    df_normal["_label"] = 1

    df_anomaly = generate_anomalous_traffic(n_anomaly, rng)
    df_anomaly["_label"] = -1

    df_all = pd.concat([df_normal, df_anomaly], ignore_index=True)

    # Shuffle the dataset
    df_all = df_all.sample(frac=1, random_state=random_state).reset_index(drop=True)

    y = df_all["_label"].values
    X = df_all[FEATURE_COLUMNS].copy()

    logger.info(
        "Training data generated",
        extra={
            "total_samples": len(X),
            "normal_samples": int((y == 1).sum()),
            "anomaly_samples": int((y == -1).sum()),
            "anomaly_rate_pct": round(float((y == -1).mean()) * 100, 2),
        },
    )

    return X, y


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_model(
    X_train: pd.DataFrame,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    contamination: float = DEFAULT_CONTAMINATION,
    max_samples: str | int = DEFAULT_MAX_SAMPLES,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> tuple[IsolationForest, StandardScaler]:
    """
    Fit a StandardScaler and train an Isolation Forest on the training data.

    Args:
        X_train:       Training feature DataFrame (n_samples, 6).
        n_estimators:  Number of isolation trees to build.
        contamination: Expected fraction of anomalies in training data.
        max_samples:   Number of samples per tree ('auto' or int).
        random_state:  Reproducibility seed.

    Returns:
        Tuple of (trained IsolationForest, fitted StandardScaler).
    """
    logger.info(
        "Fitting StandardScaler on training features",
        extra={"n_samples": len(X_train), "n_features": len(FEATURE_COLUMNS)},
    )
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)

    logger.info(
        "Training Isolation Forest",
        extra={
            "n_estimators": n_estimators,
            "contamination": contamination,
            "max_samples": max_samples,
            "random_state": random_state,
        },
    )

    start_ts = time.perf_counter()
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples=max_samples,
        max_features=1.0,
        bootstrap=False,
        n_jobs=-1,  # use all available CPU cores
        random_state=random_state,
        verbose=0,
    )
    model.fit(X_scaled)
    elapsed = time.perf_counter() - start_ts

    # Stamp training timestamp onto the model object for retrieval by ModelManager
    model._trained_at = datetime.now(timezone.utc).isoformat()
    model._feature_columns = FEATURE_COLUMNS

    logger.info(
        "Isolation Forest training complete",
        extra={
            "n_estimators": n_estimators,
            "training_time_s": round(elapsed, 3),
            "n_features_in": model.n_features_in_,
        },
    )

    return model, scaler


# ---------------------------------------------------------------------------
# Evaluation (quick sanity check during training)
# ---------------------------------------------------------------------------


def quick_evaluate(
    model: IsolationForest,
    scaler: StandardScaler,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
) -> dict:
    """
    Run a quick sanity-check evaluation on the test split.
    Full evaluation is handled by ml/evaluate.py.

    Returns a dict with precision, recall, f1, and anomaly detection rate.
    """
    from sklearn.metrics import classification_report, confusion_matrix

    X_scaled = scaler.transform(X_test)
    y_pred = model.predict(X_scaled)

    # sklearn convention: 1=normal, -1=anomaly
    # Treat -1 as "positive" class for precision/recall
    from sklearn.metrics import f1_score, precision_score, recall_score

    precision = precision_score(y_test, y_pred, pos_label=-1, zero_division=0)
    recall = recall_score(y_test, y_pred, pos_label=-1, zero_division=0)
    f1 = f1_score(y_test, y_pred, pos_label=-1, zero_division=0)

    anomaly_rate = float((y_pred == -1).mean())
    true_anomaly_rate = float((y_test == -1).mean())

    cm = confusion_matrix(y_test, y_pred, labels=[1, -1]).tolist()

    report = classification_report(
        y_test, y_pred, target_names=["normal", "anomaly"], zero_division=0
    )

    metrics = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "anomaly_rate_predicted": round(anomaly_rate, 4),
        "anomaly_rate_true": round(true_anomaly_rate, 4),
        "confusion_matrix": cm,
        "test_samples": len(y_test),
    }

    logger.info("=" * 60)
    logger.info("QUICK EVALUATION RESULTS (test split)")
    logger.info("=" * 60)
    logger.info(f"\n{report}")
    logger.info(f"Precision: {precision:.4f} | Recall: {recall:.4f} | F1: {f1:.4f}")
    logger.info(
        f"Predicted anomaly rate: {anomaly_rate:.2%} (true: {true_anomaly_rate:.2%})"
    )
    logger.info("=" * 60)

    return metrics


# ---------------------------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------------------------


def save_artifacts(
    model: IsolationForest,
    scaler: StandardScaler,
    metrics: dict,
    args: argparse.Namespace,
    training_start_ts: float,
) -> None:
    """Save the trained model, scaler, and metadata to disk."""
    # --- Save model ---
    logger.info(f"Saving model to {MODEL_PATH}")
    joblib.dump(model, MODEL_PATH, compress=3)

    # --- Save scaler ---
    logger.info(f"Saving scaler to {SCALER_PATH}")
    joblib.dump(scaler, SCALER_PATH, compress=3)

    # --- Save metadata ---
    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_duration_s": round(time.perf_counter() - training_start_ts, 3),
        "model_path": str(MODEL_PATH),
        "scaler_path": str(SCALER_PATH),
        "algorithm": "IsolationForest",
        "hyperparameters": {
            "n_estimators": args.n_estimators,
            "contamination": args.contamination,
            "max_samples": args.max_samples,
            "random_state": args.random_state,
        },
        "training_data": {
            "n_normal": args.n_normal,
            "n_anomaly": args.n_anomaly,
            "total": args.n_normal + args.n_anomaly,
            "anomaly_rate_pct": round(
                args.n_anomaly / (args.n_normal + args.n_anomaly) * 100, 2
            ),
        },
        "features": FEATURE_COLUMNS,
        "n_features": len(FEATURE_COLUMNS),
        "evaluation": metrics,
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Training metadata saved to {METADATA_PATH}")

    # Confirm file sizes
    model_size_kb = MODEL_PATH.stat().st_size / 1024
    scaler_size_kb = SCALER_PATH.stat().st_size / 1024
    logger.info(
        f"Artifact sizes — model: {model_size_kb:.1f} KB, "
        f"scaler: {scaler_size_kb:.1f} KB"
    )


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the LogSentinel Isolation Forest anomaly detection model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--n-normal",
        type=int,
        default=DEFAULT_N_SAMPLES_NORMAL,
        help="Number of normal training samples to generate",
    )
    parser.add_argument(
        "--n-anomaly",
        type=int,
        default=DEFAULT_N_SAMPLES_ANOMALY,
        help="Number of anomalous training samples to generate",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=DEFAULT_N_ESTIMATORS,
        help="Number of isolation trees",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=DEFAULT_CONTAMINATION,
        help="Expected fraction of anomalies in training data (0.0–0.5)",
    )
    parser.add_argument(
        "--max-samples",
        default=DEFAULT_MAX_SAMPLES,
        help="Number of samples to draw for each tree ('auto' or int)",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=DEFAULT_RANDOM_STATE,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--test-split",
        type=float,
        default=0.20,
        help="Fraction of data to hold out for evaluation (0.0–0.5)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(MODELS_DIR),
        help="Directory to save model artifacts",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip the quick evaluation step after training",
    )

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # Override output paths if --output-dir is specified
    global MODEL_PATH, SCALER_PATH, METADATA_PATH
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    MODEL_PATH = output_dir / "isolation_forest.joblib"
    SCALER_PATH = output_dir / "scaler.joblib"
    METADATA_PATH = output_dir / "training_metadata.json"

    # Handle max_samples type (could be 'auto' string or int)
    max_samples = args.max_samples
    if max_samples != "auto":
        try:
            max_samples = int(max_samples)
        except ValueError:
            logger.warning(
                f"Invalid --max-samples value '{max_samples}' — using 'auto'"
            )
            max_samples = "auto"

    training_start = time.perf_counter()

    logger.info("=" * 60)
    logger.info("LogSentinel — Isolation Forest Model Training")
    logger.info("=" * 60)
    logger.info(f"Output directory : {output_dir}")
    logger.info(f"Normal samples   : {args.n_normal:,}")
    logger.info(f"Anomaly samples  : {args.n_anomaly:,}")
    logger.info(f"Contamination    : {args.contamination}")
    logger.info(f"N estimators     : {args.n_estimators}")
    logger.info(f"Random state     : {args.random_state}")
    logger.info("=" * 60)

    # --- Generate data ---
    X, y = generate_training_data(
        n_normal=args.n_normal,
        n_anomaly=args.n_anomaly,
        random_state=args.random_state,
    )

    # --- Train / test split ---
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=args.test_split,
        random_state=args.random_state,
        stratify=y,
    )
    logger.info(f"Train/test split — train: {len(X_train):,}, test: {len(X_test):,}")

    # --- Train ---
    # IsolationForest is an unsupervised algorithm: train on ALL data
    # (including anomalies) — the contamination parameter tells it
    # what fraction to expect.
    model, scaler = train_model(
        X_train=X_train,
        n_estimators=args.n_estimators,
        contamination=args.contamination,
        max_samples=max_samples,
        random_state=args.random_state,
    )

    # --- Evaluate ---
    metrics = {}
    if not args.skip_eval:
        metrics = quick_evaluate(model, scaler, X_test, y_test)
    else:
        logger.info("Skipping evaluation (--skip-eval flag set)")

    # --- Save ---
    save_artifacts(
        model=model,
        scaler=scaler,
        metrics=metrics,
        args=args,
        training_start_ts=training_start,
    )

    total_elapsed = time.perf_counter() - training_start
    logger.info("=" * 60)
    logger.info(
        f"Training complete in {total_elapsed:.2f}s | "
        f"F1: {metrics.get('f1_score', 'N/A')} | "
        f"Precision: {metrics.get('precision', 'N/A')} | "
        f"Recall: {metrics.get('recall', 'N/A')}"
    )
    logger.info(f"Model saved to: {MODEL_PATH}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
