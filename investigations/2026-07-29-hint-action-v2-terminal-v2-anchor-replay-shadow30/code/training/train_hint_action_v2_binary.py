#!/usr/bin/env python3
"""Binary Hint v2 focused on the actual override/no-override decision."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import average_precision_score

from train_hint_action_model import sha256_file
from train_hint_action_v2_robust import (
    load,
    policy_metrics,
    positive_view,
)
from train_models import (
    apply_temperature,
    balanced_training_weights,
    choose_temperature,
    evaluate,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "v1" / "hint_action_decision.jsonl.gz"
DEFAULT_MODEL = ROOT / "models" / "v2" / "hint_action_decision_v2_binary.joblib"
DEFAULT_REPORT = ROOT / "reports" / "v2" / "hint_action_v2_binary_report.json"
DEFAULT_REPORT_MD = ROOT / "reports" / "v2" / "hint_action_v2_binary_report.md"
CLASSES = ["do_not_override", "override_hint"]
SCHEMA = "navila-hint-action-binary-bundle-v2"


def binary_labels(labels: np.ndarray) -> np.ndarray:
    return np.asarray(
        [
            "override_hint"
            if label == "override_hint"
            else "do_not_override"
            for label in labels
        ],
        dtype=object,
    )


def fit_weights(
    labels: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> tuple[np.ndarray, dict[str, float], int]:
    result, mapping = balanced_training_weights(
        labels, weights, CLASSES
    )
    hard = np.asarray(
        [item["hard_negative"] for item in metadata], dtype=bool
    )
    result[hard] *= 2.0
    return result, mapping, int(hard.sum())


def probability_columns(model: Any, matrix: np.ndarray) -> np.ndarray:
    order = [
        list(model.classes_).index(label)
        for label in CLASSES
    ]
    return model.predict_proba(matrix)[:, order]


def choose_advisory(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
    minimum_precision: float = 0.85,
) -> dict[str, Any]:
    thresholds = sorted(
        {
            *(float(value) for value in np.linspace(0.20, 0.995, 160)),
            *(
                float(np.nextafter(value, 1.0))
                for value in scores[labels != "override_hint"]
            ),
        }
    )
    candidates = [
        policy_metrics(
            labels, scores, weights, metadata, threshold, 1, 1, False
        )
        for threshold in thresholds
    ]
    eligible = [
        item
        for item in candidates
        if item["precision"] >= minimum_precision
    ]
    pool = eligible or candidates
    selected = max(
        pool,
        key=lambda item: (
            item["recall"],
            item["precision"],
            -item["threshold"],
        ),
    )
    per_scene = {}
    for scene in sorted({item["scene_id"] for item in metadata}):
        mask = np.asarray(
            [item["scene_id"] == scene for item in metadata]
        )
        scene_meta = [
            metadata[int(index)] for index in np.flatnonzero(mask)
        ]
        per_scene[scene] = policy_metrics(
            labels[mask],
            scores[mask],
            weights[mask],
            scene_meta,
            selected["threshold"],
            1,
            1,
            False,
        )
    selected["per_scene"] = per_scene
    return selected


def choose_safe_execution(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    thresholds = sorted(
        {
            *(float(value) for value in np.linspace(0.30, 0.999, 120)),
            *(
                float(np.nextafter(value, 1.0))
                for value in scores[labels != "override_hint"]
            ),
        }
    )
    scenes = sorted({item["scene_id"] for item in metadata})
    candidates = []
    for threshold in thresholds:
        for streak in (1, 2, 3):
            value = policy_metrics(
                labels,
                scores,
                weights,
                metadata,
                threshold,
                streak,
                1,
                True,
            )
            per_scene = {}
            for scene in scenes:
                mask = np.asarray(
                    [item["scene_id"] == scene for item in metadata]
                )
                scene_meta = [
                    metadata[int(index)]
                    for index in np.flatnonzero(mask)
                ]
                per_scene[scene] = policy_metrics(
                    labels[mask],
                    scores[mask],
                    weights[mask],
                    scene_meta,
                    threshold,
                    streak,
                    1,
                    True,
                )
            value["per_scene"] = per_scene
            candidates.append(value)
    safe = [
        item
        for item in candidates
        if all(
            scene["weighted_false_positive"] <= 1e-12
            for scene in item["per_scene"].values()
        )
    ]
    pool = safe or candidates
    return max(
        pool,
        key=lambda item: (
            item["recall"],
            item["precision"],
            -item["same_kind_streak"],
            -item["threshold"],
        ),
    )


def markdown(report: dict[str, Any]) -> str:
    oof = report["metrics"]["development_oof"]
    test = report["metrics"]["test"]
    advisory_oof = report["advisory_policy"]["development_oof"]
    advisory_test = report["advisory_policy"]["test"]
    execution_oof = report["execution_policy"]["development_oof"]
    execution_test = report["execution_policy"]["test"]
    advisory_clear_oof = report["advisory_clearance_policy"][
        "development_oof"
    ]
    advisory_clear_test = report["advisory_clearance_policy"]["test"]
    return "\n".join(
        [
            "# Hint-action v2 binary shadow model",
            "",
            "This estimator answers only `override_hint` versus "
            "`do_not_override`. The separate clear-path gate remains mandatory "
            "for execution. Prospective ep1008 is not part of training.",
            "",
            f"- artifact: `{report['artifact_path']}`",
            f"- SHA-256: `{report['artifact_sha256']}`",
            f"- selected estimator: `{report['training']['selected_model']}`",
            "",
            "| Evaluation | Balanced accuracy | Macro F1 | Average precision |",
            "|---|---:|---:|---:|",
            f"| development OOF | {oof['balanced_accuracy']:.4f} | "
            f"{oof['macro_f1']:.4f} | "
            f"{report['average_precision']['development_oof']:.4f} |",
            f"| untouched test | {test['balanced_accuracy']:.4f} | "
            f"{test['macro_f1']:.4f} | "
            f"{report['average_precision']['test']:.4f} |",
            "",
            "## Advisory",
            "",
            f"- OOF threshold={advisory_oof['threshold']:.6f}, precision/recall="
            f"{advisory_oof['precision']:.4f}/{advisory_oof['recall']:.4f};",
            f"- test precision/recall={advisory_test['precision']:.4f}/"
            f"{advisory_test['recall']:.4f}.",
            f"- with the independent clearance gate: OOF precision/recall="
            f"{advisory_clear_oof['precision']:.4f}/"
            f"{advisory_clear_oof['recall']:.4f}, test="
            f"{advisory_clear_test['precision']:.4f}/"
            f"{advisory_clear_test['recall']:.4f}.",
            "",
            "## Clearance-gated execution",
            "",
            f"- OOF threshold={execution_oof['threshold']:.6f}, streak="
            f"{execution_oof['same_kind_streak']}, precision/recall="
            f"{execution_oof['precision']:.4f}/{execution_oof['recall']:.4f};",
            f"- test precision/recall={execution_test['precision']:.4f}/"
            f"{execution_test['recall']:.4f}, false-positive weight="
            f"{execution_test['weighted_false_positive']:.2f}.",
            "",
            "Status: shadow-only.",
            "",
        ]
    )


def train(args: argparse.Namespace) -> dict[str, Any]:
    data_path = Path(args.data).resolve()
    loaded = load(data_path)
    vectorizer = DictVectorizer(sparse=False, dtype=np.float32)
    vectorizer.fit(
        loaded["train"]["features"]
        + loaded["validation"]["features"]
    )
    matrices = {
        split: vectorizer.transform(loaded[split]["features"])
        for split in ("train", "validation", "test")
    }
    views = {
        split: positive_view(matrices[split], loaded[split])
        for split in ("train", "validation", "test")
    }
    x_dev = np.vstack((views["train"][0], views["validation"][0]))
    y_dev = binary_labels(
        np.concatenate((views["train"][1], views["validation"][1]))
    )
    w_dev = np.concatenate((views["train"][2], views["validation"][2]))
    meta_dev = views["train"][3] + views["validation"][3]
    y_test = binary_labels(views["test"][1])
    scenes = sorted({item["scene_id"] for item in meta_dev})
    candidates = {
        "regularized_hgb": HistGradientBoostingClassifier(
            learning_rate=0.04,
            max_iter=260,
            max_leaf_nodes=15,
            max_depth=4,
            min_samples_leaf=30,
            max_bins=127,
            l2_regularization=4.0,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=25,
            random_state=20260729,
        ),
        "small_hgb": HistGradientBoostingClassifier(
            learning_rate=0.035,
            max_iter=300,
            max_leaf_nodes=9,
            max_depth=3,
            min_samples_leaf=40,
            max_bins=127,
            l2_regularization=8.0,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=30,
            random_state=20260729,
        ),
    }
    candidate_results = {}
    positive_index = CLASSES.index("override_hint")
    for name, base_model in candidates.items():
        oof_raw = np.zeros((len(y_dev), len(CLASSES)), dtype=np.float64)
        for scene in scenes:
            held_out = np.asarray(
                [item["scene_id"] == scene for item in meta_dev]
            )
            fit = ~held_out
            fit_meta = [
                item for item, keep in zip(meta_dev, fit) if keep
            ]
            weights, _mapping, _hard = fit_weights(
                y_dev[fit], w_dev[fit], fit_meta
            )
            model = clone(base_model)
            print(
                f"[hint-v2-binary:{name}] hold out {scene}: "
                f"train={fit.sum()} test={held_out.sum()}",
                flush=True,
            )
            model.fit(
                x_dev[fit], y_dev[fit], sample_weight=weights
            )
            oof_raw[held_out] = probability_columns(
                model, x_dev[held_out]
            )
        temperature, loss = choose_temperature(
            oof_raw, y_dev, w_dev, CLASSES
        )
        probabilities = apply_temperature(oof_raw, temperature)
        ap = float(
            average_precision_score(
                y_dev == "override_hint",
                probabilities[:, positive_index],
                sample_weight=w_dev,
            )
        )
        candidate_results[name] = {
            "model": base_model,
            "raw": oof_raw,
            "probabilities": probabilities,
            "temperature": temperature,
            "calibrated_log_loss": loss,
            "average_precision": ap,
        }
    selected_name, selected = max(
        candidate_results.items(),
        key=lambda item: item[1]["average_precision"],
    )
    oof_probabilities = selected["probabilities"]
    oof_metrics = evaluate(
        y_dev, oof_probabilities, w_dev, meta_dev, CLASSES
    )
    advisory = choose_advisory(
        y_dev,
        oof_probabilities[:, positive_index],
        w_dev,
        meta_dev,
    )
    execution = choose_safe_execution(
        y_dev,
        oof_probabilities[:, positive_index],
        w_dev,
        meta_dev,
    )

    final_weights, class_mapping, hard_count = fit_weights(
        y_dev, w_dev, meta_dev
    )
    final_model = clone(selected["model"])
    final_model.fit(x_dev, y_dev, sample_weight=final_weights)
    test_probabilities = apply_temperature(
        probability_columns(final_model, views["test"][0]),
        selected["temperature"],
    )
    test_metrics = evaluate(
        y_test,
        test_probabilities,
        views["test"][2],
        views["test"][3],
        CLASSES,
    )
    test_ap = float(
        average_precision_score(
            y_test == "override_hint",
            test_probabilities[:, positive_index],
            sample_weight=views["test"][2],
        )
    )
    advisory_test = policy_metrics(
        y_test,
        test_probabilities[:, positive_index],
        views["test"][2],
        views["test"][3],
        advisory["threshold"],
        1,
        1,
        False,
    )
    advisory_clear_oof = policy_metrics(
        y_dev,
        oof_probabilities[:, positive_index],
        w_dev,
        meta_dev,
        advisory["threshold"],
        1,
        1,
        True,
    )
    advisory_clear_test = policy_metrics(
        y_test,
        test_probabilities[:, positive_index],
        views["test"][2],
        views["test"][3],
        advisory["threshold"],
        1,
        1,
        True,
    )
    execution_test = policy_metrics(
        y_test,
        test_probabilities[:, positive_index],
        views["test"][2],
        views["test"][3],
        execution["threshold"],
        execution["same_kind_streak"],
        execution["same_target_streak"],
        True,
    )
    bundle = {
        "schema": SCHEMA,
        "task": "hint_action_binary",
        "scope": {
            "movement_direction_only": True,
            "stop_authority": False,
            "collision_authority": False,
            "clearance_gate": "independent_hard_gate",
            "integration_status": "shadow_only",
        },
        "classes": CLASSES,
        "feature_names": vectorizer.get_feature_names_out().tolist(),
        "feature_count": len(vectorizer.feature_names_),
        "vectorizer": vectorizer,
        "model": final_model,
        "temperature": selected["temperature"],
        "decision_policy": {
            "advisory": {
                key: advisory[key]
                for key in (
                    "threshold",
                    "same_kind_streak",
                    "same_target_streak",
                    "require_clearance",
                )
            },
            "advisory_clearance": {
                "threshold": advisory["threshold"],
                "same_kind_streak": 1,
                "same_target_streak": 1,
                "require_clearance": True,
            },
            "execution": {
                key: execution[key]
                for key in (
                    "threshold",
                    "same_kind_streak",
                    "same_target_streak",
                    "require_clearance",
                )
            },
            "integration_status": "shadow_only",
        },
        "training": {
            "dataset_path": str(data_path),
            "dataset_sha256": sha256_file(data_path),
            "development_rows": len(y_dev),
            "hard_negative_rows": hard_count,
            "selected_model": selected_name,
            "candidate_average_precision": {
                name: value["average_precision"]
                for name, value in candidate_results.items()
            },
            "class_weight_map": class_mapping,
            "calibration": "leave_one_scene_out",
            "calibrated_log_loss": selected["calibrated_log_loss"],
            "python": __import__("sys").version,
            "sklearn_version": __import__("sklearn").__version__,
            "numpy_version": np.__version__,
        },
        "metrics": {
            "development_oof": oof_metrics,
            "test": test_metrics,
        },
        "average_precision": {
            "development_oof": selected["average_precision"],
            "test": test_ap,
        },
        "advisory_policy": {
            "development_oof": advisory,
            "test": advisory_test,
        },
        "advisory_clearance_policy": {
            "development_oof": advisory_clear_oof,
            "test": advisory_clear_test,
        },
        "execution_policy": {
            "development_oof": execution,
            "test": execution_test,
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
