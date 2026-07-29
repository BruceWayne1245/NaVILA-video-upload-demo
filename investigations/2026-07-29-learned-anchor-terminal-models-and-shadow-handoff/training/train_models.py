#!/usr/bin/env python3
"""Train and evaluate first-pass anchor-transition and terminal models."""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import (
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)

from model_features import CausalFeatureState, assert_runtime_only


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "v1"
DEFAULT_MODELS = ROOT / "models" / "v1"
DEFAULT_REPORTS = ROOT / "reports" / "v1"
MODEL_SCHEMA = "navila-learned-controller-bundle-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def task_config(task: str) -> tuple[str, str, list[str]]:
    if task == "anchor_transition":
        return (
            "anchor_state.jsonl.gz",
            "transition_action",
            ["advance_one", "hold", "rebase", "rollback", "skip_or_rebase"],
        )
    if task == "terminal_decision":
        return (
            "terminal_decision.jsonl.gz",
            "terminal_class",
            ["arrived", "boundary", "far"],
        )
    raise ValueError(task)


def load_features(
    data_dir: Path,
    task: str,
    limit: int = 0,
) -> dict[str, Any]:
    filename, label_field, classes = task_config(task)
    features = {split: [] for split in ("train", "validation", "test")}
    labels = {split: [] for split in features}
    weights = {split: [] for split in features}
    metadata = {split: [] for split in features}
    states: dict[str, CausalFeatureState] = {}
    total = 0
    skipped_oracle_source = 0
    for row in read_jsonl_gz(data_dir / filename):
        route_memory = row["inputs"].get("route_memory") or {}
        provenance = " ".join(
            str(route_memory.get(field) or "").lower()
            for field in (
                "source",
                "configured_source",
                "relocalization_backend",
            )
        )
        if "oracle" in provenance or "isaac" in provenance:
            skipped_oracle_source += 1
            continue
        episode_key = row["episode"]["episode_key"]
        state = states.setdefault(episode_key, CausalFeatureState())
        feature = state.transform(row)
        assert_runtime_only(feature)
        split = row["episode"]["split"]
        features[split].append(feature)
        labels[split].append(row["labels"][label_field])
        weights[split].append(float(row["labels"]["sample_weight"]))
        metadata[split].append(
            {
                "episode_key": episode_key,
                "physical_episode_id": row["episode"]["physical_episode_id"],
                "scene_id": row["episode"]["scene_id"],
            }
        )
        total += 1
        if limit and total >= limit:
            break
    return {
        "features": features,
        "labels": labels,
        "weights": weights,
        "metadata": metadata,
        "classes": classes,
        "source_file": filename,
        "skipped_oracle_source_rows": skipped_oracle_source,
    }


def filter_positive_weight(
    matrix: np.ndarray,
    labels: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    mask = weights > 0.0
    indices = np.flatnonzero(mask)
    return (
        matrix[mask],
        labels[mask],
        weights[mask],
        [metadata[index] for index in indices],
    )


def balanced_training_weights(
    labels: np.ndarray,
    base_weights: np.ndarray,
    classes: list[str],
) -> tuple[np.ndarray, dict[str, float]]:
    counts = collections.Counter(labels.tolist())
    total = len(labels)
    mapping = {}
    for label in classes:
        count = counts.get(label, 0)
        if count == 0:
            mapping[label] = 1.0
        else:
            mapping[label] = min(6.0, max(0.25, total / (len(classes) * count)))
    return (
        np.asarray(
            [base * mapping[label] for base, label in zip(base_weights, labels)],
            dtype=np.float64,
        ),
        mapping,
    )


def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-9, 1.0)
    logits = np.log(clipped) / float(temperature)
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=1, keepdims=True)


def choose_temperature(
    probabilities: np.ndarray,
    labels: np.ndarray,
    weights: np.ndarray,
    classes: list[str],
) -> tuple[float, float]:
    best = (1.0, math.inf)
    for temperature in np.linspace(0.50, 3.00, 51):
        calibrated = apply_temperature(probabilities, float(temperature))
        loss = log_loss(
            labels,
            calibrated,
            labels=classes,
            sample_weight=weights,
        )
        if loss < best[1]:
            best = (float(temperature), float(loss))
    return best


def evaluate(
    labels: np.ndarray,
    probabilities: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
    classes: list[str],
) -> dict[str, Any]:
    prediction = np.asarray(classes)[np.argmax(probabilities, axis=1)]
    report = classification_report(
        labels,
        prediction,
        labels=classes,
        output_dict=True,
        zero_division=0,
        sample_weight=weights,
    )
    result: dict[str, Any] = {
        "rows": int(len(labels)),
        "episodes": len({item["episode_key"] for item in metadata}),
        "scenes": sorted({item["scene_id"] for item in metadata}),
        "balanced_accuracy": float(
            balanced_accuracy_score(labels, prediction, sample_weight=weights)
        ),
        "macro_f1": float(
            f1_score(
                labels,
                prediction,
                labels=classes,
                average="macro",
                sample_weight=weights,
                zero_division=0,
            )
        ),
        "log_loss": float(
            log_loss(
                labels,
                probabilities,
                labels=classes,
                sample_weight=weights,
            )
        ),
        "classification_report": report,
        "confusion_matrix": confusion_matrix(
            labels,
            prediction,
            labels=classes,
            sample_weight=weights,
        ).tolist(),
    }
    try:
        result["roc_auc_ovr_macro"] = float(
            roc_auc_score(
                labels,
                probabilities,
                labels=classes,
                multi_class="ovr",
                average="macro",
                sample_weight=weights,
            )
        )
    except ValueError:
        result["roc_auc_ovr_macro"] = None
    per_scene = {}
    scenes = sorted({item["scene_id"] for item in metadata})
    for scene in scenes:
        mask = np.asarray([item["scene_id"] == scene for item in metadata])
        scene_labels = labels[mask]
        scene_prediction = prediction[mask]
        scene_weights = weights[mask]
        per_scene[scene] = {
            "rows": int(mask.sum()),
            "balanced_accuracy": float(
                balanced_accuracy_score(
                    scene_labels, scene_prediction, sample_weight=scene_weights
                )
            ),
            "macro_f1": float(
                f1_score(
                    scene_labels,
                    scene_prediction,
                    labels=classes,
                    average="macro",
                    sample_weight=scene_weights,
                    zero_division=0,
                )
            ),
        }
    result["per_scene"] = per_scene
    return result


def zero_false_positive_threshold(
    probabilities: np.ndarray,
    labels: np.ndarray,
    positive_class: str,
    classes: list[str],
) -> dict[str, float]:
    index = classes.index(positive_class)
    scores = probabilities[:, index]
    negative_scores = scores[labels != positive_class]
    positives = scores[labels == positive_class]
    threshold = (
        float(np.nextafter(negative_scores.max(), 1.0))
        if len(negative_scores)
        else 0.5
    )
    threshold = min(1.0, max(0.0, threshold))
    recall = float(np.mean(positives >= threshold)) if len(positives) else 0.0
    return {
        "threshold": threshold,
        "validation_false_positives": int(
            np.sum(negative_scores >= threshold)
        ),
        "validation_recall": recall,
    }


def fit_task(
    data_dir: Path,
    model_dir: Path,
    task: str,
    limit: int,
) -> tuple[dict[str, Any], Path]:
    loaded = load_features(data_dir, task, limit=limit)
    print(
        f"[train] {task} rows: "
        + ", ".join(
            f"{split}={len(loaded['labels'][split])}"
            for split in ("train", "validation", "test")
        )
        + f"; skipped_oracle={loaded['skipped_oracle_source_rows']}",
        flush=True,
    )
    vectorizer = DictVectorizer(sparse=False, dtype=np.float32)
    train_matrix = vectorizer.fit_transform(loaded["features"]["train"])
    matrices = {"train": train_matrix}
    for split in ("validation", "test"):
        matrices[split] = vectorizer.transform(loaded["features"][split])

    filtered = {}
    for split in matrices:
        filtered[split] = filter_positive_weight(
            matrices[split],
            np.asarray(loaded["labels"][split], dtype=object),
            np.asarray(loaded["weights"][split], dtype=np.float64),
            loaded["metadata"][split],
        )
    x_train, y_train, base_train_weights, train_meta = filtered["train"]
    train_weights, class_weight_map = balanced_training_weights(
        y_train, base_train_weights, loaded["classes"]
    )
    max_iterations = 120 if task == "anchor_transition" else 180
    max_leaf_nodes = 15 if task == "anchor_transition" else 31
    print(
        f"[train] {task} matrix={x_train.shape}, features="
        f"{len(vectorizer.feature_names_)}, fitting up to {max_iterations} iterations",
        flush=True,
    )
    model = HistGradientBoostingClassifier(
        learning_rate=0.06,
        max_iter=max_iterations,
        max_leaf_nodes=max_leaf_nodes,
        max_depth=6,
        min_samples_leaf=40,
        max_bins=127,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.12,
        n_iter_no_change=15,
        random_state=20260729,
    )
    model.fit(x_train, y_train, sample_weight=train_weights)

    column_order = [
        list(model.classes_).index(label) for label in loaded["classes"]
    ]
    raw_probabilities = {
        split: model.predict_proba(filtered[split][0])[:, column_order]
        for split in ("train", "validation", "test")
    }
    val_x, val_y, val_weights, val_meta = filtered["validation"]
    temperature, validation_calibrated_loss = choose_temperature(
        raw_probabilities["validation"],
        val_y,
        val_weights,
        loaded["classes"],
    )
    probabilities = {
        split: apply_temperature(raw_probabilities[split], temperature)
        for split in raw_probabilities
    }
    metrics = {
        split: evaluate(
            filtered[split][1],
            probabilities[split],
            filtered[split][2],
            filtered[split][3],
            loaded["classes"],
        )
        for split in ("train", "validation", "test")
    }
    policy = {}
    if task == "terminal_decision":
        policy = {
            "arrived_zero_false_positive": zero_false_positive_threshold(
                probabilities["validation"],
                val_y,
                "arrived",
                loaded["classes"],
            ),
            "far_zero_false_positive_on_nonfar": zero_false_positive_threshold(
                probabilities["validation"],
                val_y,
                "far",
                loaded["classes"],
            ),
        }

    data_path = data_dir / loaded["source_file"]
    bundle = {
        "schema": MODEL_SCHEMA,
        "task": task,
        "classes": loaded["classes"],
        "feature_names": vectorizer.get_feature_names_out().tolist(),
        "feature_count": len(vectorizer.feature_names_),
        "vectorizer": vectorizer,
        "model": model,
        "temperature": temperature,
        "decision_policy": policy,
        "training": {
            "dataset_path": str(data_path),
            "dataset_sha256": sha256_file(data_path),
            "python": sys.version,
            "sklearn_version": __import__("sklearn").__version__,
            "numpy_version": np.__version__,
            "train_rows": int(len(y_train)),
            "class_weight_map": class_weight_map,
            "model_params": model.get_params(),
            "iterations": int(model.n_iter_),
            "validation_calibrated_log_loss": validation_calibrated_loss,
            "skipped_oracle_source_rows": loaded[
                "skipped_oracle_source_rows"
            ],
        },
        "metrics": metrics,
    }
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{task}_v1.joblib"
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
    return summary, model_path


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Anchor and terminal model training report",
        "",
        f"Generated from `{report['dataset_schema']}`.",
        "",
    ]
    for task, result in report["tasks"].items():
        lines.extend(
            [
                f"## {task}",
                "",
                f"- artifact: `{result['artifact_path']}`",
                f"- SHA-256: `{result['artifact_sha256']}`",
                f"- features: {result['feature_count']}",
                f"- temperature: {result['temperature']:.3f}",
                f"- training iterations: {result['training']['iterations']}",
                "",
                "| Split | Rows | Balanced accuracy | Macro F1 | Log loss |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for split in ("train", "validation", "test"):
            metrics = result["metrics"][split]
            lines.append(
                f"| {split} | {metrics['rows']} | "
                f"{metrics['balanced_accuracy']:.4f} | "
                f"{metrics['macro_f1']:.4f} | {metrics['log_loss']:.4f} |"
            )
        if result.get("decision_policy"):
            lines.extend(["", "Decision-policy calibration:", ""])
            for name, policy in result["decision_policy"].items():
                lines.append(
                    f"- `{name}`: threshold={policy['threshold']:.6f}, "
                    f"validation false positives={policy['validation_false_positives']}, "
                    f"recall={policy['validation_recall']:.4f}"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA))
    parser.add_argument("--model-dir", default=str(DEFAULT_MODELS))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORTS))
    parser.add_argument(
        "--task",
        choices=("both", "anchor_transition", "terminal_decision"),
        default="both",
    )
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    model_dir = Path(args.model_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    tasks = (
        ["anchor_transition", "terminal_decision"]
        if args.task == "both"
        else [args.task]
    )
    report = {
        "schema": "navila-model-training-report-v1",
        "dataset_schema": "navila-anchor-terminal-training-v1",
        "tasks": {},
    }
    for task in tasks:
        print(f"[train] loading and fitting {task}", flush=True)
        summary, path = fit_task(data_dir, model_dir, task, args.limit)
        report["tasks"][task] = summary
        print(
            f"[train] completed {task}: {path} "
            f"test_bal_acc={summary['metrics']['test']['balanced_accuracy']:.4f}",
            flush=True,
        )
    json_path = report_dir / "training_report.json"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (report_dir / "training_report.md").write_text(
        markdown_report(report), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
