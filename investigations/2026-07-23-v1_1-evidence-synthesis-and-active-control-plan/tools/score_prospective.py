#!/usr/bin/env python3
"""Score the frozen V1.1 artifact on the predeclared prospective batch."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.audit import attach_episode_metadata, load_episode_metadata, raw_label_audit
from reliability.diagnostics import calibration_curve_equal_mass, expected_calibration_error
from reliability.training import read_dataset
from reliability.v11_dataset import ICP_AMBIGUITY_LEVELS, MATCH_CLASS_LEVELS
from reliability.v11_training import HEADS, load_v11_npz, physical_episode_balanced_weights


GATES = {
    "bearing": {"minimum_auc": 0.80, "maximum_risk_ucb": 0.10, "minimum_coverage": 0.35},
    "distance": {"minimum_auc": 0.92, "maximum_risk_ucb": 0.05, "minimum_coverage": 0.35},
    "pose": {"minimum_auc": 0.96, "maximum_risk_ucb": 0.05, "minimum_coverage": 0.30},
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _metrics(
    target: np.ndarray,
    probability: np.ndarray,
    weight: np.ndarray,
    trusted: np.ndarray,
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    has_both = np.unique(target).size > 1
    curve = calibration_curve_equal_mass(target, probability, weight)
    return {
        "rows": int(len(target)),
        "positive_rate": float(np.average(target, weights=weight)),
        "mean_probability": float(np.average(probability, weights=weight)),
        "roc_auc": float(roc_auc_score(target, probability, sample_weight=weight)) if has_both else None,
        "average_precision": (
            float(average_precision_score(target, probability, sample_weight=weight))
            if has_both else None
        ),
        "brier": float(brier_score_loss(target, probability, sample_weight=weight)),
        "calibration_bias": float(np.average(probability - target, weights=weight)),
        "ece_equal_mass_10": expected_calibration_error(curve),
        "trusted_coverage": float(np.average(trusted, weights=weight)),
        "trusted_bad_rate": (
            float(np.average(target[trusted], weights=weight[trusted])) if trusted.any() else None
        ),
    }


def _cluster_risk_ucb(
    target: np.ndarray,
    trusted: np.ndarray,
    weight: np.ndarray,
    groups: np.ndarray,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    unique_groups, inverse = np.unique(groups, return_inverse=True)
    trusted_weight = np.bincount(
        inverse, weights=weight * trusted, minlength=len(unique_groups)
    )
    bad_weight = np.bincount(
        inverse, weights=weight * trusted * target, minlength=len(unique_groups)
    )
    rng = np.random.default_rng(seed)
    risks = []
    for _ in range(samples):
        draw = rng.integers(0, len(unique_groups), size=len(unique_groups))
        multiplicity = np.bincount(draw, minlength=len(unique_groups))
        denominator = float(multiplicity @ trusted_weight)
        if denominator > 0:
            risks.append(float((multiplicity @ bad_weight) / denominator))
    return {
        "method": "one_sided_95_percent_physical_episode_cluster_bootstrap",
        "physical_episode_clusters": int(len(unique_groups)),
        "samples_requested": int(samples),
        "samples_valid": int(len(risks)),
        "seed": int(seed),
        "upper_95": float(np.quantile(risks, 0.95)) if risks else None,
    }


def _group_macro(
    target: np.ndarray,
    probability: np.ndarray,
    trusted: np.ndarray,
    groups: np.ndarray,
) -> dict[str, Any]:
    per_group = []
    for group in sorted(np.unique(groups).tolist()):
        selected = groups == group
        values = _metrics(
            target[selected],
            probability[selected],
            np.ones(int(selected.sum()), dtype=float),
            trusted[selected],
        )
        per_group.append({"group": str(group), **values})
    output: dict[str, Any] = {"groups": len(per_group), "per_group": per_group}
    for key in (
        "positive_rate",
        "roc_auc",
        "average_precision",
        "brier",
        "ece_equal_mass_10",
        "trusted_coverage",
        "trusted_bad_rate",
    ):
        values = [float(item[key]) for item in per_group if item.get(key) is not None]
        output[key] = float(np.mean(values)) if values else None
        output[f"{key}_groups"] = len(values)
    return output


def _slice_metrics(
    target: np.ndarray,
    probability: np.ndarray,
    trusted: np.ndarray,
    weight: np.ndarray,
    values: np.ndarray,
) -> dict[str, Any]:
    output = {}
    for value in sorted(np.unique(values).tolist()):
        selected = values == value
        output[str(value)] = _metrics(
            target[selected], probability[selected], weight[selected], trusted[selected]
        )
    return output


def _return_stage(episode_id: np.ndarray, attempt: np.ndarray) -> np.ndarray:
    maximum = {
        int(episode): int(np.max(attempt[episode_id == episode]))
        for episode in np.unique(episode_id)
    }
    stages = []
    for episode, current in zip(episode_id.tolist(), attempt.tolist()):
        fraction = float(current) / max(maximum[int(episode)], 1)
        stages.append("early" if fraction <= 1 / 3 else "middle" if fraction <= 2 / 3 else "late")
    return np.asarray(stages)


def _streak_report(
    trusted: np.ndarray,
    episode_id: np.ndarray,
    anchor_index: np.ndarray,
    attempt: np.ndarray,
) -> dict[str, Any]:
    by_stream: dict[tuple[int, int], list[tuple[int, bool]]] = defaultdict(list)
    for episode, anchor, current_attempt, is_trusted in zip(
        episode_id.tolist(), anchor_index.tolist(), attempt.tolist(), trusted.tolist()
    ):
        by_stream[(int(episode), int(anchor))].append((int(current_attempt), bool(is_trusted)))
    trusted_longest, untrusted_longest = [], []
    for values in by_stream.values():
        values.sort()
        for desired, destination in ((True, trusted_longest), (False, untrusted_longest)):
            longest = current = 0
            previous_attempt = None
            for current_attempt, state in values:
                if state == desired and (
                    previous_attempt is None or current_attempt == previous_attempt + 1
                ):
                    current += 1
                elif state == desired:
                    current = 1
                else:
                    current = 0
                longest = max(longest, current)
                previous_attempt = current_attempt
            destination.append(longest)
    return {
        "streams": len(by_stream),
        "trusted_longest_median": float(np.median(trusted_longest)),
        "trusted_longest_p95": float(np.quantile(trusted_longest, 0.95)),
        "trusted_longest_max": int(max(trusted_longest)),
        "untrusted_longest_median": float(np.median(untrusted_longest)),
        "untrusted_longest_p95": float(np.quantile(untrusted_longest, 0.95)),
        "untrusted_longest_max": int(max(untrusted_longest)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    parser.add_argument("--dataset", default=str(here / "prospective_v1_1.npz"))
    parser.add_argument("--v1-dataset", default=str(here / "prospective_v1.csv"))
    parser.add_argument("--v1-manifest", default=str(here / "prospective_v1_manifest.json"))
    parser.add_argument("--config", default=str(here / "config.json"))
    parser.add_argument(
        "--artifact", default=str(ROOT / "artifacts" / "reliability_v1_1_development.pkl")
    )
    parser.add_argument("--output", default=str(here / "prospective_score.json"))
    parser.add_argument("--predictions-csv", default=str(here / "row_predictions.csv"))
    parser.add_argument("--label-audit-csv", default=str(here / "raw_label_audit.csv"))
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260722)
    args = parser.parse_args()

    data = load_v11_npz(args.dataset)
    with open(args.artifact, "rb") as handle:
        artifact = pickle.load(handle)
    labels = np.asarray(data["labels"], dtype=np.int8)
    episodes = np.asarray(data["episode_id"])
    scenes = np.asarray(data["scene_id"])
    attempts = np.asarray(data["attempt"])
    anchors = np.asarray(data["anchor_index"])
    roles = np.asarray(data["anchor_role"])
    weights = physical_episode_balanced_weights(episodes)
    stages = _return_stage(episodes, attempts)

    predictions = {}
    report: dict[str, Any] = {
        "dataset": str(args.dataset),
        "artifact": str(args.artifact),
        "rows": int(len(labels)),
        "physical_episode_clusters": int(len(np.unique(episodes))),
        "scenes": int(len(np.unique(scenes))),
        "frozen": {
            "development_only": artifact.get("development_only"),
            "prospective_validation_passed": artifact.get("prospective_validation_passed"),
            "schema_version": artifact.get("schema_version"),
        },
        "heads": {},
    }
    for head_index, head in enumerate(HEADS):
        values = artifact["heads"][head]
        selected = np.asarray(values["feature_indices"], dtype=int)
        raw = values["model"].predict_proba(data["features"][:, selected])[:, 1]
        probability = np.asarray(values["calibrator"].predict(raw), dtype=float)
        if not np.isfinite(probability).all():
            raise AssertionError(f"non-finite probability for {head}")
        threshold = float(values["trusted_threshold"])
        trusted = probability <= threshold
        target = labels[:, head_index]
        pooled = _metrics(target, probability, weights, trusted)
        bound = _cluster_risk_ucb(
            target, trusted, weights, episodes, args.bootstrap_samples, args.seed + head_index
        )
        gate = GATES[head]
        gate_checks = {
            "auc": pooled["roc_auc"] is not None and pooled["roc_auc"] >= gate["minimum_auc"],
            "trusted_risk_ucb": (
                bound["upper_95"] is not None
                and bound["upper_95"] <= gate["maximum_risk_ucb"]
            ),
            "trusted_coverage": pooled["trusted_coverage"] >= gate["minimum_coverage"],
        }
        scene_macro = _group_macro(target, probability, trusted, scenes)
        worst_scene = max(
            scene_macro["per_group"],
            key=lambda item: -1.0 if item["trusted_bad_rate"] is None else item["trusted_bad_rate"],
        )
        report["heads"][head] = {
            "candidate": values["candidate"],
            "features": int(len(selected)),
            "trusted_threshold": threshold,
            "pooled_episode_balanced": pooled,
            "trusted_risk_bound": bound,
            "gate": gate,
            "gate_checks": gate_checks,
            "gate_passed": all(gate_checks.values()),
            "episode_macro": _group_macro(target, probability, trusted, episodes),
            "scene_macro": scene_macro,
            "worst_scene_by_trusted_bad_rate": worst_scene,
            "role_slices": _slice_metrics(target, probability, trusted, weights, roles),
            "return_stage_slices": _slice_metrics(target, probability, trusted, weights, stages),
            "streaks_by_episode_anchor": _streak_report(trusted, episodes, anchors, attempts),
        }
        predictions[head] = probability

    jointly_trusted = np.logical_and.reduce([
        predictions[head] <= float(artifact["heads"][head]["trusted_threshold"])
        for head in HEADS
    ])
    pose_target = labels[:, 2]
    joint_bound = _cluster_risk_ucb(
        pose_target,
        jointly_trusted,
        weights,
        episodes,
        args.bootstrap_samples,
        args.seed + 10,
    )
    report["joint_operating_point"] = {
        "definition": "all_three_heads_trusted; bad means pose_bad",
        "rows_trusted": int(np.sum(jointly_trusted)),
        "trusted_coverage": float(np.average(jointly_trusted, weights=weights)),
        "trusted_pose_bad_rate": (
            float(np.average(pose_target[jointly_trusted], weights=weights[jointly_trusted]))
            if jointly_trusted.any() else None
        ),
        "trusted_pose_bad_rate_upper_95": joint_bound["upper_95"],
        "cluster_bootstrap": joint_bound,
    }

    maximum_attempt = np.asarray(
        [int(np.max(attempts[episodes == episode])) for episode in np.unique(episodes)]
    )
    report["attempt_availability"] = {
        "max_attempt_per_usable_episode": {
            "minimum": int(np.min(maximum_attempt)),
            "median": float(np.median(maximum_attempt)),
            "p95": float(np.quantile(maximum_attempt, 0.95)),
            "maximum": int(np.max(maximum_attempt)),
        },
        "episodes_available_by_attempt": {
            str(boundary): int(len(np.unique(episodes[attempts >= boundary])))
            for boundary in (1, 10, 25, 50, 100, 200, 400)
        },
    }
    feature_missing = np.mean(~np.isfinite(data["features"]), axis=0)
    order = np.argsort(feature_missing)[::-1]
    report["missingness"] = {
        "features": int(len(data["feature_names"])),
        "completely_missing_features": [
            str(data["feature_names"][index]) for index in order if feature_missing[index] == 1.0
        ],
        "highest_missing_fraction": [
            {
                "feature": str(data["feature_names"][index]),
                "missing_fraction": float(feature_missing[index]),
            }
            for index in order[:20]
        ],
    }
    observed_match = sorted(np.unique(data["match_class"]).tolist())
    observed_ambiguity = sorted(np.unique(data["icp_ambiguity"]).tolist())
    report["categories"] = {
        "match_class_counts": dict(Counter(data["match_class"].tolist())),
        "match_class_unseen": sorted(set(observed_match) - set(MATCH_CLASS_LEVELS)),
        "icp_ambiguity_counts": dict(Counter(data["icp_ambiguity"].tolist())),
        "icp_ambiguity_unseen": sorted(set(observed_ambiguity) - set(ICP_AMBIGUITY_LEVELS)),
    }

    v1_rows = read_dataset(args.v1_dataset)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    attach_episode_metadata(
        v1_rows, load_episode_metadata(config["offline_audit"]["episode_dataset"])
    )
    manifest = json.loads(Path(args.v1_manifest).read_text(encoding="utf-8"))
    report["raw_label_audit"] = raw_label_audit(
        v1_rows,
        manifest,
        int(config["offline_audit"]["label_sample_size"]),
        int(config["offline_audit"]["label_sample_seed"]),
        float(config["labels"]["bearing_bad_deg"]),
        float(config["labels"]["distance_bad_m"]),
        args.label_audit_csv,
    )
    report["overall_gate_passed"] = all(
        report["heads"][head]["gate_passed"] for head in HEADS
    )
    with Path(args.predictions_csv).open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "episode_id", "scene_id", "attempt", "anchor_index", "anchor_role",
            "label_bearing_bad", "label_distance_bad", "label_pose_bad",
            "p_bearing_bad", "p_distance_bad", "p_pose_bad",
            "bearing_trusted", "distance_trusted", "pose_trusted", "jointly_trusted",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(len(labels)):
            writer.writerow({
                "episode_id": int(episodes[index]),
                "scene_id": str(scenes[index]),
                "attempt": int(attempts[index]),
                "anchor_index": int(anchors[index]),
                "anchor_role": str(roles[index]),
                "label_bearing_bad": int(labels[index, 0]),
                "label_distance_bad": int(labels[index, 1]),
                "label_pose_bad": int(labels[index, 2]),
                "p_bearing_bad": float(predictions["bearing"][index]),
                "p_distance_bad": float(predictions["distance"][index]),
                "p_pose_bad": float(predictions["pose"][index]),
                "bearing_trusted": int(
                    predictions["bearing"][index]
                    <= float(artifact["heads"]["bearing"]["trusted_threshold"])
                ),
                "distance_trusted": int(
                    predictions["distance"][index]
                    <= float(artifact["heads"]["distance"]["trusted_threshold"])
                ),
                "pose_trusted": int(
                    predictions["pose"][index]
                    <= float(artifact["heads"]["pose"]["trusted_threshold"])
                ),
                "jointly_trusted": int(jointly_trusted[index]),
            })
    report["row_predictions_csv"] = str(Path(args.predictions_csv))
    Path(args.output).write_text(
        json.dumps(_jsonable(report), indent=2, sort_keys=True), encoding="utf-8"
    )
    concise = {
        "rows": report["rows"],
        "physical_episode_clusters": report["physical_episode_clusters"],
        "overall_gate_passed": report["overall_gate_passed"],
        "raw_label_audit": report["raw_label_audit"],
        "heads": {
            head: {
                "auc": report["heads"][head]["pooled_episode_balanced"]["roc_auc"],
                "trusted_coverage": report["heads"][head]["pooled_episode_balanced"][
                    "trusted_coverage"
                ],
                "trusted_bad_rate": report["heads"][head]["pooled_episode_balanced"][
                    "trusted_bad_rate"
                ],
                "trusted_bad_rate_upper_95": report["heads"][head]["trusted_risk_bound"][
                    "upper_95"
                ],
                "gate_checks": report["heads"][head]["gate_checks"],
            }
            for head in HEADS
        },
        "joint_operating_point": report["joint_operating_point"],
    }
    print(json.dumps(_jsonable(concise), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
