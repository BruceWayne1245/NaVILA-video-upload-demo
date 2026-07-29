#!/usr/bin/env python3
"""Validate saved bundles, evaluate terminal policy, and combine reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np

import train_models


ROOT = Path(__file__).resolve().parents[1]


def summarize_bundle(path: Path) -> tuple[dict, dict]:
    bundle = joblib.load(path)
    required = {
        "schema",
        "task",
        "classes",
        "feature_names",
        "feature_count",
        "vectorizer",
        "model",
        "temperature",
        "training",
        "metrics",
    }
    missing = sorted(required - set(bundle))
    if missing:
        raise RuntimeError(f"{path}: missing bundle fields {missing}")
    if bundle["feature_count"] != len(bundle["feature_names"]):
        raise RuntimeError(f"{path}: feature-count mismatch")
    dataset_path = Path(bundle["training"]["dataset_path"])
    actual_dataset_hash = train_models.sha256_file(dataset_path)
    if actual_dataset_hash != bundle["training"]["dataset_sha256"]:
        raise RuntimeError(f"{path}: dataset hash mismatch")
    summary = {
        key: value
        for key, value in bundle.items()
        if key not in {"model", "vectorizer", "feature_names"}
    }
    summary["artifact_path"] = str(path)
    summary["artifact_sha256"] = train_models.sha256_file(path)
    summary["artifact_validation"] = {
        "load": "pass",
        "feature_count": bundle["feature_count"],
        "dataset_hash": "pass",
    }
    return bundle, summary


def terminal_policy_evaluation(
    bundle: dict,
    data_dir: Path,
) -> dict:
    loaded = train_models.load_features(data_dir, "terminal_decision")
    classes = bundle["classes"]
    model_order = [list(bundle["model"].classes_).index(label) for label in classes]
    arrived_threshold = bundle["decision_policy"][
        "arrived_zero_false_positive"
    ]["threshold"]
    far_threshold = bundle["decision_policy"][
        "far_zero_false_positive_on_nonfar"
    ]["threshold"]
    result = {}
    for split in ("validation", "test"):
        matrix = bundle["vectorizer"].transform(loaded["features"][split])
        matrix, labels, weights, metadata = train_models.filter_positive_weight(
            matrix,
            np.asarray(loaded["labels"][split], dtype=object),
            np.asarray(loaded["weights"][split], dtype=np.float64),
            loaded["metadata"][split],
        )
        raw = bundle["model"].predict_proba(matrix)[:, model_order]
        probabilities = train_models.apply_temperature(
            raw, bundle["temperature"]
        )
        arrived_scores = probabilities[:, classes.index("arrived")]
        far_scores = probabilities[:, classes.index("far")]
        prediction = np.full(len(labels), "boundary", dtype=object)
        prediction[far_scores >= far_threshold] = "far"
        prediction[arrived_scores >= arrived_threshold] = "arrived"
        arrived_mask = labels == "arrived"
        far_mask = labels == "far"
        result[split] = {
            "rows": int(len(labels)),
            "arrived_false_positives_all_nonarrived": int(
                np.sum((prediction == "arrived") & ~arrived_mask)
            ),
            "arrived_false_positives_true_far": int(
                np.sum((prediction == "arrived") & far_mask)
            ),
            "arrived_recall": float(
                np.mean(prediction[arrived_mask] == "arrived")
            )
            if np.any(arrived_mask)
            else 0.0,
            "far_false_positives_all_nonfar": int(
                np.sum((prediction == "far") & ~far_mask)
            ),
            "far_recall": float(np.mean(prediction[far_mask] == "far"))
            if np.any(far_mask)
            else 0.0,
            "uncertain_fraction": float(np.mean(prediction == "boundary")),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "v1"))
    parser.add_argument("--model-dir", default=str(ROOT / "models" / "v1"))
    parser.add_argument("--report-dir", default=str(ROOT / "reports" / "v1"))
    args = parser.parse_args()
    data_dir = Path(args.data_dir).resolve()
    model_dir = Path(args.model_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "schema": "navila-model-training-report-v1",
        "dataset_schema": "navila-anchor-terminal-training-v1",
        "tasks": {},
    }
    for task in ("anchor_transition", "terminal_decision"):
        bundle, summary = summarize_bundle(model_dir / f"{task}_v1.joblib")
        if task == "terminal_decision":
            summary["policy_evaluation"] = terminal_policy_evaluation(
                bundle, data_dir
            )
        report["tasks"][task] = summary

    (report_dir / "training_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown = train_models.markdown_report(report)
    terminal_policy = report["tasks"]["terminal_decision"]["policy_evaluation"]
    markdown += "## Terminal zero-false-positive policy evaluation\n\n"
    markdown += (
        "| Split | Arrived false positives | Arrived-vs-far false positives | "
        "Arrived recall | Far false positives | Far recall | Uncertain |\n"
    )
    markdown += "|---|---:|---:|---:|---:|---:|---:|\n"
    for split in ("validation", "test"):
        value = terminal_policy[split]
        markdown += (
            f"| {split} | "
            f"{value['arrived_false_positives_all_nonarrived']} | "
            f"{value['arrived_false_positives_true_far']} | "
            f"{value['arrived_recall']:.4f} | "
            f"{value['far_false_positives_all_nonfar']} | "
            f"{value['far_recall']:.4f} | "
            f"{value['uncertain_fraction']:.4f} |\n"
        )
    (report_dir / "training_report.md").write_text(
        markdown, encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
