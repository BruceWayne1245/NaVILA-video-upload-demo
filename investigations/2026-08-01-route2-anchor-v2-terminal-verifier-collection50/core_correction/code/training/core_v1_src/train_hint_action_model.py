#!/usr/bin/env python3
"""Train the first dedicated hint-action intervention model."""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer

from hint_action_features import HintActionCausalFeatureState
from train_models import (
    apply_temperature,
    balanced_training_weights,
    choose_temperature,
    evaluate,
    filter_positive_weight,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "v1" / "hint_action_decision.jsonl.gz"
DEFAULT_MODEL = ROOT / "models" / "v1" / "hint_action_decision_v1.joblib"
DEFAULT_REPORT_JSON = (
    ROOT / "reports" / "v1" / "hint_action_training_report.json"
)
DEFAULT_REPORT_MD = (
    ROOT / "reports" / "v1" / "hint_action_training_report.md"
)
# Keep probability columns in sklearn's lexicographic label order.  Metrics
# such as log_loss validate this convention independently of model.classes_.
CLASSES = ["abstain", "keep_vlm", "override_hint"]
MODEL_SCHEMA = "navila-hint-action-controller-bundle-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def oracle_source(row: dict[str, Any]) -> bool:
    route_memory = row["inputs"].get("route_memory") or {}
    provenance = " ".join(
        str(route_memory.get(field) or "").lower()
        for field in ("source", "configured_source", "relocalization_backend")
    )
    return "oracle" in provenance or "isaac" in provenance


def load_features(path: Path) -> dict[str, Any]:
    features = {split: [] for split in ("train", "validation", "test")}
    labels = {split: [] for split in features}
    weights = {split: [] for split in features}
    metadata = {split: [] for split in features}
    states: dict[str, HintActionCausalFeatureState] = {}
    skipped_oracle = 0
    for row in read_rows(path):
        if oracle_source(row):
            skipped_oracle += 1
            continue
        episode_key = row["episode"]["episode_key"]
        state = states.setdefault(
            episode_key, HintActionCausalFeatureState()
        )
        split = row["episode"]["split"]
        features[split].append(state.transform(row))
        labels[split].append(row["labels"]["decision"])
        weights[split].append(float(row["labels"]["sample_weight"]))
        metadata[split].append(
            {
                "episode_key": episode_key,
                "physical_episode_id": row["episode"][
                    "physical_episode_id"
                ],
                "scene_id": row["episode"]["scene_id"],
                "historical_override": bool(
                    row["historical_policy"]["override"]
                ),
                "historical_reason": row["historical_policy"].get("reason"),
            }
        )
    return {
        "features": features,
        "labels": labels,
        "weights": weights,
        "metadata": metadata,
        "skipped_oracle_source_rows": skipped_oracle,
    }


def intervention_metrics(
    labels: np.ndarray,
    override_scores: np.ndarray,
    weights: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    predicted = override_scores >= float(threshold)
    positive = labels == "override_hint"
    tp = float(weights[predicted & positive].sum())
    fp = float(weights[predicted & ~positive].sum())
    fn = float(weights[~predicted & positive].sum())
    tn = float(weights[~predicted & ~positive].sum())
    return {
        "threshold": float(threshold),
        "weighted_true_positive": tp,
        "weighted_false_positive": fp,
        "weighted_false_negative": fn,
        "weighted_true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "coverage": float(np.average(predicted, weights=weights))
        if float(weights.sum()) > 0.0
        else 0.0,
    }


def historical_metrics(
    labels: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    predicted = np.asarray(
        [item["historical_override"] for item in metadata], dtype=bool
    )
    positive = labels == "override_hint"
    tp = float(weights[predicted & positive].sum())
    fp = float(weights[predicted & ~positive].sum())
    fn = float(weights[~predicted & positive].sum())
    tn = float(weights[~predicted & ~positive].sum())
    return {
        "weighted_true_positive": tp,
        "weighted_false_positive": fp,
        "weighted_false_negative": fn,
        "weighted_true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "coverage": float(np.average(predicted, weights=weights))
        if float(weights.sum()) > 0.0
        else 0.0,
    }


def choose_operating_points(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
) -> dict[str, Any]:
    thresholds = sorted(
        {
            0.50,
            *(
                float(value)
                for value in np.linspace(0.55, 0.99, 45)
            ),
            *(
                float(np.nextafter(value, 1.0))
                for value in scores[labels != "override_hint"]
            ),
        }
    )
    metrics = [
        intervention_metrics(labels, scores, weights, threshold)
        for threshold in thresholds
    ]

    def best_at_precision(minimum: float) -> dict[str, Any]:
        eligible = [
            item for item in metrics if item["precision"] >= minimum
        ]
        if not eligible:
            return max(metrics, key=lambda item: item["precision"])
        return max(
            eligible,
            key=lambda item: (item["recall"], item["precision"]),
        )

    no_false_positive = [
        item
        for item in metrics
        if item["weighted_false_positive"] <= 1e-12
    ]
    return {
        "precision_0p90": best_at_precision(0.90),
        "precision_0p95": best_at_precision(0.95),
        "zero_validation_false_positive": (
            max(no_false_positive, key=lambda item: item["recall"])
            if no_false_positive
            else max(metrics, key=lambda item: item["precision"])
        ),
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Dedicated hint-action model — first shadow baseline",
        "",
        "This model decides only whether to prefer a conflicting movement hint "
        "over the VLM movement direction. Stop authority stays with the terminal "
        "model/state machine; collision clearance remains a hard safety gate.",
        "",
        f"- artifact: `{report['artifact_path']}`",
        f"- artifact SHA-256: `{report['artifact_sha256']}`",
        f"- dataset SHA-256: `{report['training']['dataset_sha256']}`",
        f"- features: {report['feature_count']}",
        f"- temperature: {report['temperature']:.3f}",
        "",
        "## Three-class quality",
        "",
        "| Split | Rows | Balanced accuracy | Macro F1 | Log loss |",
        "|---|---:|---:|---:|---:|",
    ]
    for split in ("train", "validation", "test"):
        metrics = report["metrics"][split]
        lines.append(
            f"| {split} | {metrics['rows']} | "
            f"{metrics['balanced_accuracy']:.4f} | "
            f"{metrics['macro_f1']:.4f} | {metrics['log_loss']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Intervention comparison",
            "",
            "| Split/policy | Precision | Recall | Coverage |",
            "|---|---:|---:|---:|",
        ]
    )
    for split in ("validation", "test"):
        old = report["historical_policy"][split]
        lines.append(
            f"| {split} historical gate | {old['precision']:.4f} | "
            f"{old['recall']:.4f} | {old['coverage']:.4f} |"
        )
        for name, values in report["operating_points"][split].items():
            lines.append(
                f"| {split} model `{name}` | {values['precision']:.4f} | "
                f"{values['recall']:.4f} | {values['coverage']:.4f} |"
            )
    lines.extend(
        [
            "",
            "Thresholds are selected on validation only. Test entries reuse the "
            "frozen validation thresholds; no test-set tuning is performed.",
            "",
            "Status: shadow-only. This artifact is not wired into the active "
            "evaluator.",
            "",
        ]
    )
    return "\n".join(lines)


def train(args: argparse.Namespace) -> dict[str, Any]:
    data_path = Path(args.data).resolve()
    model_path = Path(args.model).resolve()
    report_json = Path(args.report_json).resolve()
    report_md = Path(args.report_md).resolve()
    loaded = load_features(data_path)
    print(
        "[hint-train] rows "
        + ", ".join(
            f"{split}={len(loaded['labels'][split])}"
            for split in ("train", "validation", "test")
        )
        + f"; skipped_oracle={loaded['skipped_oracle_source_rows']}",
        flush=True,
    )

    vectorizer = DictVectorizer(sparse=False, dtype=np.float32)
    matrices = {
        "train": vectorizer.fit_transform(loaded["features"]["train"])
    }
    for split in ("validation", "test"):
        matrices[split] = vectorizer.transform(
            loaded["features"][split]
        )
    filtered = {}
    for split in matrices:
        filtered[split] = filter_positive_weight(
            matrices[split],
            np.asarray(loaded["labels"][split], dtype=object),
            np.asarray(loaded["weights"][split], dtype=np.float64),
            loaded["metadata"][split],
        )
    x_train, y_train, base_weights, _train_meta = filtered["train"]
    train_weights, class_weight_map = balanced_training_weights(
        y_train, base_weights, CLASSES
    )
    print(
        f"[hint-train] matrix={x_train.shape} "
        f"features={len(vectorizer.feature_names_)}",
        flush=True,
    )
    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=220,
        max_leaf_nodes=23,
        max_depth=6,
        min_samples_leaf=20,
        max_bins=127,
        l2_regularization=1.5,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
        random_state=20260729,
    )
    model.fit(x_train, y_train, sample_weight=train_weights)
    column_order = [list(model.classes_).index(label) for label in CLASSES]
    raw_probabilities = {
        split: model.predict_proba(filtered[split][0])[:, column_order]
        for split in ("train", "validation", "test")
    }
    val_labels = filtered["validation"][1]
    val_weights = filtered["validation"][2]
    temperature, calibrated_loss = choose_temperature(
        raw_probabilities["validation"],
        val_labels,
        val_weights,
        CLASSES,
    )
    probabilities = {
        split: apply_temperature(values, temperature)
        for split, values in raw_probabilities.items()
    }
    metrics = {
        split: evaluate(
            filtered[split][1],
            probabilities[split],
            filtered[split][2],
            filtered[split][3],
            CLASSES,
        )
        for split in ("train", "validation", "test")
    }

    override_index = CLASSES.index("override_hint")
    validation_points = choose_operating_points(
        val_labels,
        probabilities["validation"][:, override_index],
        val_weights,
    )
    operating_points = {"validation": validation_points, "test": {}}
    for name, point in validation_points.items():
        operating_points["test"][name] = intervention_metrics(
            filtered["test"][1],
            probabilities["test"][:, override_index],
            filtered["test"][2],
            point["threshold"],
        )
    historical = {
        split: historical_metrics(
            filtered[split][1],
            filtered[split][2],
            filtered[split][3],
        )
        for split in ("validation", "test")
    }

    bundle = {
        "schema": MODEL_SCHEMA,
        "task": "hint_action_decision",
        "scope": {
            "movement_direction_only": True,
            "stop_authority": False,
            "collision_authority": False,
            "integration_status": "shadow_only",
        },
        "classes": CLASSES,
        "feature_names": vectorizer.get_feature_names_out().tolist(),
        "feature_count": len(vectorizer.feature_names_),
        "vectorizer": vectorizer,
        "model": model,
        "temperature": temperature,
        "decision_policy": validation_points,
        "training": {
            "dataset_path": str(data_path),
            "dataset_sha256": sha256_file(data_path),
            "python": sys.version,
            "sklearn_version": __import__("sklearn").__version__,
            "numpy_version": np.__version__,
            "train_rows": int(len(y_train)),
            "class_weight_map": class_weight_map,
            "iterations": int(model.n_iter_),
            "validation_calibrated_log_loss": calibrated_loss,
            "skipped_oracle_source_rows": loaded[
                "skipped_oracle_source_rows"
            ],
        },
        "metrics": metrics,
        "historical_policy": historical,
        "operating_points": operating_points,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_suffix(".joblib.tmp")
    joblib.dump(bundle, temporary, compress=3)
    os.replace(temporary, model_path)
    bundle["artifact_path"] = str(model_path)
    bundle["artifact_sha256"] = sha256_file(model_path)

    summary = {
        key: value
        for key, value in bundle.items()
        if key not in {"model", "vectorizer", "feature_names"}
    }
    summary["feature_count"] = len(vectorizer.feature_names_)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md.write_text(markdown(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT_MD))
    return parser.parse_args()


def main() -> None:
    print(json.dumps(train(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
