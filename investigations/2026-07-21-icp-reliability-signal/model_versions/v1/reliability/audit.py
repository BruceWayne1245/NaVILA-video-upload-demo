"""Group-aware offline audit for the frozen Reliability V1 artifact.

The artifact is evaluated without retraining. The audit adds cluster-aware
metrics, risk/coverage curves, a scalar ICP baseline, and raw-source label
checks that re-read measurements and trajectories.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from .bundle import ReliabilityBundle
from .calibration import PlattCalibrator, trusted_threshold
from .dataset import load_json, load_trajectory
from .training import HEAD_LABELS, strict_chronological_split


BASELINE_SIGNALS = {
    "negative_confidence": ("confidence", -1.0),
    "negative_overlap_ratio": ("overlap_ratio", -1.0),
    "median_residual_m": ("median_residual_m", 1.0),
    "mean_residual_m": ("mean_residual_m", 1.0),
    "negative_degeneracy_ratio": ("corridor_degeneracy_ratio", -1.0),
    "near_tie_basin_count": ("icp_near_tie_basin_count", 1.0),
    "localizability_condition_number": ("localizability_condition_number", 1.0),
    "negative_min_normalized_eigenvalue": (
        "localizability_min_normalized_eigenvalue",
        -1.0,
    ),
}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_episode_metadata(path: str | Path) -> dict[int, dict[str, Any]]:
    """Map CLI episode indices used in run suffixes to dataset metadata."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        episodes = (json.load(handle).get("episodes") or [])
    return {
        index: {
            "scene_id": Path(str(episode.get("scene_id") or "unknown")).stem,
            "dataset_episode_id": episode.get("episode_id"),
            "trajectory_id": episode.get("trajectory_id"),
        }
        for index, episode in enumerate(episodes)
    }


def attach_episode_metadata(
    rows: list[dict[str, Any]], metadata: Mapping[int, Mapping[str, Any]]
) -> None:
    for row in rows:
        episode_index = int(row["episode_id"])
        if episode_index not in metadata:
            raise KeyError(f"episode index {episode_index} is absent from the episode dataset")
        row.update(metadata[episode_index])


def _weighted_metrics(
    target: np.ndarray,
    score: np.ndarray,
    weight: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    target = np.asarray(target, dtype=np.int64)
    score = np.asarray(score, dtype=np.float64)
    weight = np.asarray(weight, dtype=np.float64)
    positive_weight = weight > 0
    trusted = score <= float(threshold)
    result: dict[str, Any] = {
        "rows": int(target.size),
        "positive_rate": float(np.average(target, weights=weight)),
        "brier": float(brier_score_loss(target, score, sample_weight=weight)),
        "trusted_threshold": float(threshold),
        "trusted_coverage": float(np.average(trusted, weights=weight)),
        "trusted_bad_rate": (
            float(np.average(target[trusted], weights=weight[trusted]))
            if trusted.any() and float(weight[trusted].sum()) > 0.0
            else None
        ),
    }
    if np.unique(target[positive_weight]).size > 1:
        result["roc_auc"] = float(roc_auc_score(target, score, sample_weight=weight))
        result["average_precision"] = float(
            average_precision_score(target, score, sample_weight=weight)
        )
    else:
        result["roc_auc"] = None
        result["average_precision"] = None
    return result


def grouped_macro_metrics(
    rows: list[dict[str, Any]],
    target: np.ndarray,
    score: np.ndarray,
    threshold: float,
    group_column: str,
) -> dict[str, Any]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[str(row[group_column])].append(index)
    per_group = []
    for group, indices in sorted(grouped.items()):
        selected = np.asarray(indices, dtype=np.int64)
        metrics = _weighted_metrics(
            target[selected], score[selected], np.ones(selected.size), threshold
        )
        per_group.append({"group": group, **metrics})
    metric_names = (
        "positive_rate",
        "roc_auc",
        "average_precision",
        "brier",
        "trusted_coverage",
        "trusted_bad_rate",
    )
    macro: dict[str, Any] = {"groups": len(per_group)}
    for name in metric_names:
        values = [float(item[name]) for item in per_group if item.get(name) is not None]
        macro[name] = float(np.mean(values)) if values else None
        macro[f"{name}_groups"] = len(values)
    macro["per_group"] = per_group
    return macro


def cluster_bootstrap_intervals(
    rows: list[dict[str, Any]],
    target: np.ndarray,
    score: np.ndarray,
    base_weight: np.ndarray,
    threshold: float,
    group_column: str,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """Resample whole clusters; never treat correlated readings as IID."""
    group_names = sorted({str(row[group_column]) for row in rows})
    group_to_index = {name: index for index, name in enumerate(group_names)}
    row_group = np.asarray([group_to_index[str(row[group_column])] for row in rows])
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(int(samples)):
        selected = rng.integers(0, len(group_names), size=len(group_names))
        multiplicity = np.bincount(selected, minlength=len(group_names))
        weight = np.asarray(base_weight, dtype=np.float64) * multiplicity[row_group]
        metrics = _weighted_metrics(target, score, weight, threshold)
        for name in (
            "positive_rate",
            "roc_auc",
            "average_precision",
            "brier",
            "trusted_coverage",
            "trusted_bad_rate",
        ):
            value = metrics.get(name)
            if value is not None and math.isfinite(float(value)):
                draws[name].append(float(value))
    intervals: dict[str, Any] = {
        "method": f"{group_column}_cluster_percentile_bootstrap",
        "clusters": len(group_names),
        "samples_requested": int(samples),
        "seed": int(seed),
    }
    for name, values in draws.items():
        intervals[name] = {
            "low": float(np.quantile(values, 0.025)),
            "high": float(np.quantile(values, 0.975)),
            "valid_samples": len(values),
        }
    return intervals


def risk_coverage_curve(
    target: np.ndarray,
    score: np.ndarray,
    weight: np.ndarray,
    coverage_grid: Iterable[float] | None = None,
) -> list[dict[str, float]]:
    """Empirical selective risk for lowest predicted-risk prefixes."""
    if coverage_grid is None:
        coverage_grid = np.linspace(0.05, 1.0, 20)
    order = np.argsort(np.asarray(score), kind="stable")
    ordered_target = np.asarray(target, dtype=float)[order]
    ordered_score = np.asarray(score, dtype=float)[order]
    ordered_weight = np.asarray(weight, dtype=float)[order]
    cumulative_weight = np.cumsum(ordered_weight)
    cumulative_bad = np.cumsum(ordered_weight * ordered_target)
    total_weight = float(cumulative_weight[-1])
    result = []
    for requested in coverage_grid:
        index = int(np.searchsorted(cumulative_weight, float(requested) * total_weight, side="left"))
        index = min(max(index, 0), len(order) - 1)
        result.append({
            "requested_coverage": float(requested),
            "coverage": float(cumulative_weight[index] / total_weight),
            "bad_rate": float(cumulative_bad[index] / cumulative_weight[index]),
            "score_threshold": float(ordered_score[index]),
        })
    return result


def _numeric_signal(rows: list[dict[str, Any]], field: str, direction: float) -> np.ndarray:
    values = []
    for row in rows:
        value = row.get(field)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = float("nan")
        values.append(numeric if math.isfinite(numeric) else float("nan"))
    return direction * np.asarray(values, dtype=np.float64)


def select_simple_baseline(
    calibration_rows: list[dict[str, Any]],
    calibration_target: np.ndarray,
    calibration_weight: np.ndarray,
) -> dict[str, Any]:
    from sklearn.metrics import roc_auc_score

    candidates = []
    for name, (field, direction) in BASELINE_SIGNALS.items():
        signal = _numeric_signal(calibration_rows, field, direction)
        finite = np.isfinite(signal)
        if not finite.any():
            continue
        fill_value = float(np.median(signal[finite]))
        filled = np.where(finite, signal, fill_value)
        auc = float(roc_auc_score(calibration_target, filled, sample_weight=calibration_weight))
        candidates.append({
            "name": name,
            "field": field,
            "direction": direction,
            "fill_value": fill_value,
            "calibration_auc": auc,
            "missing_fraction": float(np.mean(~finite)),
        })
    if not candidates:
        raise ValueError("none of the configured ICP baseline signals are available")
    selected = max(candidates, key=lambda item: item["calibration_auc"])
    return {**selected, "candidates": candidates}


def apply_simple_baseline(rows: list[dict[str, Any]], baseline: Mapping[str, Any]) -> np.ndarray:
    signal = _numeric_signal(rows, str(baseline["field"]), float(baseline["direction"]))
    return np.where(np.isfinite(signal), signal, float(baseline["fill_value"]))


def _independent_bearing_distance(
    robot_x: float,
    robot_y: float,
    robot_yaw: float,
    anchor_x: float,
    anchor_y: float,
) -> tuple[float, float]:
    world_dx, world_dy = anchor_x - robot_x, anchor_y - robot_y
    body_x = world_dx * math.cos(robot_yaw) + world_dy * math.sin(robot_yaw)
    body_y = -world_dx * math.sin(robot_yaw) + world_dy * math.cos(robot_yaw)
    return math.degrees(math.atan2(body_y, body_x)), math.hypot(body_x, body_y)


def _wrapped_abs_difference_degrees(first: float, second: float) -> float:
    return abs((float(first) - float(second) + 180.0) % 360.0 - 180.0)


def _stratified_sample_indices(
    rows: list[dict[str, Any]], sample_size: int, seed: int
) -> list[int]:
    """Balance batches/classes and favor episode diversity before repeats."""
    buckets: dict[tuple[str, int], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(rows):
        buckets[(str(row["batch"]), int(row["label_pose_bad"]))][str(row["episode_key"])].append(index)
    rng = np.random.default_rng(seed)
    bucket_keys = sorted(buckets)
    base, remainder = divmod(int(sample_size), len(bucket_keys))
    chosen: list[int] = []
    for bucket_position, bucket_key in enumerate(bucket_keys):
        quota = base + int(bucket_position < remainder)
        episode_groups = list(buckets[bucket_key].values())
        rng.shuffle(episode_groups)
        for indices in episode_groups:
            rng.shuffle(indices)
        pool: list[int] = []
        depth = 0
        while len(pool) < quota and any(depth < len(indices) for indices in episode_groups):
            for indices in episode_groups:
                if depth < len(indices):
                    pool.append(indices[depth])
                    if len(pool) == quota:
                        break
            depth += 1
        chosen.extend(pool)
    return sorted(chosen)


def raw_label_audit(
    rows: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    sample_size: int,
    seed: int,
    bearing_bad_deg: float,
    distance_bad_m: float,
    output_csv: str | Path,
) -> dict[str, Any]:
    """Re-read raw files for a deterministic, human-inspectable label sample."""
    run_lookup = {
        (str(run["batch"]), int(run["episode_id"])): run
        for run in manifest.get("runs", [])
        if run.get("status") == "ok"
    }
    selected_indices = _stratified_sample_indices(rows, sample_size, seed)
    selected_by_run: dict[tuple[str, int], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index in selected_indices:
        row = rows[index]
        selected_by_run[(str(row["batch"]), int(row["episode_id"]))].append((index, row))

    audit_rows: list[dict[str, Any]] = []
    schedule_checks = []
    # Check the code-derived attempt schedule in every usable run. Only the
    # deterministic stratified subset below receives the more expensive
    # per-reading arithmetic audit.
    for run_key, run in sorted(run_lookup.items()):
        selected = selected_by_run.get(run_key, [])
        measurement = load_json(run["measurement"])
        round_trip = measurement.get("round_trip") or {}
        diagnostics = round_trip.get("route_relocalization_diagnostics") or {}
        records = diagnostics.get("covisibility_records") or []
        trajectory = load_trajectory(run["trajectory"])
        return_rows = [row for row in trajectory if row.get("phase") == "return"]
        interval = int((round_trip.get("route_memory") or {})["relocalization_interval_updates"])
        expected_attempts = 1 + len(return_rows) // interval if return_rows else 0
        diagnostic_attempts = int(diagnostics.get("attempts") or 0)
        observed_attempts = sorted({
            int(record["attempt"]) for record in records if record.get("attempt") is not None
        })
        schedule_checks.append({
            "batch": run_key[0],
            "episode_id": run_key[1],
            "return_rows": len(return_rows),
            "interval": interval,
            "expected_attempts": expected_attempts,
            "diagnostic_attempts": diagnostic_attempts,
            "max_record_attempt": max(observed_attempts) if observed_attempts else None,
            "passed": diagnostic_attempts == expected_attempts,
        })
        anchor_positions = {}
        for anchor in (round_trip.get("route_memory") or {}).get("anchors") or []:
            pose = (anchor.get("metadata") or {}).get("world_pose") or []
            if len(pose) >= 2:
                anchor_positions[int(anchor["index"])] = (float(pose[0]), float(pose[1]))
        record_lookup: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            if record.get("attempt") is not None and record.get("anchor_index") is not None:
                record_lookup[(int(record["attempt"]), int(record["anchor_index"]))].append(record)

        for source_index, row in selected:
            attempt = int(row["attempt"])
            anchor_index = int(row["anchor_index"])
            candidates = record_lookup[(attempt, anchor_index)]
            if not candidates:
                raise AssertionError(f"raw record missing for {run_key}, attempt={attempt}, anchor={anchor_index}")
            expected_distance = float(row["estimated_distance_to_anchor_m"])
            record = min(
                candidates,
                key=lambda item: abs(float(item.get("estimated_distance_to_anchor_m") or 0.0) - expected_distance),
            )
            trajectory_index = 0 if attempt == 1 else (attempt - 1) * interval - 1
            trajectory_row = return_rows[trajectory_index]
            position = trajectory_row["position"]
            anchor_x, anchor_y = anchor_positions[anchor_index]
            true_bearing, true_distance = _independent_bearing_distance(
                float(position[0]), float(position[1]), float(trajectory_row["yaw_rad"]), anchor_x, anchor_y
            )
            bearing_error = _wrapped_abs_difference_degrees(
                float(record["estimated_bearing_to_anchor_deg"]), true_bearing
            )
            distance_error = abs(float(record["estimated_distance_to_anchor_m"]) - true_distance)
            bearing_label = int(bearing_error > bearing_bad_deg)
            distance_label = int(distance_error > distance_bad_m)
            checks = {
                "step": int(row["attempt_step"]) == int(trajectory_row["step"]),
                "true_bearing": abs(float(row["true_bearing_to_anchor_deg"]) - true_bearing) <= 1e-9,
                "true_distance": abs(float(row["true_distance_to_anchor_m"]) - true_distance) <= 1e-9,
                "bearing_error": abs(float(row["bearing_error_deg"]) - bearing_error) <= 1e-9,
                "distance_error": abs(float(row["distance_error_m"]) - distance_error) <= 1e-9,
                "bearing_label": int(row["label_bearing_bad"]) == bearing_label,
                "distance_label": int(row["label_distance_bad"]) == distance_label,
                "pose_label": int(row["label_pose_bad"]) == int(bearing_label or distance_label),
            }
            audit_rows.append({
                "source_row": source_index,
                "batch": row["batch"],
                "episode_id": row["episode_id"],
                "scene_id": row["scene_id"],
                "attempt": attempt,
                "anchor_index": anchor_index,
                "anchor_role": row["anchor_role"],
                "trajectory_return_index": trajectory_index,
                "attempt_step": trajectory_row["step"],
                "robot_x": position[0],
                "robot_y": position[1],
                "robot_yaw_rad": trajectory_row["yaw_rad"],
                "anchor_x": anchor_x,
                "anchor_y": anchor_y,
                "estimated_bearing_deg": record["estimated_bearing_to_anchor_deg"],
                "recomputed_true_bearing_deg": true_bearing,
                "recomputed_bearing_error_deg": bearing_error,
                "estimated_distance_m": record["estimated_distance_to_anchor_m"],
                "recomputed_true_distance_m": true_distance,
                "recomputed_distance_error_m": distance_error,
                "stored_pose_bad": row["label_pose_bad"],
                "recomputed_pose_bad": int(bearing_label or distance_label),
                "passed": all(checks.values()),
                "failed_checks": ";".join(name for name, passed in checks.items() if not passed),
                "measurement": run["measurement"],
                "trajectory": run["trajectory"],
            })

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)
    failed_samples = [row for row in audit_rows if not row["passed"]]
    failed_schedules = [row for row in schedule_checks if not row["passed"]]
    return {
        "method": "deterministic_batch_class_stratified_raw_source_recompute",
        "seed": int(seed),
        "samples_requested": int(sample_size),
        "samples_checked": len(audit_rows),
        "sample_failures": len(failed_samples),
        "runs_touched": len(selected_by_run),
        "schedule_runs_checked": len(schedule_checks),
        "schedule_failures": len(failed_schedules),
        "failed_schedules": failed_schedules,
        "output_csv": str(output_path),
        "output_sha256": sha256_file(output_path),
        "batch_counts": dict(Counter(str(row["batch"]) for row in audit_rows)),
        "pose_label_counts": dict(Counter(str(row["stored_pose_bad"]) for row in audit_rows)),
        "unique_episodes": len({(row["batch"], row["episode_id"]) for row in audit_rows}),
        "unique_scenes": len({row["scene_id"] for row in audit_rows}),
    }


def evaluate_frozen_bundle(
    rows: list[dict[str, Any]],
    config: Mapping[str, Any],
    bundle: ReliabilityBundle,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    partition, split_audit = strict_chronological_split(rows, dict(config))
    scene_sets = {
        name: {str(row["scene_id"]) for row in values}
        for name, values in partition.items()
    }
    split_audit["scene_ids"] = {name: sorted(values) for name, values in scene_sets.items()}
    split_audit["scene_overlaps"] = {
        "train_calibration": sorted(scene_sets["train"] & scene_sets["calibration"]),
        "train_test": sorted(scene_sets["train"] & scene_sets["test"]),
        "calibration_test": sorted(scene_sets["calibration"] & scene_sets["test"]),
    }
    split_audit["scene_counts"] = {name: len(values) for name, values in scene_sets.items()}

    predictions = {}
    for split_name, split_rows in partition.items():
        results = bundle.predict_features_many(split_rows)
        predictions[split_name] = {
            "bearing": np.asarray([result.p_bearing_bad_30 for result in results]),
            "distance": np.asarray([result.p_distance_bad_0p5 for result in results]),
            "pose": np.asarray([result.p_pose_bad for result in results]),
            "status": Counter(result.status for result in results),
        }

    report: dict[str, Any] = {
        "model_version": bundle.model_version,
        "split": split_audit,
        "bootstrap": {"samples": int(bootstrap_samples), "seed": int(bootstrap_seed)},
        "heads": {},
    }
    risk_rows: list[dict[str, Any]] = []
    for head, label in HEAD_LABELS.items():
        threshold = float(bundle.trusted_thresholds[head])
        calibration_rows = partition["calibration"]
        test_rows = partition["test"]
        y_cal = np.asarray([row[label] for row in calibration_rows], dtype=np.int64)
        w_cal = np.asarray([row["sample_weight"] for row in calibration_rows], dtype=np.float64)
        y_test = np.asarray([row[label] for row in test_rows], dtype=np.int64)
        w_test = np.asarray([row["sample_weight"] for row in test_rows], dtype=np.float64)
        p_test = predictions["test"][head]

        baseline = select_simple_baseline(calibration_rows, y_cal, w_cal)
        baseline_cal = apply_simple_baseline(calibration_rows, baseline)
        baseline_test_raw = apply_simple_baseline(test_rows, baseline)
        minimum = float(np.min(baseline_cal))
        maximum = float(np.max(baseline_cal))
        scale = max(maximum - minimum, 1e-12)
        baseline_cal_raw = np.clip((baseline_cal - minimum) / scale, 0.0, 1.0)
        baseline_test_raw = np.clip((baseline_test_raw - minimum) / scale, 0.0, 1.0)
        baseline_calibrator = PlattCalibrator().fit(
            baseline_cal_raw, y_cal, w_cal
        )
        baseline_cal_probability = baseline_calibrator.predict(baseline_cal_raw)
        baseline_test_probability = baseline_calibrator.predict(baseline_test_raw)
        baseline_threshold = trusted_threshold(
            baseline_cal_probability,
            y_cal,
            w_cal,
            float(config["trusted_bad_rate_targets"][head]),
        )

        model_metrics = _weighted_metrics(y_test, p_test, w_test, threshold)
        baseline_metrics = _weighted_metrics(
            y_test, baseline_test_probability, w_test, baseline_threshold
        )
        model_curve = risk_coverage_curve(y_test, p_test, w_test)
        baseline_curve = risk_coverage_curve(y_test, baseline_test_probability, w_test)
        target_bad_rate = float(config["trusted_bad_rate_targets"][head])
        model_safe_grid_points = [
            point for point in model_curve if point["bad_rate"] <= target_bad_rate
        ]
        baseline_safe_grid_points = [
            point for point in baseline_curve if point["bad_rate"] <= target_bad_rate
        ]
        for method, curve in (("model", model_curve), ("simple_icp_baseline", baseline_curve)):
            for point in curve:
                risk_rows.append({"head": head, "method": method, **point})

        report["heads"][head] = {
            "label": label,
            "trusted_bad_rate_target": float(config["trusted_bad_rate_targets"][head]),
            "model": {
                "test": model_metrics,
                "episode_macro": grouped_macro_metrics(
                    test_rows, y_test, p_test, threshold, "episode_key"
                ),
                "scene_macro": grouped_macro_metrics(
                    test_rows, y_test, p_test, threshold, "scene_id"
                ),
                "episode_bootstrap_ci": cluster_bootstrap_intervals(
                    test_rows, y_test, p_test, w_test, threshold,
                    "episode_key", bootstrap_samples, bootstrap_seed,
                ),
                "scene_bootstrap_ci": cluster_bootstrap_intervals(
                    test_rows, y_test, p_test, w_test, threshold,
                    "scene_id", bootstrap_samples, bootstrap_seed + 1,
                ),
                "risk_coverage": model_curve,
                "diagnostic_max_grid_coverage_at_target": (
                    max(point["coverage"] for point in model_safe_grid_points)
                    if model_safe_grid_points else None
                ),
                "status_counts": dict(predictions["test"]["status"]),
            },
            "simple_icp_baseline": {
                "selection_partition": "calibration",
                "selected_signal": baseline["name"],
                "selected_field": baseline["field"],
                "direction": baseline["direction"],
                "calibration_auc": baseline["calibration_auc"],
                "calibration_missing_fraction": baseline["missing_fraction"],
                "normalization": {"calibration_min": minimum, "calibration_max": maximum},
                "calibrator": {
                    "type": "weighted_monotonic_platt",
                    "slope": baseline_calibrator.slope,
                    "intercept": baseline_calibrator.intercept,
                },
                "test": baseline_metrics,
                "episode_macro": grouped_macro_metrics(
                    test_rows, y_test, baseline_test_probability, baseline_threshold, "episode_key"
                ),
                "scene_macro": grouped_macro_metrics(
                    test_rows, y_test, baseline_test_probability, baseline_threshold, "scene_id"
                ),
                "risk_coverage": baseline_curve,
                "diagnostic_max_grid_coverage_at_target": (
                    max(point["coverage"] for point in baseline_safe_grid_points)
                    if baseline_safe_grid_points else None
                ),
                "candidate_signals": baseline["candidates"],
            },
        }
    return report, risk_rows


def write_risk_coverage_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_risk_coverage(rows: list[dict[str, Any]], path: str | Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), sharey=True)
    for axis, head in zip(axes, ("bearing", "distance", "pose")):
        for method, style in (("model", "-"), ("simple_icp_baseline", "--")):
            subset = [row for row in rows if row["head"] == head and row["method"] == method]
            axis.plot(
                [100.0 * float(row["coverage"]) for row in subset],
                [100.0 * float(row["bad_rate"]) for row in subset],
                style,
                linewidth=2,
                label=method.replace("simple_icp_", "ICP "),
            )
        axis.set_title(head)
        axis.set_xlabel("trusted coverage (%)")
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("bad rate inside trusted set (%)")
    axes[-1].legend(loc="best")
    figure.suptitle("Reliability V1 test risk–coverage (episode-balanced)")
    figure.tight_layout()
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _fmt(value: Any, digits: int = 4) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def _ci(intervals: Mapping[str, Any], name: str) -> str:
    value = intervals.get(name)
    return "n/a" if not value else f"[{value['low']:.4f}, {value['high']:.4f}]"


def audit_report_markdown(report: Mapping[str, Any]) -> str:
    label_audit = report["label_audit"]
    evaluation = report["evaluation"]
    split = evaluation["split"]
    lines = [
        "# Reliability V1 offline audit",
        "",
        "## Verdict",
        "",
        "The frozen V1 artifact retains useful ranking power, but its trusted-set error rates remain above the declared safety targets. It stays shadow-only.",
        "",
        "## Provenance and label audit",
        "",
        f"- Model: `{evaluation['model_version']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        f"- Artifact SHA-256: `{report['artifact_sha256']}`",
        f"- Raw labels rechecked: **{label_audit['samples_checked'] - label_audit['sample_failures']}/{label_audit['samples_checked']} passed** across {label_audit['unique_episodes']} episode-runs and {label_audit['unique_scenes']} scenes.",
        f"- Attempt schedules checked in all usable runs: **{label_audit['schedule_runs_checked'] - label_audit['schedule_failures']}/{label_audit['schedule_runs_checked']} passed**.",
        f"- Human-readable audit rows: `{label_audit['output_csv']}` (`{label_audit['output_sha256'][:12]}`).",
        "",
        "The raw audit reloads each measurement and trajectory, traces the runtime schedule (attempt 1 at the first return row; later attempts at interval multiples), recomputes body-frame ground truth and both error labels, and compares them with the frozen CSV.",
        "",
        "## Test composition and leakage scope",
        "",
        f"- Test rows: {split['rows']['test']}; test episodes: {len(split['episode_ids']['test'])}; test scenes: {split['scene_counts']['test']}.",
        f"- Episode overlaps: `{split['overlaps']}`.",
        f"- Scene overlaps: `{split['scene_overlaps']}`.",
        "",
        "Episode identities are disjoint, but scenes overlap across partitions. This is a same-benchmark, seen-scene evaluation—not evidence of unseen-scene generalization.",
        "",
        "## Frozen-model test metrics",
        "",
        "All pooled values use episode-balanced weights. Confidence intervals resample whole episodes, never individual readings.",
        "",
        "| Head | AUC (95% CI) | AP (95% CI) | Brier (95% CI) | Trusted coverage (95% CI) | Trusted bad rate (95% CI) | Target |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for head, values in evaluation["heads"].items():
        test = values["model"]["test"]
        ci = values["model"]["episode_bootstrap_ci"]
        lines.append(
            f"| {head} | {_fmt(test['roc_auc'])} {_ci(ci, 'roc_auc')} | "
            f"{_fmt(test['average_precision'])} {_ci(ci, 'average_precision')} | "
            f"{_fmt(test['brier'])} {_ci(ci, 'brier')} | "
            f"{_fmt(test['trusted_coverage'])} {_ci(ci, 'trusted_coverage')} | "
            f"{_fmt(test['trusted_bad_rate'])} {_ci(ci, 'trusted_bad_rate')} | "
            f"{_fmt(values['trusted_bad_rate_target'])} |"
        )
    lines.extend([
        "",
        "## Episode and scene macro view",
        "",
        "| Head | Episode-macro AUC | Episode-macro trusted bad | Scene-macro AUC | Scene-macro trusted bad |",
        "|---|---:|---:|---:|---:|",
    ])
    for head, values in evaluation["heads"].items():
        episode = values["model"]["episode_macro"]
        scene = values["model"]["scene_macro"]
        lines.append(
            f"| {head} | {_fmt(episode['roc_auc'])} ({episode['roc_auc_groups']}/{episode['groups']} valid) | "
            f"{_fmt(episode['trusted_bad_rate'])} | {_fmt(scene['roc_auc'])} "
            f"({scene['roc_auc_groups']}/{scene['groups']} valid) | {_fmt(scene['trusted_bad_rate'])} |"
        )
    lines.extend([
        "",
        "## Simple ICP baseline",
        "",
        "For each head, one scalar ICP signal is selected by calibration AUC only. Its trusted threshold is then selected on the same calibration partition using the same bad-rate target. The test batch is untouched by both choices.",
        "",
        "| Head | Calibration-selected signal | Model test AUC | Baseline test AUC | Model Brier | Baseline Brier | Model trusted bad | Baseline trusted bad |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for head, values in evaluation["heads"].items():
        model = values["model"]["test"]
        baseline = values["simple_icp_baseline"]
        base_test = baseline["test"]
        lines.append(
            f"| {head} | `{baseline['selected_signal']}` | {_fmt(model['roc_auc'])} | "
            f"{_fmt(base_test['roc_auc'])} | {_fmt(model['brier'])} | {_fmt(base_test['brier'])} | "
            f"{_fmt(model['trusted_bad_rate'])} | {_fmt(base_test['trusted_bad_rate'])} |"
        )
    lines.extend([
        "",
        "## Risk–coverage conclusion",
        "",
        "| Head | Target bad rate | Largest 5%-grid coverage meeting target | Deployed coverage | Deployed bad rate |",
        "|---|---:|---:|---:|---:|",
    ])
    for head, values in evaluation["heads"].items():
        model = values["model"]
        test = model["test"]
        lines.append(
            f"| {head} | {_fmt(values['trusted_bad_rate_target'])} | "
            f"{_fmt(model['diagnostic_max_grid_coverage_at_target'])} | "
            f"{_fmt(test['trusted_coverage'])} | {_fmt(test['trusted_bad_rate'])} |"
        )
    lines.extend([
        "",
        "The numeric curves are in `reports/risk_coverage.csv` and the plot is in `reports/risk_coverage.png`. Low predicted risk does isolate a much safer subset, but the calibration-selected deployed thresholds accept too much. The grid values above are post-hoc test diagnostics and must not be reused as deployment thresholds.",
        "",
        "## Remaining validity limits",
        "",
        f"- Only {report['usable_runs']} of {report['runs_discovered']} discovered runs were usable; missing/corrupt logs can create selection bias that bootstrap intervals do not capture.",
        f"- Calibration contains {len(split['episode_ids']['calibration'])} episodes and {split['scene_counts']['calibration']} scenes, so threshold uncertainty is substantial.",
        "- Episode-cluster intervals quantify sampling variability across available episode-runs; scene-cluster intervals are in JSON, but only eight test scenes make them coarse.",
        "- The raw audit validates the code-derived schedule and sampled labels, but old logs lack an independent relocalization timestamp. Future capture should persist the attempt step directly.",
        "- The scalar baseline is selected from a small candidate family on calibration data; it is a sanity comparator, not a production rule.",
        "",
        "## Decision",
        "",
        "Keep all enforcement switches off. Use the next unchanged 100-episode run as a prospective shadow/data-collection batch after the capture canary passes.",
        "",
    ])
    return "\n".join(lines)
