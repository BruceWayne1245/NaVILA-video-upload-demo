"""Leakage-safe training, calibration, thresholding, and evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .bundle import ReliabilityBundle
from .calibration import PlattCalibrator, trusted_threshold
from .schema import CATEGORICAL_FEATURES, LABEL_COLUMNS, NUMERIC_FEATURES, SCHEMA_VERSION
from .vectorizer import FeatureVectorizer


HEAD_LABELS = {
    "bearing": "label_bearing_bad",
    "distance": "label_distance_bad",
    "pose": "label_pose_bad",
}


def _coerce_row(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for name in NUMERIC_FEATURES:
        try:
            result[name] = float(row[name]) if row.get(name, "") != "" else None
        except ValueError:
            result[name] = None
    for name in LABEL_COLUMNS + ("episode_id", "attempt", "anchor_index", "outbound_success", "return_success"):
        result[name] = int(float(row[name]))
    result["sample_weight"] = float(row.get("sample_weight") or 1.0)
    for name in CATEGORICAL_FEATURES:
        result[name] = row.get(name) or "__missing__"
    return result


def read_dataset(path: str | Path) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = [_coerce_row(row) for row in csv.DictReader(handle)]
    schemas = {row.get("schema_version") for row in rows}
    if schemas != {SCHEMA_VERSION}:
        raise ValueError(f"unexpected dataset schema(s): {sorted(schemas)}")
    return rows


def strict_chronological_split(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    split_cfg = config["split"]
    train_batches = set(split_cfg["train_batches"])
    calibration_batches = set(split_cfg["calibration_batches"])
    test_batches = set(split_cfg["test_batches"])
    ids_by_partition = {
        "train_source": {row["episode_id"] for row in rows if row["batch"] in train_batches},
        "calibration_source": {row["episode_id"] for row in rows if row["batch"] in calibration_batches},
        "test": {row["episode_id"] for row in rows if row["batch"] in test_batches},
    }
    # Reserve every latest-batch episode for test. From the middle batch, only
    # episode identities absent from test may calibrate. Training receives only
    # oldest-batch identities absent from both later partitions.
    calibration_ids = ids_by_partition["calibration_source"] - ids_by_partition["test"]
    train_ids = ids_by_partition["train_source"] - ids_by_partition["test"] - calibration_ids
    partition = {
        "train": [row for row in rows if row["batch"] in train_batches and row["episode_id"] in train_ids],
        "calibration": [row for row in rows if row["batch"] in calibration_batches and row["episode_id"] in calibration_ids],
        "test": [row for row in rows if row["batch"] in test_batches],
    }
    episode_sets = {name: {row["episode_id"] for row in values} for name, values in partition.items()}
    overlaps = {
        "train_calibration": sorted(episode_sets["train"] & episode_sets["calibration"]),
        "train_test": sorted(episode_sets["train"] & episode_sets["test"]),
        "calibration_test": sorted(episode_sets["calibration"] & episode_sets["test"]),
    }
    if any(overlaps.values()):
        raise AssertionError(f"episode leakage detected: {overlaps}")
    for name, values in partition.items():
        if not values:
            raise ValueError(f"strict chronological {name} partition is empty")
    audit = {
        "strategy": "strict_chronological_episode_disjoint",
        "rows": {name: len(values) for name, values in partition.items()},
        "episode_ids": {name: sorted(values) for name, values in episode_sets.items()},
        "overlaps": overlaps,
    }
    return partition, audit


def _arrays(rows: list[dict[str, Any]], vectorizer: FeatureVectorizer, label: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = vectorizer.transform(rows)
    target = np.asarray([row[label] for row in rows], dtype=np.int64)
    weight = np.asarray([row["sample_weight"] for row in rows], dtype=np.float64)
    return matrix, target, weight


def _metric_bundle(target: np.ndarray, probability: np.ndarray, weight: np.ndarray, threshold: float) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    result: dict[str, Any] = {
        "rows": int(target.size),
        "positive_rate": float(np.average(target, weights=weight)),
        "brier": float(brier_score_loss(target, probability, sample_weight=weight)),
    }
    result["roc_auc"] = float(roc_auc_score(target, probability, sample_weight=weight)) if np.unique(target).size > 1 else None
    result["average_precision"] = float(average_precision_score(target, probability, sample_weight=weight)) if np.unique(target).size > 1 else None
    trusted = probability <= threshold
    result["trusted_threshold"] = float(threshold)
    result["trusted_coverage"] = float(np.average(trusted, weights=weight))
    result["trusted_bad_rate"] = float(np.average(target[trusted], weights=weight[trusted])) if trusted.any() else None
    return result


def _per_episode_metrics(rows: list[dict[str, Any]], target: np.ndarray, probability: np.ndarray, threshold: float) -> list[dict[str, Any]]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[int(row["episode_id"])].append(index)
    result = []
    for episode_id, indices in sorted(grouped.items()):
        y = target[indices]
        p = probability[indices]
        trusted = p <= threshold
        result.append({
            "episode_id": episode_id,
            "rows": len(indices),
            "positive_rate": float(np.mean(y)),
            "mean_probability": float(np.mean(p)),
            "trusted_coverage": float(np.mean(trusted)),
            "trusted_bad_rate": float(np.mean(y[trusted])) if trusted.any() else None,
        })
    return result


def train_bundle(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    dataset_path: str | Path,
) -> tuple[ReliabilityBundle, dict[str, Any]]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    import sklearn

    partition, split_audit = strict_chronological_split(rows, config)
    vectorizer = FeatureVectorizer().fit(partition["train"])
    x_train = vectorizer.transform(partition["train"])
    weights_train = np.asarray([row["sample_weight"] for row in partition["train"]], dtype=float)
    models = {
        "bearing": LogisticRegression(C=0.5, max_iter=2000, solver="liblinear", random_state=0),
        "distance": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_depth=6, l2_regularization=1.0, random_state=0),
        "pose": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_depth=6, l2_regularization=1.0, random_state=0),
    }
    calibrators: dict[str, PlattCalibrator] = {}
    thresholds = {}
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sklearn_version": sklearn.__version__,
        "split": split_audit,
        "feature_names": vectorizer.feature_names,
        "heads": {},
    }
    targets = config["trusted_bad_rate_targets"]
    dataset_digest = hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest()
    for head, label in HEAD_LABELS.items():
        y_train = np.asarray([row[label] for row in partition["train"]], dtype=int)
        if np.unique(y_train).size < 2:
            raise ValueError(f"training partition has only one class for {head}")
        models[head].fit(x_train, y_train, sample_weight=weights_train)
        x_cal, y_cal, w_cal = _arrays(partition["calibration"], vectorizer, label)
        raw_cal = models[head].predict_proba(x_cal)[:, 1]
        calibrator = PlattCalibrator().fit(raw_cal, y_cal, w_cal)
        calibrated_cal = calibrator.predict(raw_cal)
        threshold = trusted_threshold(calibrated_cal, y_cal, w_cal, float(targets[head]))
        calibrators[head] = calibrator
        thresholds[head] = threshold
        head_report = {
            "model": type(models[head]).__name__,
            "calibrator": {"type": "weighted_monotonic_platt", "slope": calibrator.slope, "intercept": calibrator.intercept},
            "calibration": _metric_bundle(y_cal, calibrated_cal, w_cal, threshold),
        }
        for split_name in ("train", "test"):
            x_value, y_value, w_value = _arrays(partition[split_name], vectorizer, label)
            probability = calibrator.predict(models[head].predict_proba(x_value)[:, 1])
            head_report[split_name] = _metric_bundle(y_value, probability, w_value, threshold)
            if split_name == "test":
                head_report["test_by_episode"] = _per_episode_metrics(partition[split_name], y_value, probability, threshold)
        report["heads"][head] = head_report
    version = f"reliability-v1-{dataset_digest[:12]}"
    report["model_version"] = version
    report["dataset_sha256"] = dataset_digest
    report["trusted_thresholds"] = thresholds
    bundle = ReliabilityBundle(
        vectorizer=vectorizer,
        models=models,
        calibrators=calibrators,
        trusted_thresholds=thresholds,
        model_version=version,
    )
    return bundle, report


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Reliability V1 training report",
        "",
        f"- Model version: `{report['model_version']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        f"- Split: `{report['split']['strategy']}`",
        f"- Rows: `{report['split']['rows']}`",
        f"- Episode overlaps: `{report['split']['overlaps']}`",
        "",
        "| Head | Model | Test AUC | Test AP | Test Brier | Trusted coverage | Trusted bad rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for head, values in report["heads"].items():
        test = values["test"]
        def fmt(value: Any) -> str:
            return "n/a" if value is None else f"{value:.4f}"
        lines.append(
            f"| {head} | {values['model']} | {fmt(test['roc_auc'])} | {fmt(test['average_precision'])} | "
            f"{fmt(test['brier'])} | {fmt(test['trusted_coverage'])} | {fmt(test['trusted_bad_rate'])} |"
        )
    lines.extend(("", "Thresholds were selected only on the episode-disjoint calibration partition; the latest batch was not used for fitting or calibration.", ""))
    return "\n".join(lines)
