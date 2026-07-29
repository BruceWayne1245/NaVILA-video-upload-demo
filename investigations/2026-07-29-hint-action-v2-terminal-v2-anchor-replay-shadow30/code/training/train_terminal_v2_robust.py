#!/usr/bin/env python3
"""Terminal v2 with leave-one-scene-out sequence-policy calibration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.feature_extraction import DictVectorizer

from train_models import apply_temperature, choose_temperature, evaluate
from train_terminal_v2 import (
    CLASSES,
    candidate_models,
    load,
    positive_weight_view,
    probability_columns,
    sequence_metrics,
    sha256_file,
    training_weights,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "v1" / "terminal_decision.jsonl.gz"
DEFAULT_MODEL = (
    ROOT / "models" / "v2" / "terminal_decision_v2_robust.joblib"
)
DEFAULT_REPORT = (
    ROOT / "reports" / "v2" / "terminal_v2_robust_report.json"
)
DEFAULT_REPORT_MD = (
    ROOT / "reports" / "v2" / "terminal_v2_robust_report.md"
)
SCHEMA = "navila-terminal-controller-bundle-v2-robust"


def choose_robust_policy(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict],
) -> dict:
    candidates = []
    for threshold in np.linspace(0.50, 0.999, 125):
        for streak in range(2, 13):
            value = sequence_metrics(
                labels,
                scores,
                weights,
                metadata,
                float(threshold),
                streak,
            )
            per_scene = {}
            for scene in sorted({item["scene_id"] for item in metadata}):
                mask = np.asarray(
                    [item["scene_id"] == scene for item in metadata]
                )
                scene_meta = [
                    item for item, keep in zip(metadata, mask) if keep
                ]
                per_scene[scene] = sequence_metrics(
                    labels[mask],
                    scores[mask],
                    weights[mask],
                    scene_meta,
                    float(threshold),
                    streak,
                )
            value["per_scene"] = per_scene
            value["worst_scene_arrived_recall"] = min(
                (
                    item["arrived_recall"]
                    for item in per_scene.values()
                    if item["arrived_recall"] > 0.0
                ),
                default=0.0,
            )
            candidates.append(value)
    safe = [
        item
        for item in candidates
        if all(
            scene["true_far_false_arrived"] == 0
            and scene["boundary_forced_arrived"] == 0
            for scene in item["per_scene"].values()
        )
    ]
    pool = safe or candidates
    return max(
        pool,
        key=lambda item: (
            item["worst_scene_arrived_recall"],
            item["arrived_recall"],
            -item["streak"],
            -item["threshold"],
        ),
    )


def markdown(report: dict) -> str:
    oof = report["metrics"]["development_oof"]
    test = report["metrics"]["test"]
    policy_oof = report["sequence_policy"]["development_oof"]
    policy_test = report["sequence_policy"]["test"]
    return "\n".join(
        [
            "# Terminal v2 robust scene-held-out baseline",
            "",
            "The estimator and arrived confirmation policy are calibrated from "
            "leave-one-scene-out predictions over every development scene. The "
            "test scene is never used for fitting, temperature selection, "
            "threshold selection, or streak selection.",
            "",
            f"- artifact: `{report['artifact_path']}`",
            f"- artifact SHA-256: `{report['artifact_sha256']}`",
            f"- development scenes: {len(report['development_scenes'])}",
            f"- test scenes: {len(report['test_scenes'])}",
            "",
            "| Evaluation | Balanced accuracy | Macro F1 | Log loss |",
            "|---|---:|---:|---:|",
            f"| development OOF | {oof['balanced_accuracy']:.4f} | "
            f"{oof['macro_f1']:.4f} | {oof['log_loss']:.4f} |",
            f"| untouched test | {test['balanced_accuracy']:.4f} | "
            f"{test['macro_f1']:.4f} | {test['log_loss']:.4f} |",
            "",
            "## Sequence safety",
            "",
            f"- OOF-selected threshold={policy_oof['threshold']:.4f}, "
            f"streak={policy_oof['streak']}, arrived recall="
            f"{policy_oof['arrived_recall']:.4f}, true-far false-arrived="
            f"{policy_oof['true_far_false_arrived']}, boundary forced-arrived="
            f"{policy_oof['boundary_forced_arrived']}.",
            f"- Untouched test: arrived recall={policy_test['arrived_recall']:.4f}, "
            f"true-far false-arrived="
            f"{policy_test['true_far_false_arrived']}, boundary forced-arrived="
            f"{policy_test['boundary_forced_arrived']}.",
            "",
            "Status: shadow-only. A zero false-arrived result with negligible "
            "arrived recall is still not an activation pass.",
            "",
        ]
    )


def train(args: argparse.Namespace) -> dict:
    data_path = Path(args.data).resolve()
    loaded = load(data_path)
    vectorizer = DictVectorizer(sparse=False, dtype=np.float32)
    all_development_features = (
        loaded["train"]["features"] + loaded["validation"]["features"]
    )
    vectorizer.fit(all_development_features)
    matrices = {
        split: vectorizer.transform(loaded[split]["features"])
        for split in ("train", "validation", "test")
    }
    views = {
        split: positive_weight_view(matrices[split], loaded[split])
        for split in ("train", "validation", "test")
    }
    x_dev = np.vstack((views["train"][0], views["validation"][0]))
    y_dev = np.concatenate((views["train"][1], views["validation"][1]))
    w_dev = np.concatenate((views["train"][2], views["validation"][2]))
    meta_dev = views["train"][3] + views["validation"][3]
    development_scenes = sorted(
        {item["scene_id"] for item in meta_dev}
    )
    oof_raw = np.zeros((len(y_dev), len(CLASSES)), dtype=np.float64)
    base_model = candidate_models()["regularized_hgb"]
    for scene in development_scenes:
        held_out = np.asarray(
            [item["scene_id"] == scene for item in meta_dev]
        )
        fit_mask = ~held_out
        fit_meta = [
            item for item, keep in zip(meta_dev, fit_mask) if keep
        ]
        fit_weights, _mapping = training_weights(
            y_dev[fit_mask],
            w_dev[fit_mask],
            fit_meta,
        )
        model = clone(base_model)
        print(
            f"[terminal-v2-robust] hold out {scene}: "
            f"train={fit_mask.sum()} test={held_out.sum()}",
            flush=True,
        )
        model.fit(
            x_dev[fit_mask],
            y_dev[fit_mask],
            sample_weight=fit_weights,
        )
        oof_raw[held_out] = probability_columns(
            model, x_dev[held_out]
        )
    temperature, _loss = choose_temperature(
        oof_raw, y_dev, w_dev, CLASSES
    )
    oof_probabilities = apply_temperature(oof_raw, temperature)
    oof_metrics = evaluate(
        y_dev,
        oof_probabilities,
        w_dev,
        meta_dev,
        CLASSES,
    )
    arrived_index = CLASSES.index("arrived")
    policy = choose_robust_policy(
        y_dev,
        oof_probabilities[:, arrived_index],
        w_dev,
        meta_dev,
    )

    final_weights, class_weights = training_weights(
        y_dev, w_dev, meta_dev
    )
    final_model = clone(base_model)
    final_model.fit(x_dev, y_dev, sample_weight=final_weights)
    test_probabilities = apply_temperature(
        probability_columns(final_model, views["test"][0]),
        temperature,
    )
    test_metrics = evaluate(
        views["test"][1],
        test_probabilities,
        views["test"][2],
        views["test"][3],
        CLASSES,
    )
    test_policy = sequence_metrics(
        views["test"][1],
        test_probabilities[:, arrived_index],
        views["test"][2],
        views["test"][3],
        policy["threshold"],
        policy["streak"],
    )
    bundle = {
        "schema": SCHEMA,
        "task": "terminal_decision",
        "classes": CLASSES,
        "feature_names": vectorizer.get_feature_names_out().tolist(),
        "feature_count": len(vectorizer.feature_names_),
        "vectorizer": vectorizer,
        "model": final_model,
        "temperature": temperature,
        "development_scenes": development_scenes,
        "test_scenes": sorted(
            {item["scene_id"] for item in views["test"][3]}
        ),
        "decision_policy": {
            "arrived_sequence_confirmation": policy,
            "boundary_action": "verify",
            "integration_status": "shadow_only",
        },
        "training": {
            "dataset_path": str(data_path),
            "dataset_sha256": sha256_file(data_path),
            "development_rows": len(y_dev),
            "class_weights": class_weights,
            "calibration": "leave_one_scene_out",
            "python": __import__("sys").version,
            "sklearn_version": __import__("sklearn").__version__,
            "numpy_version": np.__version__,
        },
        "metrics": {
            "development_oof": oof_metrics,
            "test": test_metrics,
        },
        "sequence_policy": {
            "development_oof": policy,
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
    report_md = Path(args.report_md).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md.write_text(markdown(summary), encoding="utf-8")
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
