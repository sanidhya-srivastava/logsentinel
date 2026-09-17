"""
LogSentinel — ML Model Evaluation Script
==========================================
Loads train/test data, runs the trained Isolation Forest model,
and reports a full set of detection metrics.

Usage:
    python ml/evaluate.py [--model PATH] [--data PATH] [--output PATH]

Example:
    python ml/evaluate.py \
        --model ml/models/isolation_forest.joblib \
        --output ml/models/evaluation_report.json
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Feature columns matching train.py
FEATURE_COLUMNS = [
    "hour_of_day",
    "response_time_ms",
    "error_code",
    "log_level_encoded",
    "request_count_last_60s",
    "service_id_encoded",
]

LOG_LEVEL_MAP = {
    "DEBUG": 0,
    "INFO": 1,
    "WARN": 2,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}
SERVICE_MAP = {
    "auth-service": 0,
    "payment-service": 1,
    "user-service": 2,
    "order-service": 3,
    "api-gateway": 4,
    "unknown": 5,
}


def generate_evaluation_dataset(
    n_normal: int = 1500, n_anomalous: int = 150, seed: int = 99
) -> pd.DataFrame:
    """Generate synthetic evaluation data with known labels for metric computation."""
    rng = np.random.default_rng(seed)

    # Normal logs
    normal = {
        "hour_of_day": rng.integers(0, 24, n_normal),
        "response_time_ms": rng.normal(180, 40, n_normal).clip(10, 500),
        "error_code": rng.choice(
            [0, 200, 201, 302], n_normal, p=[0.6, 0.25, 0.08, 0.07]
        ),
        "log_level_encoded": rng.choice([0, 1, 2], n_normal, p=[0.1, 0.8, 0.1]),
        "request_count_last_60s": rng.integers(5, 80, n_normal),
        "service_id_encoded": rng.integers(0, 5, n_normal),
        "true_label": np.ones(n_normal, dtype=int),  # 1 = normal
    }

    # Anomalous logs
    anomalous = {
        "hour_of_day": rng.integers(0, 24, n_anomalous),
        "response_time_ms": rng.choice(
            [rng.normal(2500, 300, n_anomalous), rng.normal(5, 2, n_anomalous)],
        ).flatten()[:n_anomalous],
        "error_code": rng.choice([500, 503, 504, 429], n_anomalous),
        "log_level_encoded": rng.choice([3, 4], n_anomalous, p=[0.6, 0.4]),
        "request_count_last_60s": rng.integers(150, 500, n_anomalous),
        "service_id_encoded": rng.integers(0, 5, n_anomalous),
        "true_label": -np.ones(n_anomalous, dtype=int),  # -1 = anomaly
    }

    df_normal = pd.DataFrame(normal)
    df_anomalous = pd.DataFrame(anomalous)
    df_anomalous["response_time_ms"] = rng.uniform(1800, 8000, n_anomalous)

    df = pd.concat([df_normal, df_anomalous], ignore_index=True)
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)

    logger.info(
        "Evaluation dataset generated",
        extra={"total": len(df), "normal": n_normal, "anomalous": n_anomalous},
    )
    return df


def load_model(model_path: str) -> object:
    """Load a trained model from a joblib file."""
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    model = joblib.load(path)
    logger.info("Model loaded", extra={"path": str(path)})
    return model


def evaluate(
    model_path: str,
    data_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> dict:
    """
    Run model evaluation and return a metrics report dict.

    Args:
        model_path:  Path to the saved joblib model artifact.
        data_path:   Optional CSV path with feature columns + true_label column.
                     If None, uses synthetic evaluation data.
        output_path: Optional path to write the JSON evaluation report.

    Returns:
        dict containing all evaluation metrics.
    """
    # ── Load model ────────────────────────────────────────────────────────────
    model = load_model(model_path)

    # ── Load or generate evaluation data ─────────────────────────────────────
    if data_path:
        logger.info("Loading evaluation data", extra={"path": data_path})
        df = pd.read_csv(data_path)
        if "true_label" not in df.columns:
            raise ValueError(
                "CSV must contain 'true_label' column (-1=anomaly, 1=normal)"
            )
    else:
        logger.info("Using synthetic evaluation dataset")
        df = generate_evaluation_dataset()

    # Validate features
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")

    X = df[FEATURE_COLUMNS].values
    y_true = df["true_label"].values  # -1 = anomaly, 1 = normal

    logger.info(
        "Evaluation dataset summary",
        extra={
            "total": len(df),
            "anomalies": int((y_true == -1).sum()),
            "normal": int((y_true == 1).sum()),
        },
    )

    # ── Predict ───────────────────────────────────────────────────────────────
    logger.info("Running model inference...")
    y_pred = model.predict(X)  # -1 = anomaly, 1 = normal
    y_scores = model.decision_function(X)  # lower = more anomalous

    # ── Metrics ───────────────────────────────────────────────────────────────
    # Convert to binary: 1 = anomaly for sklearn metrics
    y_true_binary = (y_true == -1).astype(int)
    y_pred_binary = (y_pred == -1).astype(int)

    precision = precision_score(y_true_binary, y_pred_binary, zero_division=0)
    recall = recall_score(y_true_binary, y_pred_binary, zero_division=0)
    f1 = f1_score(y_true_binary, y_pred_binary, zero_division=0)

    try:
        roc_auc = roc_auc_score(
            y_true_binary, -y_scores
        )  # invert: lower score = more anomalous
    except ValueError:
        roc_auc = None
        logger.warning(
            "ROC AUC could not be computed (possibly single class in labels)"
        )

    cm = confusion_matrix(y_true_binary, y_pred_binary)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, 0)

    cls_report = classification_report(
        y_true_binary,
        y_pred_binary,
        target_names=["normal", "anomaly"],
        output_dict=True,
    )

    # Score distribution
    score_stats = {
        "mean": float(np.mean(y_scores)),
        "std": float(np.std(y_scores)),
        "min": float(np.min(y_scores)),
        "max": float(np.max(y_scores)),
        "p10": float(np.percentile(y_scores, 10)),
        "p25": float(np.percentile(y_scores, 25)),
        "p50": float(np.percentile(y_scores, 50)),
        "p75": float(np.percentile(y_scores, 75)),
        "p90": float(np.percentile(y_scores, 90)),
    }

    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "model_path": str(model_path),
        "dataset": {
            "total_samples": int(len(df)),
            "normal_samples": int((y_true == 1).sum()),
            "anomaly_samples": int((y_true == -1).sum()),
            "source": data_path or "synthetic",
        },
        "metrics": {
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "f1_score": round(float(f1), 4),
            "roc_auc": round(float(roc_auc), 4) if roc_auc is not None else None,
        },
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
        "classification_report": cls_report,
        "score_distribution": score_stats,
    }

    # ── Log summary ───────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Evaluation Results:")
    logger.info(f"  Precision : {precision:.4f}")
    logger.info(f"  Recall    : {recall:.4f}")
    logger.info(f"  F1 Score  : {f1:.4f}")
    logger.info(f"  ROC AUC   : {roc_auc:.4f}" if roc_auc else "  ROC AUC  : N/A")
    logger.info(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    logger.info("=" * 60)

    # ── Save report ───────────────────────────────────────────────────────────
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(report, f, indent=2)
        logger.info("Evaluation report saved", extra={"path": str(out)})

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the LogSentinel Isolation Forest model",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model",
        type=str,
        default="ml/models/isolation_forest.joblib",
        help="Path to the trained model joblib file",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=None,
        help="Path to evaluation CSV (optional; uses synthetic data if omitted)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="ml/models/evaluation_report.json",
        help="Path to write the JSON evaluation report",
    )
    args = parser.parse_args()

    try:
        report = evaluate(
            model_path=args.model,
            data_path=args.data,
            output_path=args.output,
        )
        # Print summary to stdout
        print("\n=== LogSentinel Model Evaluation Summary ===")
        metrics = report["metrics"]
        print(f"  Precision : {metrics['precision']}")
        print(f"  Recall    : {metrics['recall']}")
        print(f"  F1 Score  : {metrics['f1_score']}")
        print(f"  ROC AUC   : {metrics.get('roc_auc', 'N/A')}")
        cm = report["confusion_matrix"]
        print(f"  True Pos  : {cm['true_positive']}")
        print(f"  False Pos : {cm['false_positive']}")
        print(f"  True Neg  : {cm['true_negative']}")
        print(f"  False Neg : {cm['false_negative']}")
        if args.output:
            print(f"\n  Report saved to: {args.output}")
    except FileNotFoundError as exc:
        logger.error(str(exc))
        logger.error("Run `python ml/train.py` first to train the model.")
        sys.exit(1)
    except Exception as exc:
        logger.exception("Evaluation failed", exc_info=exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
