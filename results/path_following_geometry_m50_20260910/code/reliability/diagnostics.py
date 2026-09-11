"""Calibration and domain-shift diagnostics for the frozen V1 artifact."""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from .audit import _weighted_metrics
from .bundle import ReliabilityBundle
from .calibration import trusted_threshold
from .schema import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from .training import HEAD_LABELS, strict_chronological_split


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantiles: Iterable[float]) -> np.ndarray:
    quantiles = list(quantiles)
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not valid.any():
        return np.full(len(quantiles), np.nan)
    order = np.argsort(values[valid], kind="stable")
    sorted_values = values[valid][order]
    sorted_weights = weights[valid][order]
    cumulative = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / sorted_weights.sum()
    return np.interp(np.asarray(quantiles, dtype=float), cumulative, sorted_values)


def calibration_curve_equal_mass(
    target: np.ndarray,
    probability: np.ndarray,
    weight: np.ndarray,
    bins: int = 10,
) -> list[dict[str, float]]:
    edges = _weighted_quantile(probability, weight, np.linspace(0.0, 1.0, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    result = []
    for index in range(bins):
        if index == bins - 1:
            selected = (probability >= edges[index]) & (probability <= edges[index + 1])
        else:
            selected = (probability >= edges[index]) & (probability < edges[index + 1])
        if not selected.any() or float(weight[selected].sum()) <= 0:
            continue
        result.append({
            "bin": index,
            "rows": int(selected.sum()),
            "weight": float(weight[selected].sum()),
            "mean_probability": float(np.average(probability[selected], weights=weight[selected])),
            "observed_bad_rate": float(np.average(target[selected], weights=weight[selected])),
        })
    return result


def expected_calibration_error(curve: list[dict[str, float]]) -> float | None:
    total = sum(point["weight"] for point in curve)
    if total <= 0:
        return None
    return float(sum(
        point["weight"] * abs(point["mean_probability"] - point["observed_bad_rate"])
        for point in curve
    ) / total)


def add_attempt_phase(rows: list[dict[str, Any]]) -> None:
    maximum = defaultdict(int)
    for row in rows:
        maximum[str(row["episode_key"])] = max(maximum[str(row["episode_key"])], int(row["attempt"]))
    for row in rows:
        fraction = int(row["attempt"]) / max(maximum[str(row["episode_key"])], 1)
        if fraction <= 0.25:
            phase = "q1_early"
        elif fraction <= 0.50:
            phase = "q2_mid_early"
        elif fraction <= 0.75:
            phase = "q3_mid_late"
        else:
            phase = "q4_late"
        row["attempt_fraction"] = fraction
        row["attempt_phase"] = phase


def predict_partitions(
    partition: Mapping[str, list[dict[str, Any]]], bundle: ReliabilityBundle
) -> dict[str, dict[str, Any]]:
    result = {}
    for split_name, rows in partition.items():
        predictions = bundle.predict_features_many(rows)
        result[split_name] = {
            "bearing": np.asarray([prediction.p_bearing_bad_30 for prediction in predictions]),
            "distance": np.asarray([prediction.p_distance_bad_0p5 for prediction in predictions]),
            "pose": np.asarray([prediction.p_pose_bad for prediction in predictions]),
            "status": Counter(prediction.status for prediction in predictions),
        }
    return result


def partition_calibration_report(
    partition: Mapping[str, list[dict[str, Any]]],
    predictions: Mapping[str, Mapping[str, Any]],
    bundle: ReliabilityBundle,
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for split_name, rows in partition.items():
        weight = np.asarray([row["sample_weight"] for row in rows], dtype=float)
        split_report = {"rows": len(rows), "status_counts": dict(predictions[split_name]["status"]), "heads": {}}
        for head, label in HEAD_LABELS.items():
            target = np.asarray([row[label] for row in rows], dtype=int)
            probability = np.asarray(predictions[split_name][head], dtype=float)
            curve = calibration_curve_equal_mass(target, probability, weight)
            metrics = _weighted_metrics(
                target, probability, weight, float(bundle.trusted_thresholds[head])
            )
            metrics.update({
                "mean_probability": float(np.average(probability, weights=weight)),
                "calibration_bias": float(np.average(probability - target, weights=weight)),
                "ece_equal_mass_10": expected_calibration_error(curve),
                "calibration_curve": curve,
            })
            split_report["heads"][head] = metrics
        report[split_name] = split_report
    return report


def subgroup_report(
    rows: list[dict[str, Any]],
    probability_by_head: Mapping[str, np.ndarray],
    bundle: ReliabilityBundle,
    group_column: str,
) -> dict[str, Any]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[str(row.get(group_column, "__missing__"))].append(index)
    output = {}
    for group, indices in sorted(grouped.items()):
        selected = np.asarray(indices, dtype=int)
        weights = np.asarray([rows[index]["sample_weight"] for index in indices], dtype=float)
        group_report = {
            "rows": len(indices),
            "episodes": len({str(rows[index]["episode_key"]) for index in indices}),
            "heads": {},
        }
        for head, label in HEAD_LABELS.items():
            target = np.asarray([rows[index][label] for index in indices], dtype=int)
            probability = np.asarray(probability_by_head[head])[selected]
            curve = calibration_curve_equal_mass(target, probability, weights, bins=5)
            metrics = _weighted_metrics(
                target, probability, weights, float(bundle.trusted_thresholds[head])
            )
            metrics["mean_probability"] = float(np.average(probability, weights=weights))
            metrics["ece_equal_mass_5"] = expected_calibration_error(curve)
            group_report["heads"][head] = metrics
        output[group] = group_report
    return {"group_column": group_column, "groups": output}


def _weighted_frequencies(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    counts = defaultdict(float)
    for row in rows:
        counts[str(row.get(field) or "__missing__")] += float(row["sample_weight"])
    total = sum(counts.values())
    return {key: value / total for key, value in counts.items()}


def _population_stability_index(
    reference: np.ndarray,
    comparison: np.ndarray,
    reference_weight: np.ndarray,
    comparison_weight: np.ndarray,
) -> float | None:
    reference_valid = np.isfinite(reference)
    comparison_valid = np.isfinite(comparison)
    if reference_valid.sum() < 2 or comparison_valid.sum() < 2:
        return None
    edges = np.unique(_weighted_quantile(
        reference[reference_valid], reference_weight[reference_valid], np.linspace(0.0, 1.0, 11)
    ))
    if edges.size < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    reference_bins = np.digitize(reference, edges[1:-1], right=False)
    comparison_bins = np.digitize(comparison, edges[1:-1], right=False)
    ref_parts, cmp_parts = [], []
    for index in range(edges.size - 1):
        ref_parts.append(float(reference_weight[(reference_bins == index) & reference_valid].sum()))
        cmp_parts.append(float(comparison_weight[(comparison_bins == index) & comparison_valid].sum()))
    # Treat missingness as an explicit extra bin.
    ref_parts.append(float(reference_weight[~reference_valid].sum()))
    cmp_parts.append(float(comparison_weight[~comparison_valid].sum()))
    ref = np.asarray(ref_parts) / max(sum(ref_parts), 1e-12)
    cmp = np.asarray(cmp_parts) / max(sum(cmp_parts), 1e-12)
    ref, cmp = np.clip(ref, 1e-6, None), np.clip(cmp, 1e-6, None)
    return float(np.sum((cmp - ref) * np.log(cmp / ref)))


def feature_drift_report(
    reference_rows: list[dict[str, Any]], comparison_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    from scipy.spatial.distance import jensenshannon
    from scipy.stats import wasserstein_distance

    reference_weight = np.asarray([row["sample_weight"] for row in reference_rows], dtype=float)
    comparison_weight = np.asarray([row["sample_weight"] for row in comparison_rows], dtype=float)
    numeric = {}
    for field in NUMERIC_FEATURES:
        reference = np.asarray([
            float(row[field]) if row.get(field) is not None else np.nan for row in reference_rows
        ])
        comparison = np.asarray([
            float(row[field]) if row.get(field) is not None else np.nan for row in comparison_rows
        ])
        ref_valid, cmp_valid = np.isfinite(reference), np.isfinite(comparison)
        wasserstein = None
        if ref_valid.any() and cmp_valid.any():
            wasserstein = float(wasserstein_distance(
                reference[ref_valid], comparison[cmp_valid],
                u_weights=reference_weight[ref_valid], v_weights=comparison_weight[cmp_valid],
            ))
        numeric[field] = {
            "reference_missing_fraction": float(np.average(~ref_valid, weights=reference_weight)),
            "comparison_missing_fraction": float(np.average(~cmp_valid, weights=comparison_weight)),
            "reference_mean": float(np.average(reference[ref_valid], weights=reference_weight[ref_valid])) if ref_valid.any() else None,
            "comparison_mean": float(np.average(comparison[cmp_valid], weights=comparison_weight[cmp_valid])) if cmp_valid.any() else None,
            "weighted_wasserstein": wasserstein,
            "psi": _population_stability_index(
                reference, comparison, reference_weight, comparison_weight
            ),
        }
    categorical = {}
    for field in CATEGORICAL_FEATURES:
        reference = _weighted_frequencies(reference_rows, field)
        comparison = _weighted_frequencies(comparison_rows, field)
        levels = sorted(set(reference) | set(comparison))
        ref = np.asarray([reference.get(level, 0.0) for level in levels])
        cmp = np.asarray([comparison.get(level, 0.0) for level in levels])
        categorical[field] = {
            "jensen_shannon_distance": float(jensenshannon(ref, cmp, base=2.0)),
            "reference_frequencies": reference,
            "comparison_frequencies": comparison,
        }
    top_psi = sorted(
        (
            {"feature": field, **values}
            for field, values in numeric.items()
            if values["psi"] is not None
        ),
        key=lambda item: item["psi"],
        reverse=True,
    )
    return {"numeric": numeric, "categorical": categorical, "top_numeric_by_psi": top_psi}


def calibration_threshold_sensitivity(
    calibration_rows: list[dict[str, Any]],
    calibration_probability: Mapping[str, np.ndarray],
    test_rows: list[dict[str, Any]],
    test_probability: Mapping[str, np.ndarray],
    targets: Mapping[str, float],
) -> dict[str, Any]:
    episode_keys = sorted({str(row["episode_key"]) for row in calibration_rows})
    output = {}
    for head, label in HEAD_LABELS.items():
        variants = []
        masks: list[tuple[str, np.ndarray]] = []
        for episode_key in episode_keys:
            masks.append((f"single::{episode_key}", np.asarray([
                str(row["episode_key"]) == episode_key for row in calibration_rows
            ])))
            masks.append((f"leave_one_out::{episode_key}", np.asarray([
                str(row["episode_key"]) != episode_key for row in calibration_rows
            ])))
        masks.append(("all_calibration", np.ones(len(calibration_rows), dtype=bool)))
        test_target = np.asarray([row[label] for row in test_rows], dtype=int)
        test_weight = np.asarray([row["sample_weight"] for row in test_rows], dtype=float)
        for name, mask in masks:
            cal_target = np.asarray([row[label] for row in calibration_rows], dtype=int)[mask]
            cal_weight = np.asarray([row["sample_weight"] for row in calibration_rows], dtype=float)[mask]
            threshold = trusted_threshold(
                np.asarray(calibration_probability[head])[mask], cal_target, cal_weight, float(targets[head])
            )
            test_metrics = _weighted_metrics(
                test_target, np.asarray(test_probability[head]), test_weight, threshold
            )
            variants.append({
                "calibration_subset": name,
                "calibration_episodes": int(len({
                    str(row["episode_key"]) for index, row in enumerate(calibration_rows) if mask[index]
                })),
                "threshold": float(threshold),
                "test_trusted_coverage": test_metrics["trusted_coverage"],
                "test_trusted_bad_rate": test_metrics["trusted_bad_rate"],
            })
        output[head] = variants
    return output


def build_shift_diagnostic(
    rows: list[dict[str, Any]], config: Mapping[str, Any], bundle: ReliabilityBundle
) -> dict[str, Any]:
    add_attempt_phase(rows)
    partition, split_audit = strict_chronological_split(rows, dict(config))
    predictions = predict_partitions(partition, bundle)
    return {
        "model_version": bundle.model_version,
        "split": split_audit,
        "calibration": partition_calibration_report(partition, predictions, bundle),
        "test_subgroups": {
            column: subgroup_report(
                partition["test"], predictions["test"], bundle, column
            )
            for column in ("scene_id", "anchor_role", "attempt_phase")
        },
        "feature_drift": {
            "train_to_calibration": feature_drift_report(partition["train"], partition["calibration"]),
            "train_to_test": feature_drift_report(partition["train"], partition["test"]),
            "calibration_to_test": feature_drift_report(partition["calibration"], partition["test"]),
        },
        "threshold_sensitivity": calibration_threshold_sensitivity(
            partition["calibration"], predictions["calibration"],
            partition["test"], predictions["test"], config["trusted_bad_rate_targets"],
        ),
    }


def write_subgroup_csv(report: Mapping[str, Any], path: str | Path) -> None:
    rows = []
    for dimension, dimension_report in report["test_subgroups"].items():
        for group, group_report in dimension_report["groups"].items():
            for head, metrics in group_report["heads"].items():
                rows.append({
                    "dimension": dimension,
                    "group": group,
                    "head": head,
                    "rows": group_report["rows"],
                    "episodes": group_report["episodes"],
                    **{key: metrics.get(key) for key in (
                        "positive_rate", "mean_probability", "calibration_bias",
                        "ece_equal_mass_5", "roc_auc", "average_precision", "brier",
                        "trusted_coverage", "trusted_bad_rate",
                    )},
                })
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_calibration(report: Mapping[str, Any], path: str | Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))
    for axis, head in zip(axes, ("bearing", "distance", "pose")):
        axis.plot([0, 1], [0, 1], color="black", linestyle=":", label="perfect")
        for split_name, marker in (("calibration", "o"), ("test", "s")):
            curve = report["calibration"][split_name]["heads"][head]["calibration_curve"]
            axis.plot(
                [point["mean_probability"] for point in curve],
                [point["observed_bad_rate"] for point in curve],
                marker=marker,
                linewidth=1.8,
                label=split_name,
            )
        axis.set_title(head)
        axis.set_xlabel("mean predicted bad probability")
        axis.set_ylabel("observed bad rate")
        axis.grid(alpha=0.25)
        axis.legend()
    figure.suptitle("Frozen V1 calibration shift (episode-balanced equal-mass bins)")
    figure.tight_layout()
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def diagnostic_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Reliability V1 calibration and domain-shift diagnosis",
        "",
        "## Main finding",
        "",
        "V1's primary failure is threshold transfer: ranking remains useful on the latest batch, while the three-episode calibration partition systematically understates the risk of the accepted test subset. Feature and role/scene drift are secondary contributors.",
        "",
        "## Partition calibration",
        "",
        "| Split | Head | Observed bad | Mean predicted | Bias (predicted − observed) | ECE | Brier | Trusted coverage | Trusted bad |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split_name in ("train", "calibration", "test"):
        for head, metrics in report["calibration"][split_name]["heads"].items():
            lines.append(
                f"| {split_name} | {head} | {_fmt(metrics['positive_rate'])} | "
                f"{_fmt(metrics['mean_probability'])} | {_fmt(metrics['calibration_bias'])} | "
                f"{_fmt(metrics['ece_equal_mass_10'])} | {_fmt(metrics['brier'])} | "
                f"{_fmt(metrics['trusted_coverage'])} | {_fmt(metrics['trusted_bad_rate'])} |"
            )
    lines.extend([
        "",
        "## Test role breakdown",
        "",
        "| Role | Head | Rows | AUC | Trusted coverage | Trusted bad | ECE |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    role_groups = report["test_subgroups"]["anchor_role"]["groups"]
    for role, role_report in role_groups.items():
        for head, metrics in role_report["heads"].items():
            lines.append(
                f"| {role} | {head} | {role_report['rows']} | {_fmt(metrics['roc_auc'])} | "
                f"{_fmt(metrics['trusted_coverage'])} | {_fmt(metrics['trusted_bad_rate'])} | "
                f"{_fmt(metrics['ece_equal_mass_5'])} |"
            )
    lines.extend([
        "",
        "## Threshold instability",
        "",
        "The table below gives the range produced when thresholds are estimated from each single calibration episode or each two-episode leave-one-out subset, then replayed on the already-seen historical test batch.",
        "",
        "| Head | Threshold range | Test coverage range | Test trusted-bad range |",
        "|---|---:|---:|---:|",
    ])
    for head, variants in report["threshold_sensitivity"].items():
        sensitivity = [item for item in variants if item["calibration_subset"] != "all_calibration"]
        lines.append(
            f"| {head} | {min(item['threshold'] for item in sensitivity):.4f}–{max(item['threshold'] for item in sensitivity):.4f} | "
            f"{min(item['test_trusted_coverage'] for item in sensitivity):.4f}–{max(item['test_trusted_coverage'] for item in sensitivity):.4f} | "
            f"{min(item['test_trusted_bad_rate'] for item in sensitivity if item['test_trusted_bad_rate'] is not None):.4f}–"
            f"{max(item['test_trusted_bad_rate'] for item in sensitivity if item['test_trusted_bad_rate'] is not None):.4f} |"
        )
    lines.extend([
        "",
        "## Largest calibration-to-test feature shifts",
        "",
        "| Rank | Feature | PSI | Calibration missing | Test missing |",
        "|---:|---|---:|---:|---:|",
    ])
    drift = report["feature_drift"]["calibration_to_test"]["top_numeric_by_psi"][:10]
    for rank, item in enumerate(drift, 1):
        lines.append(
            f"| {rank} | `{item['feature']}` | {_fmt(item['psi'])} | "
            f"{_fmt(item['reference_missing_fraction'])} | {_fmt(item['comparison_missing_fraction'])} |"
        )
    lines.extend([
        "",
        "## Implications for V1.1",
        "",
        "1. Treat all three historical batches as development data; the old latest batch is no longer an untouched test set.",
        "2. Produce out-of-fold probabilities with episode-grouped, scene-aware folds before fitting any calibrator or threshold.",
        "3. Add full basin and causal temporal features, with current/next candidates from one attempt kept in the same fold.",
        "4. Select thresholds using cluster-aware upper risk bounds and minimum coverage, not a three-episode empirical prefix.",
        "5. Freeze V1.1 before opening results from the next prospective batch.",
        "",
    ])
    return "\n".join(lines)
