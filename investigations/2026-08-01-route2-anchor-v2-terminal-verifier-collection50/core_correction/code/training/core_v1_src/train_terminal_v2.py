#!/usr/bin/env python3
"""Train a conservative terminal v2 baseline with sequence confirmation."""

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
from sklearn.linear_model import LogisticRegression

from terminal_v2_features import TerminalV2FeatureState
from train_models import apply_temperature, choose_temperature, evaluate

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
from training.v11_core_downstream_features import filter_core_features


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "v1" / "terminal_decision.jsonl.gz"
DEFAULT_MODEL = ROOT / "models" / "v2" / "terminal_decision_v2.joblib"
DEFAULT_REPORT = ROOT / "reports" / "v2" / "terminal_v2_report.json"
DEFAULT_REPORT_MD = ROOT / "reports" / "v2" / "terminal_v2_report.md"
CLASSES = ["arrived", "boundary", "far"]
SCHEMA = "navila-terminal-controller-bundle-v2"


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


def is_oracle_source(row: dict[str, Any]) -> bool:
    memory = row["inputs"].get("route_memory") or {}
    provenance = " ".join(
        str(memory.get(field) or "").lower()
        for field in ("source", "configured_source", "relocalization_backend")
    )
    return "oracle" in provenance or "isaac" in provenance


def load(path: Path) -> dict[str, Any]:
    result = {
        split: {"features": [], "labels": [], "weights": [], "metadata": []}
        for split in ("train", "validation", "test")
    }
    states: dict[str, TerminalV2FeatureState] = {}
    skipped_oracle = 0
    for row in read_rows(path):
        if is_oracle_source(row):
            skipped_oracle += 1
            continue
        key = row["episode"]["episode_key"]
        state = states.setdefault(key, TerminalV2FeatureState())
        weight = float(row["labels"]["sample_weight"])
        label = row["labels"]["terminal_class"]
        requested_stop = bool(row["inputs"].get("vlm_requested_stop"))
        # Boundary and arrived-without-stop are the two scarce mechanisms
        # called out in the handoff.  Reweighting changes only training loss;
        # validation/test retain their original oracle alignment weights.
        training_multiplier = (
            2.0
            if label == "boundary"
            else 1.5
            if label == "arrived" and not requested_stop
            else 1.0
        )
        split = row["episode"]["split"]
        result[split]["features"].append(
            filter_core_features(
                state.transform(row), required_head="distance"
            )
        )
        result[split]["labels"].append(label)
        result[split]["weights"].append(weight)
        result[split]["metadata"].append(
            {
                "episode_key": key,
                "scene_id": row["episode"]["scene_id"],
                "step": int(row["time"]["step"]),
                "training_multiplier": training_multiplier,
                "vlm_requested_stop": requested_stop,
            }
        )
    result["skipped_oracle_source_rows"] = skipped_oracle
    return result


def positive_weight_view(
    matrix: np.ndarray,
    payload: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    labels = np.asarray(payload["labels"], dtype=object)
    weights = np.asarray(payload["weights"], dtype=np.float64)
    mask = weights > 0.0
    indices = np.flatnonzero(mask)
    return (
        matrix[mask],
        labels[mask],
        weights[mask],
        [payload["metadata"][index] for index in indices],
    )


def training_weights(
    labels: np.ndarray,
    base: np.ndarray,
    metadata: list[dict[str, Any]],
) -> tuple[np.ndarray, dict[str, float]]:
    counts = collections.Counter(labels.tolist())
    total = len(labels)
    class_weights = {
        label: min(
            12.0,
            max(0.25, total / (len(CLASSES) * max(1, counts[label]))),
        )
        for label in CLASSES
    }
    values = np.asarray(
        [
            weight
            * class_weights[label]
            * float(meta["training_multiplier"])
            for label, weight, meta in zip(labels, base, metadata)
        ],
        dtype=np.float64,
    )
    return values, class_weights


def candidate_models() -> dict[str, Any]:
    return {
        "regularized_hgb": HistGradientBoostingClassifier(
            learning_rate=0.045,
            max_iter=220,
            max_leaf_nodes=15,
            max_depth=4,
            min_samples_leaf=60,
            max_bins=127,
            l2_regularization=4.0,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=20,
            random_state=20260729,
        ),
        "linear_logistic": LogisticRegression(
            C=0.15,
            max_iter=1200,
            solver="lbfgs",
            random_state=20260729,
        ),
    }


def probability_columns(model: Any, matrix: np.ndarray) -> np.ndarray:
    order = [list(model.classes_).index(label) for label in CLASSES]
    return model.predict_proba(matrix)[:, order]


def sequence_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
    threshold: float,
    streak: int,
) -> dict[str, Any]:
    confirmed = np.zeros(len(labels), dtype=bool)
    by_episode: dict[str, list[int]] = collections.defaultdict(list)
    for index, item in enumerate(metadata):
        by_episode[item["episode_key"]].append(index)
    for indices in by_episode.values():
        indices.sort(key=lambda index: metadata[index]["step"])
        run = 0
        for index in indices:
            run = run + 1 if scores[index] >= threshold else 0
            confirmed[index] = run >= streak
    arrived = labels == "arrived"
    boundary = labels == "boundary"
    far = labels == "far"
    arrived_weight = float(weights[arrived].sum())
    return {
        "threshold": float(threshold),
        "streak": int(streak),
        "confirmed_rows": int(confirmed.sum()),
        "confirmed_episodes": len(
            {
                metadata[index]["episode_key"]
                for index in np.flatnonzero(confirmed)
            }
        ),
        "arrived_recall": (
            float(weights[confirmed & arrived].sum()) / arrived_weight
            if arrived_weight
            else 0.0
        ),
        "true_far_false_arrived": int(np.sum(confirmed & far)),
        "weighted_true_far_false_arrived": float(
            weights[confirmed & far].sum()
        ),
        "boundary_forced_arrived": int(np.sum(confirmed & boundary)),
        "weighted_boundary_forced_arrived": float(
            weights[confirmed & boundary].sum()
        ),
    }


def choose_sequence_policy(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = []
    for threshold in np.linspace(0.50, 0.995, 100):
        for streak in range(2, 9):
            candidates.append(
                sequence_metrics(
                    labels,
                    scores,
                    weights,
                    metadata,
                    float(threshold),
                    streak,
                )
            )
    safe = [
        item
        for item in candidates
        if item["true_far_false_arrived"] == 0
        and item["boundary_forced_arrived"] == 0
    ]
    pool = safe or candidates
    return max(
        pool,
        key=lambda item: (
            item["arrived_recall"],
            -item["streak"],
            -item["threshold"],
        ),
    )


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Terminal v2 shadow baseline",
        "",
        "Absolute anchor-index features are removed. Boundary and "
        "arrived-without-stop rows receive extra training weight. Any arrived "
        "proposal still requires a validation-frozen consecutive sequence.",
        "",
        f"- selected estimator: `{report['selected_estimator']}`",
        f"- artifact: `{report['artifact_path']}`",
        f"- artifact SHA-256: `{report['artifact_sha256']}`",
        f"- features: {report['feature_count']}",
        "",
        "| Split | Balanced accuracy | Macro F1 | Log loss |",
        "|---|---:|---:|---:|",
    ]
    for split in ("validation", "test"):
        value = report["metrics"][split]
        lines.append(
            f"| {split} | {value['balanced_accuracy']:.4f} | "
            f"{value['macro_f1']:.4f} | {value['log_loss']:.4f} |"
        )
    lines.extend(["", "## Consecutive arrived confirmation", ""])
    for split in ("validation", "test"):
        value = report["sequence_policy"][split]
        lines.append(
            f"- {split}: threshold={value['threshold']:.4f}, "
            f"streak={value['streak']}, arrived recall="
            f"{value['arrived_recall']:.4f}, true-far false-arrived="
            f"{value['true_far_false_arrived']}, boundary forced-arrived="
            f"{value['boundary_forced_arrived']}."
        )
    lines.extend(
        [
            "",
            "The threshold/streak are selected on validation only and reused "
            "unchanged on test. Status: shadow-only; no stop authority.",
            "",
        ]
    )
    return "\n".join(lines)


def train(args: argparse.Namespace) -> dict[str, Any]:
    data_path = Path(args.data).resolve()
    loaded = load(data_path)
    vectorizer = DictVectorizer(sparse=False, dtype=np.float32)
    matrices = {
        "train": vectorizer.fit_transform(loaded["train"]["features"])
    }
    for split in ("validation", "test"):
        matrices[split] = vectorizer.transform(
            loaded[split]["features"]
        )
    views = {
        split: positive_weight_view(matrices[split], loaded[split])
        for split in ("train", "validation", "test")
    }
    x_train, y_train, base_weights, train_meta = views["train"]
    fit_weights, class_weights = training_weights(
        y_train, base_weights, train_meta
    )

    candidates = {}
    fitted = {}
    for name, model in candidate_models().items():
        print(f"[terminal-v2] fitting {name}", flush=True)
        model.fit(x_train, y_train, sample_weight=fit_weights)
        raw_validation = probability_columns(
            model, views["validation"][0]
        )
        temperature, _loss = choose_temperature(
            raw_validation,
            views["validation"][1],
            views["validation"][2],
            CLASSES,
        )
        calibrated = apply_temperature(raw_validation, temperature)
        metrics = evaluate(
            views["validation"][1],
            calibrated,
            views["validation"][2],
            views["validation"][3],
            CLASSES,
        )
        candidates[name] = {
            "temperature": temperature,
            "validation_balanced_accuracy": metrics[
                "balanced_accuracy"
            ],
            "validation_macro_f1": metrics["macro_f1"],
            "validation_log_loss": metrics["log_loss"],
        }
        fitted[name] = model
    selected_name = max(
        candidates,
        key=lambda name: (
            candidates[name]["validation_macro_f1"],
            candidates[name]["validation_balanced_accuracy"],
        ),
    )
    model = fitted[selected_name]
    temperature = candidates[selected_name]["temperature"]
    probabilities = {
        split: apply_temperature(
            probability_columns(model, views[split][0]), temperature
        )
        for split in ("train", "validation", "test")
    }
    metrics = {
        split: evaluate(
            views[split][1],
            probabilities[split],
            views[split][2],
            views[split][3],
            CLASSES,
        )
        for split in ("train", "validation", "test")
    }
    arrived_index = CLASSES.index("arrived")
    validation_policy = choose_sequence_policy(
        views["validation"][1],
        probabilities["validation"][:, arrived_index],
        views["validation"][2],
        views["validation"][3],
    )
    test_policy = sequence_metrics(
        views["test"][1],
        probabilities["test"][:, arrived_index],
        views["test"][2],
        views["test"][3],
        validation_policy["threshold"],
        validation_policy["streak"],
    )

    bundle = {
        "schema": SCHEMA,
        "task": "terminal_decision",
        "classes": CLASSES,
        "feature_names": vectorizer.get_feature_names_out().tolist(),
        "feature_count": len(vectorizer.feature_names_),
        "vectorizer": vectorizer,
        "model": model,
        "temperature": temperature,
        "selected_estimator": selected_name,
        "estimator_candidates": candidates,
        "decision_policy": {
            "arrived_sequence_confirmation": validation_policy,
            "boundary_action": "verify",
            "integration_status": "shadow_only",
        },
        "training": {
            "dataset_path": str(data_path),
            "dataset_sha256": sha256_file(data_path),
            "class_weights": class_weights,
            "train_rows": len(y_train),
            "skipped_oracle_source_rows": loaded[
                "skipped_oracle_source_rows"
            ],
            "python": sys.version,
            "sklearn_version": __import__("sklearn").__version__,
            "numpy_version": np.__version__,
        },
        "metrics": metrics,
        "sequence_policy": {
            "validation": validation_policy,
            "test": test_policy,
        },
    }
    model_path = Path(args.model).resolve()
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
    report_path = Path(args.report).resolve()
    report_md_path = Path(args.report_md).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md_path.write_text(markdown(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT_MD))
    return parser.parse_args()


def main() -> None:
    print(json.dumps(train(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
