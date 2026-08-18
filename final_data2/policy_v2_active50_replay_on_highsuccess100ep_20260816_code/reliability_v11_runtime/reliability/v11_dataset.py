"""Build the numeric Reliability V1.1 basin + causal-temporal dataset."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .audit import attach_episode_metadata, load_episode_metadata, sha256_file
from .dataset import load_json
from .schema import NUMERIC_FEATURES
from .training import read_dataset


V11_SCHEMA_VERSION = "reliability-v1.1-basin-temporal.0"
WINDOWS = (4, 8, 16, 32)
BASIN_FIELDS = (
    "score",
    "seed_count",
    "overlap_ratio",
    "median_residual_m",
    "inlier_count",
    "estimated_anchor_dx_m",
    "estimated_anchor_dy_m",
    "estimated_anchor_dtheta_deg",
)
YAW_FIELDS = (
    "seed_count",
    "top_yaw_deg",
    "yaw_score_entropy",
    "yaw_score_normalized_entropy",
    "yaw_peak_width_deg",
    "yaw_top1_next_distinct_gap_deg",
    "yaw_top1_next_distinct_score_ratio",
)
SCAN_CONTEXT_FIELDS = (
    "scan_context_yaw_deg",
    "scan_context_similarity",
    "scan_context_region_size",
    "scan_context_region_ratio",
    "icp_scan_context_yaw_agreement_deg",
)
LOCALIZABILITY_FIELDS = (
    "constraint_count",
    "weak_direction_count",
    "min_normalized_eigenvalue",
    "condition_number",
    "yaw_marginal_information",
    "yaw_normalized_marginal_information",
)
PAIR_SIGNALS = (
    "confidence",
    "overlap_ratio",
    "median_residual_m",
    "icp_best_to_second_score_ratio",
    "scan_context_similarity",
)
TEMPORAL_SIGNALS = (
    "confidence",
    "overlap_ratio",
    "median_residual_m",
    "corridor_degeneracy_ratio",
    "icp_best_to_second_score_ratio",
    "icp_near_tie_basin_count",
    "estimated_distance_to_anchor_m",
    "basin_1_score",
    "yaw_score_normalized_entropy",
    "scan_context_yaw_agreement_deg",
)
MATCH_CLASS_LEVELS = (
    "ambiguous_high_confidence",
    "clean_full_pose",
    "partial_pose_degenerate",
    "__missing__",
)
ICP_AMBIGUITY_LEVELS = (
    "high_confidence_multimodal",
    "ranked_multibasin",
    "single_basin",
    "__missing__",
)


def _finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if math.isfinite(result) else float("nan")


def _wrap_degrees(value: float) -> float:
    return (float(value) + 180.0) % 360.0 - 180.0


def base_features(record: Mapping[str, Any], v1_row: Mapping[str, Any]) -> dict[str, float]:
    features = {name: _finite(v1_row.get(name)) for name in NUMERIC_FEATURES}
    for name in (
        "estimated_bearing_to_anchor_deg",
        "estimated_anchor_dx_m",
        "estimated_anchor_dy_m",
        "estimated_anchor_dtheta_deg",
        "route_remaining_to_start_m",
        "anchor_distance_from_start_m",
    ):
        features[name] = _finite(record.get(name))
    features["estimated_remaining_to_start_m"] = (
        features["route_remaining_to_start_m"] + features["estimated_distance_to_anchor_m"]
    )

    yaw_curve = record.get("yaw_curve") if isinstance(record.get("yaw_curve"), Mapping) else {}
    features["yaw_curve_available"] = float(bool(yaw_curve.get("available")))
    for name in YAW_FIELDS:
        features[name] = _finite(yaw_curve.get(name))

    scan = (
        record.get("scan_context_yaw_check")
        if isinstance(record.get("scan_context_yaw_check"), Mapping) else {}
    )
    features["scan_context_available"] = float(bool(scan.get("available")))
    for name in SCAN_CONTEXT_FIELDS:
        output_name = (
            "scan_context_yaw_agreement_deg"
            if name == "icp_scan_context_yaw_agreement_deg" else name
        )
        features[output_name] = _finite(scan.get(name))

    localizability = (
        record.get("localizability")
        if isinstance(record.get("localizability"), Mapping) else {}
    )
    features["localizability_available"] = float(bool(localizability.get("available")))
    for name in LOCALIZABILITY_FIELDS:
        features[f"localizability_{name}"] = _finite(localizability.get(name))
    eigenvalues = localizability.get("eigenvalues") or []
    normalized = localizability.get("normalized_eigenvalues") or []
    weakest = localizability.get("weakest_direction") or []
    for index in range(3):
        features[f"localizability_eigenvalue_{index}"] = _finite(
            eigenvalues[index] if index < len(eigenvalues) else None
        )
        features[f"localizability_normalized_eigenvalue_{index}"] = _finite(
            normalized[index] if index < len(normalized) else None
        )
        features[f"localizability_weakest_direction_{index}"] = _finite(
            weakest[index] if index < len(weakest) else None
        )

    basins = record.get("icp_top_basins") if isinstance(record.get("icp_top_basins"), list) else []
    for rank in range(4):
        basin = basins[rank] if rank < len(basins) and isinstance(basins[rank], Mapping) else {}
        for field in BASIN_FIELDS:
            features[f"basin_{rank + 1}_{field}"] = _finite(basin.get(field))
    features.update(_basin_summary(basins))
    features["anchor_role_current"] = float(v1_row.get("anchor_role") == "current")
    features["anchor_role_next"] = float(v1_row.get("anchor_role") == "next")
    features["anchor_role_other"] = float(v1_row.get("anchor_role") not in ("current", "next"))
    match_class = str(v1_row.get("match_class") or "__missing__")
    ambiguity = str(v1_row.get("icp_ambiguity") or "__missing__")
    for level in MATCH_CLASS_LEVELS:
        features[f"match_class__{level}"] = float(match_class == level)
    for level in ICP_AMBIGUITY_LEVELS:
        features[f"icp_ambiguity__{level}"] = float(ambiguity == level)
    return features


def _basin_summary(basins: list[Any]) -> dict[str, float]:
    valid = [basin for basin in basins[:4] if isinstance(basin, Mapping)]
    result = {
        "basin_top4_present": float(len(valid)),
        "basin_score_gap_1_2": float("nan"),
        "basin_score_ratio_1_2": float("nan"),
        "basin_translation_spread_m": float("nan"),
        "basin_yaw_spread_deg": float("nan"),
        "basin_score_std": float("nan"),
        "basin_overlap_std": float("nan"),
        "basin_residual_std": float("nan"),
        "basin_seed_count_sum": float("nan"),
    }
    if not valid:
        return result
    scores = np.asarray([_finite(item.get("score")) for item in valid])
    overlaps = np.asarray([_finite(item.get("overlap_ratio")) for item in valid])
    residuals = np.asarray([_finite(item.get("median_residual_m")) for item in valid])
    seeds = np.asarray([_finite(item.get("seed_count")) for item in valid])
    translations = np.asarray([
        [_finite(item.get("estimated_anchor_dx_m")), _finite(item.get("estimated_anchor_dy_m"))]
        for item in valid
    ])
    yaws = np.asarray([_finite(item.get("estimated_anchor_dtheta_deg")) for item in valid])
    if len(valid) >= 2 and np.isfinite(scores[:2]).all():
        result["basin_score_gap_1_2"] = float(scores[0] - scores[1])
        result["basin_score_ratio_1_2"] = float(scores[0] / max(abs(scores[1]), 1e-8))
    for name, values in (
        ("basin_score_std", scores),
        ("basin_overlap_std", overlaps),
        ("basin_residual_std", residuals),
    ):
        finite = values[np.isfinite(values)]
        result[name] = float(np.std(finite)) if finite.size else float("nan")
    finite_seeds = seeds[np.isfinite(seeds)]
    result["basin_seed_count_sum"] = float(np.sum(finite_seeds)) if finite_seeds.size else float("nan")
    valid_translation = translations[np.isfinite(translations).all(axis=1)]
    if len(valid_translation) >= 2:
        center = np.mean(valid_translation, axis=0)
        result["basin_translation_spread_m"] = float(
            np.sqrt(np.mean(np.sum((valid_translation - center) ** 2, axis=1)))
        )
    finite_yaws = yaws[np.isfinite(yaws)]
    if finite_yaws.size >= 2:
        radians = np.radians(finite_yaws)
        resultant = math.hypot(float(np.mean(np.cos(radians))), float(np.mean(np.sin(radians))))
        result["basin_yaw_spread_deg"] = float(math.degrees(math.sqrt(max(-2.0 * math.log(max(resultant, 1e-8)), 0.0))))
    return result


def add_pair_features(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["episode_key"]), int(row["attempt"]))].append(row)
    for members in grouped.values():
        for row in members:
            others = [candidate for candidate in members if candidate is not row]
            other = others[0] if len(others) == 1 else None
            features = row["features"]
            features["pair_available"] = float(other is not None)
            for signal in PAIR_SIGNALS:
                own_value = features.get(signal, float("nan"))
                other_value = other["features"].get(signal, float("nan")) if other else float("nan")
                features[f"pair_{signal}_signed_diff"] = own_value - other_value
                features[f"pair_{signal}_abs_diff"] = abs(own_value - other_value)
            if other:
                features["pair_estimated_remaining_abs_diff_m"] = abs(
                    features["estimated_remaining_to_start_m"]
                    - other["features"]["estimated_remaining_to_start_m"]
                )
                features["pair_estimated_bearing_abs_diff_deg"] = abs(_wrap_degrees(
                    features["estimated_bearing_to_anchor_deg"]
                    - other["features"]["estimated_bearing_to_anchor_deg"]
                ))
            else:
                features["pair_estimated_remaining_abs_diff_m"] = float("nan")
                features["pair_estimated_bearing_abs_diff_deg"] = float("nan")
    # These route-progress values are needed to form the simultaneous-pair
    # consistency signal above, but are deliberately excluded as standalone
    # inputs: they can act as route/episode identity proxies.
    for row in rows:
        for name in (
            "anchor_distance_from_start_m",
            "route_remaining_to_start_m",
            "estimated_remaining_to_start_m",
            "estimated_bearing_to_anchor_deg",
        ):
            row["features"].pop(name, None)


def _rolling_slope(values: np.ndarray) -> float:
    valid = np.isfinite(values)
    if valid.sum() < 2:
        return float("nan")
    x = np.arange(values.size, dtype=float)[valid]
    y = values[valid]
    x = x - x.mean()
    denominator = float(np.sum(x * x))
    return float(np.sum(x * (y - y.mean())) / denominator) if denominator > 0 else 0.0


def add_causal_temporal_features(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["episode_key"]), int(row["anchor_index"]))].append(row)
    for members in grouped.values():
        members.sort(key=lambda row: int(row["attempt"]))
        previous_role = None
        role_age = 0
        histories: dict[str, list[float]] = defaultdict(list)
        previous_attempt = None
        for row in members:
            features = row["features"]
            role = str(row["anchor_role"])
            role_changed = previous_role is not None and role != previous_role
            role_age = 1 if role_changed or previous_role is None else role_age + 1
            features["temporal_history_count_including_current"] = float(len(histories[TEMPORAL_SIGNALS[0]]) + 1)
            features["temporal_attempt_gap"] = (
                float(int(row["attempt"]) - previous_attempt) if previous_attempt is not None else float("nan")
            )
            features["temporal_role_changed"] = float(role_changed)
            features["temporal_role_age"] = float(role_age)
            for signal in TEMPORAL_SIGNALS:
                current = features.get(signal, float("nan"))
                history = histories[signal]
                features[f"temporal_{signal}_delta_1"] = (
                    current - history[-1] if history and math.isfinite(current) and math.isfinite(history[-1])
                    else float("nan")
                )
                history.append(current)
                for window in WINDOWS:
                    values = np.asarray(history[-window:], dtype=float)
                    finite = values[np.isfinite(values)]
                    prefix = f"temporal_{signal}_w{window}"
                    features[f"{prefix}_mean"] = float(np.mean(finite)) if finite.size else float("nan")
                    features[f"{prefix}_std"] = float(np.std(finite)) if finite.size else float("nan")
                    features[f"{prefix}_slope"] = _rolling_slope(values)
            previous_role = role
            previous_attempt = int(row["attempt"])


def _record_lookup(records: list[dict[str, Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    lookup: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("attempt") is not None and record.get("anchor_index") is not None:
            lookup[(int(record["attempt"]), int(record["anchor_index"]))].append(record)
    return lookup


def collect_enriched_rows(
    v1_rows: list[dict[str, Any]], manifest: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_run: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in v1_rows:
        rows_by_run[(str(row["batch"]), int(row["episode_id"]))].append(row)
    run_lookup = {
        (str(run["batch"]), int(run["episode_id"])): run
        for run in manifest.get("runs", []) if run.get("status") == "ok"
    }
    enriched = []
    duplicate_keys = 0
    for run_index, (run_key, source_rows) in enumerate(sorted(rows_by_run.items()), 1):
        run = run_lookup[run_key]
        measurement = load_json(run["measurement"])
        records = (
            (measurement.get("round_trip") or {})
            .get("route_relocalization_diagnostics", {})
            .get("covisibility_records", [])
        )
        lookup = _record_lookup(records)
        for source in source_rows:
            key = (int(source["attempt"]), int(source["anchor_index"]))
            candidates = lookup.get(key, [])
            if not candidates:
                raise AssertionError(f"missing raw record for {run_key}, key={key}")
            if len(candidates) > 1:
                duplicate_keys += 1
            expected_distance = _finite(source.get("estimated_distance_to_anchor_m"))
            record = min(
                candidates,
                key=lambda item: abs(_finite(item.get("estimated_distance_to_anchor_m")) - expected_distance),
            )
            enriched.append({
                "batch": source["batch"],
                "episode_id": int(source["episode_id"]),
                "episode_key": source["episode_key"],
                "scene_id": source["scene_id"],
                "attempt": int(source["attempt"]),
                "anchor_index": int(source["anchor_index"]),
                "anchor_role": source["anchor_role"],
                "match_class": source["match_class"],
                "icp_ambiguity": source["icp_ambiguity"],
                "label_bearing_bad": int(source["label_bearing_bad"]),
                "label_distance_bad": int(source["label_distance_bad"]),
                "label_pose_bad": int(source["label_pose_bad"]),
                "sample_weight": float(source["sample_weight"]),
                "features": base_features(record, source),
            })
        if run_index % 10 == 0:
            print(f"enriched {run_index}/{len(rows_by_run)} runs; rows={len(enriched)}", flush=True)
    if len(enriched) != len(v1_rows):
        raise AssertionError(f"row-count mismatch: enriched={len(enriched)} v1={len(v1_rows)}")
    return enriched, {"raw_duplicate_keys_resolved": duplicate_keys, "runs": len(rows_by_run)}


def write_npz_dataset(rows: list[dict[str, Any]], output_path: str | Path) -> dict[str, Any]:
    feature_names = sorted({name for row in rows for name in row["features"]})
    matrix = np.full((len(rows), len(feature_names)), np.nan, dtype=np.float32)
    feature_index = {name: index for index, name in enumerate(feature_names)}
    for row_index, row in enumerate(rows):
        for name, value in row["features"].items():
            matrix[row_index, feature_index[name]] = np.float32(value)
    labels = np.asarray([
        [row["label_bearing_bad"], row["label_distance_bad"], row["label_pose_bad"]]
        for row in rows
    ], dtype=np.int8)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        schema_version=np.asarray(V11_SCHEMA_VERSION),
        feature_names=np.asarray(feature_names),
        features=matrix,
        labels=labels,
        label_names=np.asarray(["bearing", "distance", "pose"]),
        sample_weight=np.asarray([row["sample_weight"] for row in rows], dtype=np.float32),
        batch=np.asarray([row["batch"] for row in rows]),
        episode_id=np.asarray([row["episode_id"] for row in rows], dtype=np.int32),
        episode_key=np.asarray([row["episode_key"] for row in rows]),
        scene_id=np.asarray([row["scene_id"] for row in rows]),
        attempt=np.asarray([row["attempt"] for row in rows], dtype=np.int32),
        anchor_index=np.asarray([row["anchor_index"] for row in rows], dtype=np.int16),
        anchor_role=np.asarray([row["anchor_role"] for row in rows]),
        match_class=np.asarray([row["match_class"] for row in rows]),
        icp_ambiguity=np.asarray([row["icp_ambiguity"] for row in rows]),
    )
    missing_fraction = np.mean(~np.isfinite(matrix), axis=0)
    return {
        "schema_version": V11_SCHEMA_VERSION,
        "dataset": str(output),
        "sha256": sha256_file(output),
        "size_bytes": output.stat().st_size,
        "rows": len(rows),
        "numeric_features": len(feature_names),
        "feature_names": feature_names,
        "feature_missing_fraction": {
            name: float(missing_fraction[index]) for index, name in enumerate(feature_names)
        },
        "episodes": len({str(row["episode_key"]) for row in rows}),
        "scenes": len({str(row["scene_id"]) for row in rows}),
        "rows_by_batch": dict(Counter(str(row["batch"]) for row in rows)),
        "label_positive_rates": {
            name: float(np.average(labels[:, index], weights=np.asarray([row["sample_weight"] for row in rows])))
            for index, name in enumerate(("bearing", "distance", "pose"))
        },
    }


def build_v11_dataset(
    v1_dataset_path: str | Path,
    v1_manifest_path: str | Path,
    episode_dataset_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    v1_rows = read_dataset(v1_dataset_path)
    attach_episode_metadata(v1_rows, load_episode_metadata(episode_dataset_path))
    manifest = json.loads(Path(v1_manifest_path).read_text(encoding="utf-8"))
    rows, collection = collect_enriched_rows(v1_rows, manifest)
    add_pair_features(rows)
    add_causal_temporal_features(rows)
    output_manifest = write_npz_dataset(rows, output_path)
    output_manifest["collection"] = collection
    output_manifest["source_v1_dataset"] = str(v1_dataset_path)
    output_manifest["source_v1_sha256"] = sha256_file(v1_dataset_path)
    return output_manifest
