#!/usr/bin/env python3
"""Build scene-disjoint anchor-state and terminal-decision datasets."""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "navila-anchor-terminal-training-v1"
DEFAULT_SOURCE = Path(
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
)
DEFAULT_EPISODE_DATASET = Path(
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/"
    "isaaclab_exts/omni.isaac.vlnce/assets/vln_ce_isaac_v1.json.gz"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "v1"
LOOKAHEAD_M = 1.0
STOP_R_IN_M = 3.0
RAW_MARGIN_M = 0.35
ARRIVED_MAX_M = STOP_R_IN_M - RAW_MARGIN_M
FAR_MIN_M = STOP_R_IN_M + RAW_MARGIN_M


RAW_CANDIDATE_FIELDS = (
    "anchor_index",
    "anchor_distance_from_start_m",
    "route_remaining_to_start_m",
    "outcome",
    "confidence",
    "inlier_count",
    "overlap_ratio",
    "median_residual_m",
    "mean_residual_m",
    "estimated_anchor_dx_m",
    "estimated_anchor_dy_m",
    "estimated_anchor_dtheta_deg",
    "estimated_distance_to_anchor_m",
    "estimated_bearing_to_anchor_deg",
    "corridor_degeneracy_ratio",
    "icp_basin_count",
    "icp_near_tie_basin_count",
    "icp_ambiguity",
    "icp_best_to_second_score_ratio",
    "icp_best_to_second_translation_delta_m",
    "icp_best_to_second_rotation_delta_deg",
    "match_class",
)

ROUTE_MEMORY_INPUT_FIELDS = (
    "source",
    "configured_source",
    "target_dx_m",
    "target_dy_m",
    "distance_to_start_m",
    "bearing_to_start_deg",
    "target_anchor_index",
    "anchor_dx_m",
    "anchor_dy_m",
    "distance_to_anchor_m",
    "bearing_to_anchor_deg",
    "anchor_route_remaining_m",
    "anchor_heading_reliable",
    "relocalization_confidence",
    "relocalization_backend",
    "filter_std_m",
    "estimate_kind",
    "estimate_source_anchor_index",
    "estimate_edge_hop_count",
    "estimate_source_confidence",
    "estimate_target_raw_confidence",
    "evidence_age_updates",
    "estimate_role",
)


class SkipEpisode(RuntimeError):
    pass


@dataclass
class EpisodeSource:
    directory: Path
    episode_key: str
    physical_episode_id: int
    scene_id: str
    trajectory_path: Path
    measurement_path: Path
    anchors_path: Path
    trajectory_sha256: str
    measurement_sha256: str | None
    anchors_sha256: str
    split: str = ""


def json_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def append_jsonl(handle, value: dict[str, Any]) -> None:
    handle.write(compact_json(value))
    handle.write("\n")


def parse_episode_id(directory: Path) -> int:
    match = re.search(r"_ep(\d+)(?:$|\.)", directory.name)
    if not match:
        raise SkipEpisode("physical_episode_id_unavailable")
    return int(match.group(1))


def first_jsonl_object(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    value = json.loads(line)
                    return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
    return None


def load_scene_lookup(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    opener = gzip.open if path.suffix == ".gz" else path.open
    with opener(path, "rt", encoding="utf-8") as handle:
        episodes = (json.load(handle) or {}).get("episodes") or []
    result = {}
    for physical_index, episode in enumerate(episodes):
        scene = str(episode.get("scene_id") or "")
        if scene:
            result[physical_index] = Path(scene).stem
    return result


def resolve_scene_and_completion(
    directory: Path,
    scene_lookup: dict[int, str],
) -> tuple[str, int, dict[str, Any]]:
    completion_path = directory / "capture_completion.json"
    completion: dict[str, Any] = {}
    if completion_path.exists():
        completion = json_load(completion_path)
        if completion.get("complete") is not True:
            raise SkipEpisode("capture_incomplete")
    scene = completion.get("scene_id")
    physical = completion.get("physical_episode_id")
    shadow_start = first_jsonl_object(directory / "reliability_v11_shadow.jsonl")
    if not scene and shadow_start:
        scene = shadow_start.get("scene_id")
    if physical is None and shadow_start:
        physical = shadow_start.get("physical_episode_id")
    if physical is None:
        physical = parse_episode_id(directory)
    if not scene:
        scene = scene_lookup.get(int(physical))
    if not scene:
        raise SkipEpisode("scene_id_unavailable")
    return str(scene), int(physical), completion


def select_measurement(directory: Path) -> tuple[Path, dict[str, Any]]:
    candidates = sorted((directory / "measurements").glob("*.json"))
    if not candidates:
        raise SkipEpisode("measurement_missing")
    errors = []
    for path in candidates:
        try:
            value = json_load(path)
            rt = value.get("round_trip") or {}
            if rt.get("completed_phase") == "return":
                return path, value
            errors.append(f"{path.name}:not_completed_return")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            errors.append(f"{path.name}:{type(exc).__name__}")
    raise SkipEpisode("measurement_unusable:" + ",".join(errors[:3]))


def resolve_trajectory(
    directory: Path,
    round_trip: dict[str, Any],
    completion: dict[str, Any],
) -> Path:
    rel = round_trip.get("trajectory_file")
    if not rel:
        rel = (completion.get("trajectory") or {}).get("path")
    if rel:
        candidate = directory / str(rel)
        if candidate.exists():
            return candidate
    candidates = sorted((directory / "trajectories").glob("*.jsonl"))
    if not candidates:
        raise SkipEpisode("trajectory_missing")
    return candidates[0]


def discover_episode(
    directory: Path,
    scene_lookup: dict[int, str],
) -> tuple[EpisodeSource, dict[str, Any]]:
    anchors_path = directory / "icp_replay_dataset" / "anchors.json"
    if not anchors_path.exists():
        raise SkipEpisode("anchors_missing")
    scene, physical, completion = resolve_scene_and_completion(
        directory, scene_lookup
    )
    measurement_path, measurement = select_measurement(directory)
    round_trip = measurement.get("round_trip") or {}
    trajectory_path = resolve_trajectory(directory, round_trip, completion)
    trajectory_sha = (
        (completion.get("trajectory") or {}).get("sha256")
        or sha256_file(trajectory_path)
    )
    measurement_sha = (completion.get("measurement") or {}).get("sha256")
    return (
        EpisodeSource(
            directory=directory,
            episode_key=directory.name,
            physical_episode_id=physical,
            scene_id=scene,
            trajectory_path=trajectory_path,
            measurement_path=measurement_path,
            anchors_path=anchors_path,
            trajectory_sha256=str(trajectory_sha),
            measurement_sha256=(
                str(measurement_sha)
                if measurement_sha is not None
                else sha256_file(measurement_path)
            ),
            anchors_sha256=sha256_file(anchors_path),
        ),
        measurement,
    )


def stable_scene_splits(scene_ids: Iterable[str]) -> dict[str, str]:
    scenes = sorted(
        set(scene_ids),
        key=lambda scene: hashlib.sha256(
            f"{SCHEMA_VERSION}:{scene}".encode("utf-8")
        ).hexdigest(),
    )
    if len(scenes) < 3:
        raise RuntimeError("at least three scenes are required for scene-disjoint splits")
    train_count = max(1, len(scenes) - 2)
    result = {scene: "train" for scene in scenes[:train_count]}
    result[scenes[train_count]] = "validation"
    for scene in scenes[train_count + 1 :]:
        result[scene] = "test"
    return result


def load_trajectory(path: Path) -> tuple[list[dict[str, Any]], str]:
    rows = []
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        for line_bytes in raw:
            digest.update(line_bytes)
            if not line_bytes.strip():
                continue
            row = json.loads(line_bytes)
            if row.get("phase") == "return":
                rows.append(row)
    if not rows:
        raise SkipEpisode("return_trajectory_empty")
    return rows, digest.hexdigest()


def load_anchors(path: Path) -> list[dict[str, Any]]:
    anchors = (json_load(path) or {}).get("anchors") or []
    clean = [
        anchor
        for anchor in anchors
        if anchor.get("index") is not None
        and anchor.get("distance_from_start_m") is not None
        and anchor.get("world_pose") is not None
        and len(anchor["world_pose"]) >= 2
    ]
    clean.sort(key=lambda anchor: int(anchor["index"]))
    if len(clean) < 2:
        raise SkipEpisode("insufficient_oracle_anchors")
    return clean


def xy(row: dict[str, Any]) -> tuple[float, float]:
    return float(row["position"][0]), float(row["position"][1])


def distance_xy(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_projection(
    position: tuple[float, float],
    a: dict[str, Any],
    b: dict[str, Any],
) -> tuple[float, float, float]:
    px, py = position
    ax, ay = float(a["world_pose"][0]), float(a["world_pose"][1])
    bx, by = float(b["world_pose"][0]), float(b["world_pose"][1])
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom <= 1e-9 else max(
        0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom)
    )
    qx, qy = ax + t * vx, ay + t * vy
    cross_track = math.hypot(px - qx, py - qy)
    route_s = float(a["distance_from_start_m"]) + t * (
        float(b["distance_from_start_m"]) - float(a["distance_from_start_m"])
    )
    return cross_track, route_s, t


def align_route_viterbi(
    rows: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Continuity-aware polyline alignment that permits real backtracking."""
    segments = list(zip(anchors[:-1], anchors[1:]))
    if not rows or not segments:
        return {}
    observations = []
    for row in rows:
        pos = xy(row)
        observations.append(
            [segment_projection(pos, a, b) for a, b in segments]
        )

    costs = []
    first = []
    last_index = len(segments) - 1
    for state, (cross, route_s, _t) in enumerate(observations[0]):
        initial_tail_penalty = 0.08 * max(0, last_index - state)
        first.append(cross * cross + initial_tail_penalty)
    costs.append(first)
    backpointers: list[list[int]] = [[-1] * len(segments)]

    for time_index in range(1, len(rows)):
        move = distance_xy(xy(rows[time_index - 1]), xy(rows[time_index]))
        current_costs = []
        current_back = []
        for state, (cross, route_s, _t) in enumerate(observations[time_index]):
            best_cost = None
            best_prev = 0
            for previous, (_pcross, previous_s, _pt) in enumerate(
                observations[time_index - 1]
            ):
                route_delta = abs(route_s - previous_s)
                motion_mismatch = abs(route_delta - move)
                excessive = max(0.0, route_delta - move - 1.25)
                reverse = max(0.0, route_s - previous_s)
                transition = (
                    0.20 * motion_mismatch
                    + 3.0 * excessive
                    + 0.35 * reverse
                )
                value = costs[-1][previous] + transition
                if best_cost is None or value < best_cost:
                    best_cost = value
                    best_prev = previous
            current_costs.append(float(best_cost) + cross * cross)
            current_back.append(best_prev)
        costs.append(current_costs)
        backpointers.append(current_back)

    states = [0] * len(rows)
    states[-1] = min(range(len(segments)), key=lambda state: costs[-1][state])
    for time_index in range(len(rows) - 1, 0, -1):
        states[time_index - 1] = backpointers[time_index][states[time_index]]

    aligned: dict[int, dict[str, Any]] = {}
    for row, state, projections in zip(rows, states, observations):
        cross, route_s, t = projections[state]
        nonadjacent_cross = [
            value[0]
            for other_state, value in enumerate(projections)
            if abs(other_state - state) > 1
        ]
        second_gap = (
            min(nonadjacent_cross) - cross if nonadjacent_cross else None
        )
        if cross <= 1.0 and (second_gap is None or second_gap >= 0.15):
            quality = "high"
        elif cross <= 1.5:
            quality = "medium"
        else:
            quality = "low"
        aligned[int(row["step"])] = {
            "segment_index": int(state),
            "segment_anchor_indices": [
                int(segments[state][0]["index"]),
                int(segments[state][1]["index"]),
            ],
            "segment_t": float(t),
            "route_s_m": float(route_s),
            "cross_track_m": float(cross),
            "second_best_cross_track_gap_m": (
                float(second_gap) if second_gap is not None else None
            ),
            "quality": quality,
        }
    return aligned


def anchor_for_route_s(
    anchors: list[dict[str, Any]], route_s: float
) -> dict[str, Any]:
    eligible = [
        anchor
        for anchor in anchors
        if float(anchor["distance_from_start_m"]) <= float(route_s) + 1e-6
    ]
    if eligible:
        return max(eligible, key=lambda anchor: float(anchor["distance_from_start_m"]))
    return anchors[0]


def oracle_labels(
    row: dict[str, Any],
    alignment: dict[str, Any],
    anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    route_s = float(alignment["route_s_m"])
    current = anchor_for_route_s(anchors, route_s)
    target = anchor_for_route_s(anchors, max(0.0, route_s - LOOKAHEAD_M))
    pos = xy(row)
    target_pos = (
        float(target["world_pose"][0]),
        float(target["world_pose"][1]),
    )
    distance_to_target = distance_xy(pos, target_pos)
    route_distance = distance_to_target + float(target["distance_from_start_m"])
    if route_distance <= ARRIVED_MAX_M:
        terminal_class = "arrived"
    elif route_distance <= FAR_MIN_M:
        terminal_class = "boundary"
    else:
        terminal_class = "far"
    return {
        "oracle_route_s_m": route_s,
        "oracle_current_anchor_index": int(current["index"]),
        "oracle_next_anchor_index": int(target["index"]),
        "oracle_distance_to_target_anchor_m": float(distance_to_target),
        "oracle_route_distance_to_a0_m": float(route_distance),
        "terminal_class": terminal_class,
    }


def group_covisibility(round_trip: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    records = (
        (round_trip.get("route_relocalization_diagnostics") or {}).get(
            "covisibility_records"
        )
        or []
    )
    grouped: dict[int, list[dict[str, Any]]] = collections.OrderedDict()
    for record in records:
        if record.get("attempt") is None:
            continue
        grouped.setdefault(int(record["attempt"]), []).append(record)
    if not grouped:
        raise SkipEpisode("covisibility_records_missing")
    return grouped


def load_v11_attempts(directory: Path) -> dict[int, dict[str, Any]]:
    path = directory / "reliability_v11_shadow.jsonl"
    if not path.exists():
        return {}
    result = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("event") == "v11_shadow_score":
                    result[int(event["attempt"])] = event
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return result


def attempt_step_map(
    attempts: list[int],
    return_rows: list[dict[str, Any]],
    round_trip: dict[str, Any],
    v11_attempts: dict[int, dict[str, Any]],
) -> tuple[dict[int, int], str]:
    if all(
        attempt in v11_attempts and v11_attempts[attempt].get("step") is not None
        for attempt in attempts
    ):
        return (
            {attempt: int(v11_attempts[attempt]["step"]) for attempt in attempts},
            "v11_shadow_exact_step",
        )
    events = (round_trip.get("route_memory") or {}).get("relocalization_events") or []
    if len(events) >= len(attempts):
        mapping = {}
        for ordinal, attempt in enumerate(attempts):
            count = events[ordinal].get("evidence_update_count")
            if count is None:
                break
            row_index = max(0, min(len(return_rows) - 1, int(count) - 1))
            mapping[attempt] = int(return_rows[row_index]["step"])
        if len(mapping) == len(attempts):
            return mapping, "evidence_update_count_exact"
    if len(attempts) == 1:
        return {attempts[0]: int(return_rows[0]["step"])}, (
            "linear_attempt_interpolation_approximate"
        )
    mapping = {}
    denominator = max(1, len(attempts) - 1)
    for ordinal, attempt in enumerate(attempts):
        fraction = ordinal / denominator
        row_index = int(round(fraction * (len(return_rows) - 1)))
        mapping[attempt] = int(return_rows[row_index]["step"])
    return mapping, "linear_attempt_interpolation_approximate"


def nearest_row(
    rows_by_step: dict[int, dict[str, Any]], step: int
) -> dict[str, Any]:
    if step in rows_by_step:
        return rows_by_step[step]
    key = min(rows_by_step, key=lambda candidate: abs(candidate - step))
    return rows_by_step[key]


def compact_candidate(
    record: dict[str, Any],
    v11_output: dict[str, Any] | None,
) -> dict[str, Any]:
    value = {field: record.get(field) for field in RAW_CANDIDATE_FIELDS}
    value["yaw_curve"] = {
        field: (record.get("yaw_curve") or {}).get(field)
        for field in (
            "available",
            "yaw_score_entropy",
            "yaw_score_normalized_entropy",
            "yaw_peak_width_deg",
            "yaw_top1_next_distinct_gap_deg",
            "yaw_top1_next_distinct_score_ratio",
        )
    }
    value["localizability"] = {
        field: (record.get("localizability") or {}).get(field)
        for field in (
            "available",
            "condition_number",
            "min_normalized_eigenvalue",
            "weak_direction_count",
            "yaw_normalized_marginal_information",
        )
    }
    value["scan_context"] = {
        field: (record.get("scan_context_yaw_check") or {}).get(field)
        for field in (
            "available",
            "scan_context_similarity",
            "scan_context_region_ratio",
            "icp_scan_context_yaw_agreement_deg",
        )
    }
    value["v11"] = {
        field: (v11_output or {}).get(field)
        for field in (
            "anchor_role",
            "p_pose_bad",
            "p_distance_bad_0p5",
            "p_bearing_bad_30",
            "pose_trusted",
            "distance_trusted",
            "bearing_trusted",
            "jointly_trusted",
        )
    }
    return value


def support_events_by_attempt(round_trip: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result = {}
    for event in round_trip.get("phase_events") or []:
        if (
            event.get("event") == "v11_anchor_support_recovery"
            and event.get("attempt") is not None
        ):
            result[int(event["attempt"])] = event
    return result


def safe_support_features(event: dict[str, Any] | None) -> dict[str, Any]:
    event = event or {}
    fields = (
        "mode",
        "action",
        "current_anchor_index",
        "next_anchor_index",
        "reconstruct_next_from_current",
        "vlm_only",
        "probe_anchor_indices",
        "promotion_blocked_anchor_indices",
    )
    return {field: event.get(field) for field in fields}


def movement_features(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if previous is None:
        return {
            "steps_since_previous": None,
            "translation_since_previous_m": None,
            "yaw_change_since_previous_deg": None,
        }
    return {
        "steps_since_previous": int(current["step"]) - int(previous["step"]),
        "translation_since_previous_m": distance_xy(xy(current), xy(previous)),
        "yaw_change_since_previous_deg": abs(
            ((float(current.get("yaw_deg", 0.0)) - float(previous.get("yaw_deg", 0.0)) + 180.0) % 360.0)
            - 180.0
        ),
    }


def route_memory_inputs(row: dict[str, Any]) -> dict[str, Any]:
    memory = row.get("route_memory") or {}
    return {field: memory.get(field) for field in ROUTE_MEMORY_INPUT_FIELDS}


def query_rows(return_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for row in return_rows:
        query_step = row.get("last_vlm_step")
        if query_step is None:
            continue
        if int(row["step"]) != int(query_step) or int(query_step) in seen:
            continue
        seen.add(int(query_step))
        result.append(row)
    return result


def stop_requested(row: dict[str, Any]) -> bool:
    output = str(row.get("last_vlm_output") or "").lower()
    return "stop" in output or "finished" in output


def visual_events_by_step(round_trip: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result = {}
    for event in round_trip.get("phase_events") or []:
        if (
            event.get("event") == "stop_gate_a0_visual_probe"
            and event.get("step") is not None
        ):
            result[int(event["step"])] = event
    return result


def latest_attempt_at_step(
    ordered: list[tuple[int, int]],
    step: int,
) -> int | None:
    value = None
    for candidate_step, attempt in ordered:
        if candidate_step > step:
            break
        value = attempt
    return value


def historical_gate(row: dict[str, Any]) -> dict[str, Any]:
    gate = row.get("stop_gate") or {}
    return {
        field: gate.get(field)
        for field in (
            "gate_decision",
            "gate_state",
            "gate_reason",
            "gate_evidence_authority",
            "gate_authority_d",
            "gate_conf",
            "gate_distance_interval_m",
            "gate_visual_home_confirmed",
            "gate_blind_query_count",
            "gate_pre_stop_blind_query_count",
        )
    }


def terminal_action_label(terminal_class: str, requested_stop: bool) -> str:
    if requested_stop:
        if terminal_class == "arrived":
            return "accept"
        if terminal_class == "far":
            return "reject"
        return "verify"
    if terminal_class == "arrived":
        return "arrived_without_stop"
    return "continue"


def build_episode_rows(
    source: EpisodeSource,
    measurement: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    round_trip = measurement.get("round_trip") or {}
    return_rows, computed_trajectory_sha = load_trajectory(source.trajectory_path)
    if source.trajectory_sha256 != computed_trajectory_sha:
        raise SkipEpisode("trajectory_hash_mismatch")
    anchors = load_anchors(source.anchors_path)
    grouped = group_covisibility(round_trip)
    v11_attempts = load_v11_attempts(source.directory)
    attempts = sorted(grouped)
    attempt_steps, step_method = attempt_step_map(
        attempts, return_rows, round_trip, v11_attempts
    )
    step_alignment_weight = (
        0.5
        if step_method == "linear_attempt_interpolation_approximate"
        else 1.0
    )
    rows_by_step = {int(row["step"]): row for row in return_rows}
    query = query_rows(return_rows)
    label_steps = sorted(set(attempt_steps.values()) | {int(row["step"]) for row in query})
    label_rows = [nearest_row(rows_by_step, step) for step in label_steps]
    alignment = align_route_viterbi(label_rows, anchors)
    support = support_events_by_attempt(round_trip)

    anchor_rows = []
    previous_attempt_row = None
    for attempt in attempts:
        step = attempt_steps[attempt]
        trajectory_row = nearest_row(rows_by_step, step)
        aligned = alignment[int(trajectory_row["step"])]
        labels = oracle_labels(trajectory_row, aligned, anchors)
        v11_event = v11_attempts.get(attempt) or {}
        outputs = {
            int(output["anchor_index"]): output
            for output in v11_event.get("outputs") or []
            if output.get("anchor_index") is not None
        }
        candidates = [
            compact_candidate(
                record,
                outputs.get(int(record["anchor_index"]))
                if record.get("anchor_index") is not None
                else None,
            )
            for record in grouped[attempt]
        ]
        candidate_indices = {
            int(candidate["anchor_index"])
            for candidate in candidates
            if candidate.get("anchor_index") is not None
        }
        support_input = safe_support_features(support.get(attempt))
        observed_next = support_input.get("next_anchor_index")
        if observed_next is None:
            observed_next = next(
                (
                    candidate["anchor_index"]
                    for candidate in candidates
                    if (candidate.get("v11") or {}).get("anchor_role") == "next"
                ),
                None,
            )
        if observed_next is None:
            inferred_pair = sorted(candidate_indices, reverse=True)
            if len(inferred_pair) >= 2:
                observed_next = inferred_pair[1]
        oracle_next = int(labels["oracle_next_anchor_index"])
        if observed_next is None:
            transition_label = "rebase"
        else:
            delta = int(observed_next) - oracle_next
            if delta == 0:
                transition_label = "hold"
            elif delta == 1:
                transition_label = "advance_one"
            elif delta > 1:
                transition_label = "skip_or_rebase"
            else:
                transition_label = "rollback"
        record = {
            "schema": SCHEMA_VERSION,
            "task": "anchor_state",
            "episode": {
                "episode_key": source.episode_key,
                "physical_episode_id": source.physical_episode_id,
                "scene_id": source.scene_id,
                "split": source.split,
            },
            "time": {
                "attempt": attempt,
                "step": int(trajectory_row["step"]),
                "attempt_step_alignment": step_method,
            },
            "inputs": {
                "movement": movement_features(trajectory_row, previous_attempt_row),
                "route_memory": route_memory_inputs(trajectory_row),
                "support": support_input,
                "candidates": candidates,
            },
            "oracle_alignment": aligned,
            "labels": {
                **labels,
                "oracle_next_present_in_candidates": oracle_next in candidate_indices,
                "transition_action": transition_label,
                "sample_weight": (
                    1.0 * step_alignment_weight
                    if aligned["quality"] == "high"
                    else 0.5 * step_alignment_weight
                    if aligned["quality"] == "medium"
                    else 0.0
                ),
            },
            "historical_policy": {
                "observed_next_anchor_index": observed_next,
            },
        }
        anchor_rows.append(record)
        previous_attempt_row = trajectory_row

    visual = visual_events_by_step(round_trip)
    ordered_attempt_steps = sorted(
        (step, attempt) for attempt, step in attempt_steps.items()
    )
    anchor_by_attempt = {
        int(row["time"]["attempt"]): row for row in anchor_rows
    }
    terminal_rows = []
    previous_query_row = None
    for trajectory_row in query:
        step = int(trajectory_row["step"])
        aligned = alignment[step]
        labels = oracle_labels(trajectory_row, aligned, anchors)
        latest_attempt = latest_attempt_at_step(ordered_attempt_steps, step)
        latest_anchor = (
            anchor_by_attempt.get(latest_attempt)
            if latest_attempt is not None
            else None
        )
        visual_event = visual.get(step) or {}
        requested = stop_requested(trajectory_row)
        terminal_rows.append(
            {
                "schema": SCHEMA_VERSION,
                "task": "terminal_decision",
                "episode": {
                    "episode_key": source.episode_key,
                    "physical_episode_id": source.physical_episode_id,
                    "scene_id": source.scene_id,
                    "split": source.split,
                },
                "time": {"step": step, "latest_attempt": latest_attempt},
                "inputs": {
                    "movement": movement_features(
                        trajectory_row, previous_query_row
                    ),
                    "route_memory": route_memory_inputs(trajectory_row),
                    "vlm_requested_stop": requested,
                    "a0_visual": {
                        "available": visual_event.get("available"),
                        "confirmed": visual_event.get("confirmed"),
                        "distance_to_a0_m": visual_event.get("distance_to_a0_m"),
                        "confidence": visual_event.get("confidence"),
                    },
                    "anchor_state_summary": (
                        {
                            "support": latest_anchor["inputs"]["support"],
                            "candidates": latest_anchor["inputs"]["candidates"],
                        }
                        if latest_anchor is not None
                        else None
                    ),
                },
                "oracle_alignment": aligned,
                "labels": {
                    **labels,
                    "terminal_action": terminal_action_label(
                        labels["terminal_class"], requested
                    ),
                    "sample_weight": (
                        1.0 * step_alignment_weight
                        if aligned["quality"] == "high"
                        else 0.5 * step_alignment_weight
                        if aligned["quality"] == "medium"
                        else 0.0
                    ),
                },
                "historical_policy": {
                    "stop_gate": historical_gate(trajectory_row),
                },
            }
        )
        previous_query_row = trajectory_row

    episode_record = {
        "schema": SCHEMA_VERSION,
        "episode_key": source.episode_key,
        "physical_episode_id": source.physical_episode_id,
        "scene_id": source.scene_id,
        "split": source.split,
        "source": {
            "directory": str(source.directory),
            "trajectory": str(source.trajectory_path),
            "measurement": str(source.measurement_path),
            "anchors": str(source.anchors_path),
            "trajectory_sha256": source.trajectory_sha256,
            "measurement_sha256": source.measurement_sha256,
            "anchors_sha256": source.anchors_sha256,
        },
        "counts": {
            "return_rows": len(return_rows),
            "relocalization_attempts": len(anchor_rows),
            "terminal_queries": len(terminal_rows),
            "anchors": len(anchors),
        },
        "outcome": {
            "outbound_success": round_trip.get("outbound_success"),
            "return_success": round_trip.get("return_success"),
            "round_trip_success": round_trip.get("round_trip_success"),
            "return_terminal_safe_fail": round_trip.get(
                "return_terminal_safe_fail"
            ),
        },
        "attempt_step_alignment": step_method,
    }
    return anchor_rows, terminal_rows, episode_record


def class_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(
        sorted(
            collections.Counter(
                str(row["labels"].get(field)) for row in rows
            ).items()
        )
    )


def manifest_hashes(output_dir: Path) -> None:
    paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "DATA_MANIFEST.sha256"
    )
    lines = [f"{sha256_file(path)}  {path.name}" for path in paths]
    (output_dir / "DATA_MANIFEST.sha256").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    source_root = Path(args.source_root).resolve()
    episode_dataset = Path(args.episode_dataset).resolve()
    scene_lookup = load_scene_lookup(episode_dataset)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    anchor_paths = sorted(source_root.glob("*/icp_replay_dataset/anchors.json"))
    if args.limit:
        anchor_paths = anchor_paths[: args.limit]

    discovered = []
    exclusions = collections.Counter()
    duplicate_trajectories = 0
    seen_trajectories = set()
    for anchors_path in anchor_paths:
        directory = anchors_path.parent.parent
        try:
            source, measurement = discover_episode(directory, scene_lookup)
            if source.trajectory_sha256 in seen_trajectories:
                duplicate_trajectories += 1
                exclusions["duplicate_trajectory"] += 1
                continue
            seen_trajectories.add(source.trajectory_sha256)
            discovered.append((source, measurement))
        except SkipEpisode as exc:
            exclusions[str(exc).split(":", 1)[0]] += 1
        except Exception as exc:
            exclusions[f"unexpected_{type(exc).__name__}"] += 1

    scene_splits = stable_scene_splits(source.scene_id for source, _ in discovered)
    for source, _measurement in discovered:
        source.split = scene_splits[source.scene_id]

    anchor_rows: list[dict[str, Any]] = []
    terminal_rows: list[dict[str, Any]] = []
    episode_rows = []
    for index, (source, measurement) in enumerate(discovered, start=1):
        try:
            anchor_part, terminal_part, episode_record = build_episode_rows(
                source, measurement
            )
            anchor_rows.extend(anchor_part)
            terminal_rows.extend(terminal_part)
            episode_rows.append(episode_record)
        except SkipEpisode as exc:
            exclusions[str(exc).split(":", 1)[0]] += 1
        except Exception as exc:
            exclusions[f"build_{type(exc).__name__}"] += 1
        if args.progress_every and index % args.progress_every == 0:
            print(
                f"processed {index}/{len(discovered)} episodes; "
                f"anchor_rows={len(anchor_rows)} terminal_rows={len(terminal_rows)}",
                flush=True,
            )

    if not anchor_rows or not terminal_rows:
        raise RuntimeError("dataset build produced no rows")

    with gzip.open(
        output_dir / "anchor_state.jsonl.gz", "wt", encoding="utf-8", compresslevel=6
    ) as handle:
        for row in anchor_rows:
            append_jsonl(handle, row)
    with gzip.open(
        output_dir / "terminal_decision.jsonl.gz",
        "wt",
        encoding="utf-8",
        compresslevel=6,
    ) as handle:
        for row in terminal_rows:
            append_jsonl(handle, row)
    with (output_dir / "episodes.jsonl").open("w", encoding="utf-8") as handle:
        for row in episode_rows:
            append_jsonl(handle, row)

    splits = {
        "schema": SCHEMA_VERSION,
        "group": "scene_id",
        "seed_material": SCHEMA_VERSION,
        "scene_to_split": scene_splits,
        "split_to_scenes": {
            split: sorted(
                scene for scene, assigned in scene_splits.items() if assigned == split
            )
            for split in ("train", "validation", "test")
        },
    }
    (output_dir / "splits.json").write_text(
        json.dumps(splits, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    anchor_quality = class_counts(anchor_rows, "sample_weight")
    terminal_quality = class_counts(terminal_rows, "sample_weight")
    audit = {
        "schema": SCHEMA_VERSION,
        "source_root": str(source_root),
        "episode_dataset": str(episode_dataset),
        "episode_dataset_sha256": sha256_file(episode_dataset),
        "candidate_capture_directories": len(anchor_paths),
        "discovered_unique_episodes": len(discovered),
        "built_episodes": len(episode_rows),
        "duplicate_trajectories_removed": duplicate_trajectories,
        "exclusions": dict(sorted(exclusions.items())),
        "splits": {
            split: {
                "scenes": len(splits["split_to_scenes"][split]),
                "episodes": sum(
                    row["split"] == split for row in episode_rows
                ),
                "anchor_rows": sum(
                    row["episode"]["split"] == split for row in anchor_rows
                ),
                "terminal_rows": sum(
                    row["episode"]["split"] == split for row in terminal_rows
                ),
            }
            for split in ("train", "validation", "test")
        },
        "attempt_step_alignment": dict(
            sorted(
                collections.Counter(
                    row["attempt_step_alignment"] for row in episode_rows
                ).items()
            )
        ),
        "anchor_state": {
            "rows": len(anchor_rows),
            "transition_classes": class_counts(anchor_rows, "transition_action"),
            "alignment_sample_weights": anchor_quality,
            "oracle_target_candidate_coverage": sum(
                bool(row["labels"]["oracle_next_present_in_candidates"])
                for row in anchor_rows
            )
            / len(anchor_rows),
        },
        "terminal_decision": {
            "rows": len(terminal_rows),
            "terminal_classes": class_counts(terminal_rows, "terminal_class"),
            "action_classes": class_counts(terminal_rows, "terminal_action"),
            "alignment_sample_weights": terminal_quality,
            "vlm_stop_rows": sum(
                bool(row["inputs"]["vlm_requested_stop"]) for row in terminal_rows
            ),
        },
        "constants": {
            "route_lookahead_m": LOOKAHEAD_M,
            "stop_r_in_m": STOP_R_IN_M,
            "raw_margin_m": RAW_MARGIN_M,
            "arrived_max_route_distance_m": ARRIVED_MAX_M,
            "far_min_route_distance_m": FAR_MIN_M,
        },
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_hashes(output_dir)
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE))
    parser.add_argument(
        "--episode-dataset", default=str(DEFAULT_EPISODE_DATASET)
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    audit = build(parse_args())
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
