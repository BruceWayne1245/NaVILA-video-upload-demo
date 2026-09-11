"""Ground-truth join and leakage-safe dataset construction."""

from __future__ import annotations

import csv
import glob
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .schema import CATEGORICAL_FEATURES, LABEL_COLUMNS, NUMERIC_FEATURES, SCHEMA_VERSION, features_from_record


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_trajectory(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda row: int(row["step"]))
    return rows


def wrap_degrees(value: float) -> float:
    return (float(value) + 180.0) % 360.0 - 180.0


def body_frame_bearing_distance(
    robot_x: float,
    robot_y: float,
    robot_yaw: float,
    target_x: float,
    target_y: float,
) -> tuple[float, float]:
    dx_world = target_x - robot_x
    dy_world = target_y - robot_y
    cosine, sine = math.cos(robot_yaw), math.sin(robot_yaw)
    dx_body = dx_world * cosine + dy_world * sine
    dy_body = -dx_world * sine + dy_world * cosine
    return math.degrees(math.atan2(dy_body, dx_body)), math.hypot(dx_body, dy_body)


def _last_measurement(run_dir: str) -> str | None:
    candidates = glob.glob(os.path.join(run_dir, "measurements", "*.json"))
    numbered = []
    for path in candidates:
        match = re.search(r"(\d+)\.json$", path)
        if match:
            numbered.append((int(match.group(1)), path))
    return max(numbered)[1] if numbered else None


def discover_runs(evaluation_root: str, batches: Iterable[str]) -> list[tuple[str, int, str]]:
    runs = []
    for batch in batches:
        for run_dir in sorted(glob.glob(os.path.join(evaluation_root, f"*{batch}*_ep*"))):
            match = re.search(r"_ep(\d+)$", run_dir)
            if match:
                runs.append((batch, int(match.group(1)), run_dir))
    return runs


def _trajectory_path(run_dir: str, measurement_path: str, round_trip: dict[str, Any]) -> str | None:
    recorded = round_trip.get("trajectory_file")
    if recorded and os.path.exists(str(recorded)):
        return str(recorded)
    step_match = re.search(r"(\d+)\.json$", measurement_path)
    if not step_match:
        return None
    candidate = os.path.join(run_dir, "trajectories", f"output_{step_match.group(1)}.jsonl")
    return candidate if os.path.exists(candidate) else None


def _attempt_trajectory_row(
    return_rows: list[dict[str, Any]], attempt: int, interval: int
) -> dict[str, Any] | None:
    """Map a 1-indexed attempt using the code-verified update-loop schedule."""
    if not return_rows or attempt < 1 or interval < 1:
        return None
    index = 0 if attempt == 1 else (attempt - 1) * interval - 1
    return return_rows[index] if 0 <= index < len(return_rows) else None


def _anchor_world_positions(round_trip: dict[str, Any]) -> dict[int, tuple[float, float]]:
    anchors = (round_trip.get("route_memory") or {}).get("anchors") or []
    result = {}
    for anchor in anchors:
        pose = (anchor.get("metadata") or {}).get("world_pose")
        if isinstance(pose, list) and len(pose) >= 2:
            result[int(anchor["index"])] = (float(pose[0]), float(pose[1]))
    return result


def _role_by_attempt(records: list[dict[str, Any]]) -> dict[tuple[int, int], str]:
    by_attempt: dict[int, set[int]] = defaultdict(set)
    for record in records:
        if record.get("attempt") is not None and record.get("anchor_index") is not None:
            by_attempt[int(record["attempt"])].add(int(record["anchor_index"]))
    result = {}
    for attempt, indices in by_attempt.items():
        ordered = sorted(indices, reverse=True)
        for position, anchor_index in enumerate(ordered):
            result[(attempt, anchor_index)] = "current" if position == 0 else "next" if position == 1 else "other"
    return result


def extract_run(
    batch: str,
    episode_id: int,
    run_dir: str,
    bearing_bad_deg: float,
    distance_bad_m: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    measurement_path = _last_measurement(run_dir)
    if measurement_path is None:
        return [], {"status": "missing_measurement"}
    try:
        measurement = load_json(measurement_path)
    except Exception as exc:
        return [], {"status": "corrupt_measurement", "error": str(exc)}
    round_trip = measurement.get("round_trip") or {}
    records = (round_trip.get("route_relocalization_diagnostics") or {}).get("covisibility_records") or []
    trajectory_path = _trajectory_path(run_dir, measurement_path, round_trip)
    if not records or trajectory_path is None:
        return [], {"status": "missing_records_or_trajectory"}
    try:
        trajectory = load_trajectory(trajectory_path)
    except Exception as exc:
        return [], {"status": "corrupt_trajectory", "error": str(exc)}

    route_memory = round_trip.get("route_memory") or {}
    interval = route_memory.get("relocalization_interval_updates")
    if not isinstance(interval, int) or interval < 1:
        return [], {"status": "missing_relocalization_interval"}
    anchor_positions = _anchor_world_positions(round_trip)
    if not anchor_positions:
        return [], {"status": "missing_anchor_world_pose"}
    return_rows = [row for row in trajectory if row.get("phase") == "return"]
    roles = _role_by_attempt(records)
    rows = []
    for record in records:
        required = ("attempt", "anchor_index", "estimated_bearing_to_anchor_deg", "estimated_distance_to_anchor_m")
        if any(record.get(name) is None for name in required):
            continue
        attempt = int(record["attempt"])
        anchor_index = int(record["anchor_index"])
        if anchor_index not in anchor_positions:
            continue
        trajectory_row = _attempt_trajectory_row(return_rows, attempt, interval)
        if trajectory_row is None:
            continue
        position = trajectory_row.get("position") or []
        if len(position) < 2 or trajectory_row.get("yaw_rad") is None:
            continue
        target_x, target_y = anchor_positions[anchor_index]
        true_bearing, true_distance = body_frame_bearing_distance(
            float(position[0]), float(position[1]), float(trajectory_row["yaw_rad"]), target_x, target_y
        )
        bearing_error = abs(wrap_degrees(float(record["estimated_bearing_to_anchor_deg"]) - true_bearing))
        distance_error = abs(float(record["estimated_distance_to_anchor_m"]) - true_distance)
        label_bearing = int(bearing_error > bearing_bad_deg)
        label_distance = int(distance_error > distance_bad_m)
        anchor_route_distance = float(record.get("anchor_distance_from_start_m") or 0.0)
        features = features_from_record(record)
        row = {
            "schema_version": SCHEMA_VERSION,
            "batch": batch,
            "episode_id": episode_id,
            "episode_key": f"{batch}::ep{episode_id}",
            "attempt": attempt,
            "attempt_step": int(trajectory_row["step"]),
            "relocalization_interval_updates": interval,
            "anchor_index": anchor_index,
            "anchor_role": roles.get((attempt, anchor_index), "unknown"),
            "outcome": str(record.get("outcome") or ""),
            "true_bearing_to_anchor_deg": true_bearing,
            "true_distance_to_anchor_m": true_distance,
            "bearing_error_deg": bearing_error,
            "distance_error_m": distance_error,
            "robot_distance_to_start_m": trajectory_row.get("distance_to_start_m"),
            "estimated_distance_to_start_m": anchor_route_distance + float(record["estimated_distance_to_anchor_m"]),
            "label_bearing_bad": label_bearing,
            "label_distance_bad": label_distance,
            "label_pose_bad": int(label_bearing or label_distance),
            "outbound_success": int(bool(round_trip.get("outbound_success"))),
            "return_success": int(bool(round_trip.get("return_success"))),
            **features,
        }
        rows.append(row)
    return rows, {
        "status": "ok" if rows else "no_usable_rows",
        "rows": len(rows),
        "interval": interval,
        "measurement": measurement_path,
        "trajectory": trajectory_path,
    }


def _add_episode_balanced_weights(rows: list[dict[str, Any]]) -> None:
    counts = Counter(str(row["episode_key"]) for row in rows)
    if not counts:
        return
    scale = len(rows) / len(counts)
    for row in rows:
        row["sample_weight"] = scale / counts[str(row["episode_key"])]


def build_dataset(config: dict[str, Any], output_csv: str | Path) -> dict[str, Any]:
    labels = config["labels"]
    runs = discover_runs(config["evaluation_root"], config["batches"])
    rows: list[dict[str, Any]] = []
    run_manifest = []
    for index, (batch, episode_id, run_dir) in enumerate(runs, 1):
        extracted, status = extract_run(
            batch,
            episode_id,
            run_dir,
            float(labels["bearing_bad_deg"]),
            float(labels["distance_bad_m"]),
        )
        rows.extend(extracted)
        run_manifest.append({"batch": batch, "episode_id": episode_id, "run_dir": run_dir, **status})
        if index % 20 == 0:
            print(f"processed {index}/{len(runs)} runs; rows={len(rows)}", flush=True)
    _add_episode_balanced_weights(rows)
    columns = [
        "schema_version", "batch", "episode_id", "episode_key", "attempt", "attempt_step",
        "relocalization_interval_updates", "anchor_index", "anchor_role", "outcome",
        "true_bearing_to_anchor_deg", "true_distance_to_anchor_m", "bearing_error_deg",
        "distance_error_m", "robot_distance_to_start_m", "estimated_distance_to_start_m",
        *LABEL_COLUMNS, "outbound_success", "return_success", "sample_weight",
        *NUMERIC_FEATURES, *CATEGORICAL_FEATURES,
    ]
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(output_csv.read_bytes()).hexdigest()
    by_batch = Counter(str(row["batch"]) for row in rows)
    episodes_by_batch = defaultdict(set)
    for row in rows:
        episodes_by_batch[str(row["batch"])].add(int(row["episode_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": str(output_csv),
        "sha256": digest,
        "rows": len(rows),
        "runs_discovered": len(runs),
        "rows_by_batch": dict(by_batch),
        "episodes_by_batch": {key: sorted(value) for key, value in episodes_by_batch.items()},
        "run_status_counts": dict(Counter(item["status"] for item in run_manifest)),
        "runs": run_manifest,
    }
