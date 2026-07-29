#!/usr/bin/env python3
"""Train Hint v2 with scene-OOF calibration and an independent clearance gate."""

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

from hint_action_v2_features import (
    HintActionV2FeatureState,
    clearance_metadata,
)
from train_hint_action_model import (
    CLASSES,
    historical_metrics,
    oracle_source,
    read_rows,
    sha256_file,
)
from train_models import (
    apply_temperature,
    balanced_training_weights,
    choose_temperature,
    evaluate,
    filter_positive_weight,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "v1" / "hint_action_decision.jsonl.gz"
DEFAULT_MODEL = ROOT / "models" / "v2" / "hint_action_decision_v2_robust.joblib"
DEFAULT_REPORT = ROOT / "reports" / "v2" / "hint_action_v2_robust_report.json"
DEFAULT_REPORT_MD = ROOT / "reports" / "v2" / "hint_action_v2_robust_report.md"
SCHEMA = "navila-hint-action-controller-bundle-v2-robust"


def load(path: Path) -> dict[str, Any]:
    result = {
        split: {"features": [], "labels": [], "weights": [], "metadata": []}
        for split in ("train", "validation", "test")
    }
    states: dict[str, HintActionV2FeatureState] = {}
    skipped_oracle = 0
    for row in read_rows(path):
        if oracle_source(row):
            skipped_oracle += 1
            continue
        key = row["episode"]["episode_key"]
        state = states.setdefault(key, HintActionV2FeatureState())
        feature = state.transform(row)
        split = row["episode"]["split"]
        clearance = clearance_metadata(row)
        route_memory = row["inputs"].get("route_memory") or {}
        confidence = route_memory.get("relocalization_confidence")
        bearing = (
            row["inputs"].get("arbiter_proposal") or {}
        ).get("desired_bearing_deg")
        label = row["labels"]["decision"]
        hard_negative = bool(
            label == "keep_vlm"
            and (
                (
                    bearing is not None
                    and abs(float(bearing)) >= 150.0
                )
                or (
                    confidence is not None
                    and float(confidence) < 0.80
                )
                or route_memory.get("estimate_kind")
                == "geometry_reconstructed"
            )
        )
        result[split]["features"].append(feature)
        result[split]["labels"].append(label)
        result[split]["weights"].append(
            float(row["labels"]["sample_weight"])
        )
        result[split]["metadata"].append(
            {
                "episode_key": key,
                "physical_episode_id": row["episode"][
                    "physical_episode_id"
                ],
                "scene_id": row["episode"]["scene_id"],
                "step": int(row["time"]["step"]),
                "historical_override": bool(
                    row["historical_policy"]["override"]
                ),
                "clearance_available": clearance["available"],
                "clearance_clear": clearance["clear"],
                "same_kind_streak": int(
                    feature["temporal.proposal.same_kind_streak"]
                ),
                "same_target_streak": int(
                    feature["temporal.proposal.same_target_streak"]
                ),
                "hard_negative": hard_negative,
            }
        )
    result["skipped_oracle_source_rows"] = skipped_oracle
    return result


def positive_view(
    matrix: np.ndarray,
    split: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    return filter_positive_weight(
        matrix,
        np.asarray(split["labels"], dtype=object),
        np.asarray(split["weights"], dtype=np.float64),
        split["metadata"],
    )


def training_weights(
    labels: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> tuple[np.ndarray, dict[str, float], int]:
    balanced, mapping = balanced_training_weights(labels, weights, CLASSES)
    hard = np.asarray(
        [item["hard_negative"] for item in metadata], dtype=bool
    )
    balanced[hard] *= 2.0
    return balanced, mapping, int(hard.sum())


def probability_columns(
    model: HistGradientBoostingClassifier,
    matrix: np.ndarray,
) -> np.ndarray:
    order = [
        list(model.classes_).index(label)
        for label in CLASSES
    ]
    return model.predict_proba(matrix)[:, order]


def policy_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
    threshold: float,
    same_kind_streak: int,
    same_target_streak: int,
    require_clearance: bool,
) -> dict[str, Any]:
    eligible = np.ones(len(labels), dtype=bool)
    if require_clearance:
        eligible = np.asarray(
            [
                item["clearance_available"]
                and item["clearance_clear"] is True
                for item in metadata
            ],
            dtype=bool,
        )
    stable = np.asarray(
        [
            item["same_kind_streak"] >= same_kind_streak
            and item["same_target_streak"] >= same_target_streak
            for item in metadata
        ],
        dtype=bool,
    )
    predicted = scores >= float(threshold)
    predicted &= stable
    predicted &= eligible
    positive = labels == "override_hint"
    considered_weights = weights * eligible
    tp = float(weights[predicted & positive].sum())
    fp = float(weights[predicted & ~positive].sum())
    fn = float(weights[eligible & ~predicted & positive].sum())
    tn = float(weights[eligible & ~predicted & ~positive].sum())
    total = float(considered_weights.sum())
    positive_total = tp + fn
    return {
        "threshold": float(threshold),
        "same_kind_streak": int(same_kind_streak),
        "same_target_streak": int(same_target_streak),
        "require_clearance": bool(require_clearance),
        "eligible_weight": total,
        "positive_eligible_weight": positive_total,
        "blocked_by_clearance_weight": float(
            weights[~eligible].sum()
        ) if require_clearance else 0.0,
        "weighted_true_positive": tp,
        "weighted_false_positive": fp,
        "weighted_false_negative": fn,
        "weighted_true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / positive_total if positive_total else 0.0,
        "coverage": (tp + fp) / total if total else 0.0,
    }


def choose_policy(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    negative_scores = scores[labels != "override_hint"]
    thresholds = sorted(
        {
            *(float(value) for value in np.linspace(0.50, 0.999, 100)),
            *(
                float(np.nextafter(value, 1.0))
                for value in negative_scores
            ),
        }
    )
    scenes = sorted({item["scene_id"] for item in metadata})
    candidates = []
    for threshold in thresholds:
        for kind_streak in (1, 2, 3):
            for target_streak in (1, 2, 3):
                overall = policy_metrics(
                    labels,
                    scores,
                    weights,
                    metadata,
                    threshold,
                    kind_streak,
                    target_streak,
                    True,
                )
                per_scene = {}
                for scene in scenes:
                    mask = np.asarray(
                        [item["scene_id"] == scene for item in metadata]
                    )
                    scene_meta = [
                        item
                        for item, keep in zip(metadata, mask)
                        if keep
                    ]
                    per_scene[scene] = policy_metrics(
                        labels[mask],
                        scores[mask],
                        weights[mask],
                        scene_meta,
                        threshold,
                        kind_streak,
                        target_streak,
                        True,
                    )
                recalls = [
                    item["recall"]
                    for item in per_scene.values()
                    if item["positive_eligible_weight"] > 0.0
                ]
                overall["per_scene"] = per_scene
                overall["worst_scene_recall"] = min(
                    recalls, default=0.0
                )
                candidates.append(overall)
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
            item["worst_scene_recall"],
            item["recall"],
            item["precision"],
            -item["same_kind_streak"],
            -item["same_target_streak"],
            -item["threshold"],
        ),
    )


def choose_advisory_policy(
    labels: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    thresholds = sorted(
        {
            *(float(value) for value in np.linspace(0.30, 0.99, 139)),
            *(
                float(np.nextafter(value, 1.0))
                for value in scores[labels != "override_hint"]
            ),
        }
    )
    scenes = sorted({item["scene_id"] for item in metadata})
    candidates = []
    for threshold in thresholds:
        overall = policy_metrics(
            labels, scores, weights, metadata, threshold, 1, 1, False
        )
        per_scene = {}
        for scene in scenes:
            mask = np.asarray(
                [item["scene_id"] == scene for item in metadata]
            )
            scene_meta = [
                item for item, keep in zip(metadata, mask) if keep
            ]
            per_scene[scene] = policy_metrics(
                labels[mask],
                scores[mask],
                weights[mask],
                scene_meta,
                threshold,
                1,
                1,
                False,
            )
        overall["per_scene"] = per_scene
        predicted_scenes = [
            item
            for item in per_scene.values()
            if (
                item["weighted_true_positive"]
                + item["weighted_false_positive"]
            )
            > 0.0
        ]
        overall["worst_predicted_scene_precision"] = min(
            (item["precision"] for item in predicted_scenes),
            default=0.0,
        )
        candidates.append(overall)
    robust = [
        item
        for item in candidates
        if item["precision"] >= 0.90
        and item["worst_predicted_scene_precision"] >= 0.80
    ]
    pool = robust or candidates
    return max(
        pool,
        key=lambda item: (
            item["recall"],
            item["precision"],
            -item["threshold"],
        ),
    )


def markdown(report: dict[str, Any]) -> str:
    oof = report["metrics"]["development_oof"]
    test = report["metrics"]["test"]
    policy_oof = report["execution_policy"]["development_oof"]
    policy_test = report["execution_policy"]["test"]
    route_test = report["route_recommendation"]["test"]
    advisory_oof = report["advisory_policy"]["development_oof"]
    advisory_test = report["advisory_policy"]["test"]
    return "\n".join(
        [
            "# Hint-action v2 robust shadow model",
            "",
            "The estimator predicts movement-direction preference. A separate "
            "deterministic clear-path gate decides whether a recommendation is "
            "executable. The untouched test scene and prospective 5ep are not "
            "used for fitting or policy selection.",
            "",
            f"- artifact: `{report['artifact_path']}`",
            f"- artifact SHA-256: `{report['artifact_sha256']}`",
            f"- features: {report['feature_count']}",
            f"- hard negatives in development fit: "
            f"{report['training']['hard_negative_rows']}",
            "",
            "| Evaluation | Balanced accuracy | Macro F1 | ROC AUC |",
            "|---|---:|---:|---:|",
            f"| development OOF | {oof['balanced_accuracy']:.4f} | "
            f"{oof['macro_f1']:.4f} | {oof['roc_auc_ovr_macro']:.4f} |",
            f"| untouched test | {test['balanced_accuracy']:.4f} | "
            f"{test['macro_f1']:.4f} | {test['roc_auc_ovr_macro']:.4f} |",
            "",
            "## Frozen execution policy",
            "",
            f"- threshold={policy_oof['threshold']:.6f}, same-kind streak="
            f"{policy_oof['same_kind_streak']}, same-target streak="
            f"{policy_oof['same_target_streak']};",
            f"- development OOF executable precision/recall="
            f"{policy_oof['precision']:.4f}/{policy_oof['recall']:.4f}, "
            f"false-positive weight={policy_oof['weighted_false_positive']:.2f};",
            f"- untouched test executable precision/recall="
            f"{policy_test['precision']:.4f}/{policy_test['recall']:.4f}, "
            f"false-positive weight={policy_test['weighted_false_positive']:.2f};",
            f"- untouched test route-recommendation precision/recall before "
            f"clearance={route_test['precision']:.4f}/{route_test['recall']:.4f}.",
            "",
            "## Frozen advisory policy",
            "",
            f"- threshold={advisory_oof['threshold']:.6f}; development OOF "
            f"precision/recall={advisory_oof['precision']:.4f}/"
            f"{advisory_oof['recall']:.4f};",
            f"- untouched test precision/recall={advisory_test['precision']:.4f}/"
            f"{advisory_test['recall']:.4f}.",
            "",
            "Status: shadow-only.",
            "",
        ]
    )


def train(args: argparse.Namespace) -> dict[str, Any]:
    data_path = Path(args.data).resolve()
    loaded = load(data_path)
    vectorizer = DictVectorizer(sparse=False, dtype=np.float32)
    development_features = (
        loaded["train"]["features"] + loaded["validation"]["features"]
    )
    vectorizer.fit(development_features)
    matrices = {
        split: vectorizer.transform(loaded[split]["features"])
        for split in ("train", "validation", "test")
    }
    views = {
        split: positive_view(matrices[split], loaded[split])
        for split in ("train", "validation", "test")
    }
    x_dev = np.vstack((views["train"][0], views["validation"][0]))
    y_dev = np.concatenate((views["train"][1], views["validation"][1]))
    w_dev = np.concatenate((views["train"][2], views["validation"][2]))
    meta_dev = views["train"][3] + views["validation"][3]
    scenes = sorted({item["scene_id"] for item in meta_dev})
    base_model = HistGradientBoostingClassifier(
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
    )
    oof_raw = np.zeros((len(y_dev), len(CLASSES)), dtype=np.float64)
    for scene in scenes:
        held_out = np.asarray(
            [item["scene_id"] == scene for item in meta_dev]
        )
        fit = ~held_out
        fit_meta = [
            item for item, keep in zip(meta_dev, fit) if keep
        ]
        fit_weights, _mapping, hard_count = training_weights(
            y_dev[fit], w_dev[fit], fit_meta
        )
        model = clone(base_model)
        print(
            f"[hint-v2] hold out {scene}: train={fit.sum()} "
            f"test={held_out.sum()} hard_negatives={hard_count}",
            flush=True,
        )
        model.fit(
            x_dev[fit],
            y_dev[fit],
            sample_weight=fit_weights,
        )
        oof_raw[held_out] = probability_columns(
            model, x_dev[held_out]
        )
    temperature, calibrated_loss = choose_temperature(
        oof_raw, y_dev, w_dev, CLASSES
    )
    oof_probabilities = apply_temperature(oof_raw, temperature)
    oof_metrics = evaluate(
        y_dev, oof_probabilities, w_dev, meta_dev, CLASSES
    )
    override_index = CLASSES.index("override_hint")
    execution_policy = choose_policy(
        y_dev,
        oof_probabilities[:, override_index],
        w_dev,
        meta_dev,
    )
    advisory_policy = choose_advisory_policy(
        y_dev,
        oof_probabilities[:, override_index],
        w_dev,
        meta_dev,
    )

    final_weights, class_mapping, hard_count = training_weights(
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
    policy_args = (
        execution_policy["threshold"],
        execution_policy["same_kind_streak"],
        execution_policy["same_target_streak"],
    )
    test_execution = policy_metrics(
        views["test"][1],
        test_probabilities[:, override_index],
        views["test"][2],
        views["test"][3],
        *policy_args,
        True,
    )
    route_oof = policy_metrics(
        y_dev,
        oof_probabilities[:, override_index],
        w_dev,
        meta_dev,
        *policy_args,
        False,
    )
    route_test = policy_metrics(
        views["test"][1],
        test_probabilities[:, override_index],
        views["test"][2],
        views["test"][3],
        *policy_args,
        False,
    )
    advisory_args = (
        advisory_policy["threshold"],
        advisory_policy["same_kind_streak"],
        advisory_policy["same_target_streak"],
    )
    advisory_test = policy_metrics(
        views["test"][1],
        test_probabilities[:, override_index],
        views["test"][2],
        views["test"][3],
        *advisory_args,
        False,
    )
    bundle = {
        "schema": SCHEMA,
        "task": "hint_action_decision",
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
        "temperature": temperature,
        "development_scenes": scenes,
        "test_scenes": sorted(
            {item["scene_id"] for item in views["test"][3]}
        ),
        "decision_policy": {
            "advisory": {
                key: advisory_policy[key]
                for key in (
                    "threshold",
                    "same_kind_streak",
                    "same_target_streak",
                    "require_clearance",
                )
            },
            "execution": {
                key: execution_policy[key]
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
            "class_weight_map": class_mapping,
            "calibration": "leave_one_scene_out",
            "calibrated_log_loss": calibrated_loss,
            "skipped_oracle_source_rows": loaded[
                "skipped_oracle_source_rows"
            ],
            "python": __import__("sys").version,
            "sklearn_version": __import__("sklearn").__version__,
            "numpy_version": np.__version__,
        },
        "metrics": {
            "development_oof": oof_metrics,
            "test": test_metrics,
        },
        "execution_policy": {
            "development_oof": execution_policy,
            "test": test_execution,
        },
        "advisory_policy": {
            "development_oof": advisory_policy,
            "test": advisory_test,
        },
        "route_recommendation": {
            "development_oof": route_oof,
            "test": route_test,
        },
        "historical_policy": {
            "development": historical_metrics(y_dev, w_dev, meta_dev),
            "test": historical_metrics(
                views["test"][1],
                views["test"][2],
                views["test"][3],
            ),
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
