#!/usr/bin/env python3
"""Build an oracle-labelled, scene-disjoint hint-action decision dataset.

The target is deliberately counterfactual.  It does not copy the historical
arbiter's allow/block result.  For each return query where the VLM movement
direction conflicts with the route hint, it compares both choices with the
oracle-aligned return direction:

* override_hint: the hint direction is correct and the VLM direction is not;
* keep_vlm: the VLM direction is correct and the hint direction is not;
* abstain: neither direction is clearly supported.

Stop commands and non-far terminal states are excluded.  Terminal authority is
owned by the separate terminal model/state machine, and collision clearance
remains an independent hard safety condition at runtime.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterator

import build_training_datasets as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "v1"
DEFAULT_EPISODES = DEFAULT_DATA_DIR / "episodes.jsonl"
DEFAULT_TERMINAL = DEFAULT_DATA_DIR / "terminal_decision.jsonl.gz"
DEFAULT_OUTPUT = DEFAULT_DATA_DIR / "hint_action_decision.jsonl.gz"
DEFAULT_AUDIT = DEFAULT_DATA_DIR / "hint_action_audit.json"
SCHEMA = "navila-hint-action-training-v1"
ORACLE_FORWARD_CONE_DEG = 20.0
ARBITER_FORWARD_CONE_DEG = 15.0
ARBITER_FORWARD_CONFLICT_DEG = 30.0
BOUNDARY_MARGIN_DEG = 5.0


def compact_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def read_jsonl_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def action_kind(text: object) -> str:
    lower = "" if text is None else str(text).lower()
    if "stop" in lower or "finished" in lower:
        return "stop"
    if "turn left" in lower:
        return "left"
    if "turn right" in lower:
        return "right"
    if "move forward" in lower or "move" in lower:
        return "forward"
    return "unknown"


def direction_kind(bearing_deg: float, forward_cone_deg: float) -> str:
    if abs(float(bearing_deg)) <= float(forward_cone_deg):
        return "forward"
    return "left" if float(bearing_deg) > 0.0 else "right"


def conflicts(
    original: str,
    desired: str,
    bearing_deg: float,
) -> bool:
    if original in {"unknown", "stop"}:
        return True
    if desired == "forward":
        return original in {"left", "right"}
    if desired == "left":
        return original == "right" or (
            original == "forward"
            and abs(float(bearing_deg)) >= ARBITER_FORWARD_CONFLICT_DEG
        )
    if desired == "right":
        return original == "left" or (
            original == "forward"
            and abs(float(bearing_deg)) >= ARBITER_FORWARD_CONFLICT_DEG
        )
    return False


def body_frame_bearing_deg(
    robot_position: list[float],
    robot_yaw_rad: float,
    target_position: list[float],
) -> float:
    dx_world = float(target_position[0]) - float(robot_position[0])
    dy_world = float(target_position[1]) - float(robot_position[1])
    c = math.cos(float(robot_yaw_rad))
    s = math.sin(float(robot_yaw_rad))
    dx_body = dx_world * c + dy_world * s
    dy_body = -dx_world * s + dy_world * c
    if math.hypot(dx_body, dy_body) <= 1e-9:
        return 0.0
    return math.degrees(math.atan2(dy_body, dx_body))


def route_memory_provenance_is_oracle(row: dict[str, Any]) -> bool:
    route_memory = row["inputs"].get("route_memory") or {}
    provenance = " ".join(
        str(route_memory.get(field) or "").lower()
        for field in ("source", "configured_source", "relocalization_backend")
    )
    return "oracle" in provenance or "isaac" in provenance


def load_terminal_rows(
    path: Path,
) -> dict[str, dict[int, dict[str, Any]]]:
    result: dict[str, dict[int, dict[str, Any]]] = collections.defaultdict(dict)
    for row in read_jsonl_gz(path):
        result[row["episode"]["episode_key"]][int(row["time"]["step"])] = row
    return result


def label_for_choices(
    original_kind: str,
    desired_kind: str,
    oracle_kind: str,
) -> str:
    hint_correct = desired_kind == oracle_kind
    vlm_correct = original_kind == oracle_kind
    if hint_correct and not vlm_correct:
        return "override_hint"
    if vlm_correct and not hint_correct:
        return "keep_vlm"
    return "abstain"


def sample_weight(
    inherited_weight: float,
    oracle_bearing_deg: float,
) -> float:
    boundary_distance = abs(
        abs(float(oracle_bearing_deg)) - ORACLE_FORWARD_CONE_DEG
    )
    if boundary_distance < BOUNDARY_MARGIN_DEG:
        return 0.5 * float(inherited_weight)
    return float(inherited_weight)


def build_row(
    episode: dict[str, Any],
    terminal: dict[str, Any],
    trajectory: dict[str, Any],
    anchors: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    arbiter = trajectory.get("hint_action_arbiter") or {}
    if not arbiter.get("enabled"):
        return None, "arbiter_not_logged"

    original = action_kind(arbiter.get("original_output"))
    if original == "stop":
        return None, "terminal_stop_owned_elsewhere"
    if original == "unknown":
        return None, "unparseable_vlm_direction"

    bearing = arbiter.get("desired_bearing_deg")
    if bearing is None:
        bearing = (trajectory.get("route_memory") or {}).get(
            "bearing_to_anchor_deg"
        )
    if bearing is None:
        return None, "missing_hint_bearing"
    desired = arbiter.get("desired_kind") or direction_kind(
        float(bearing), ARBITER_FORWARD_CONE_DEG
    )
    if desired not in {"forward", "left", "right"}:
        return None, "missing_hint_direction"
    if not conflicts(original, desired, float(bearing)):
        return None, "no_direction_conflict"

    labels = terminal["labels"]
    if labels.get("terminal_class") != "far":
        return None, "nonfar_owned_by_terminal"
    oracle_anchor_index = labels.get("oracle_next_anchor_index")
    if oracle_anchor_index is None or int(oracle_anchor_index) not in anchors:
        return None, "oracle_target_anchor_missing"
    if trajectory.get("yaw_rad") is None or trajectory.get("position") is None:
        return None, "oracle_pose_missing"

    oracle_anchor = anchors[int(oracle_anchor_index)]
    oracle_bearing = body_frame_bearing_deg(
        trajectory["position"],
        float(trajectory["yaw_rad"]),
        oracle_anchor["world_pose"],
    )
    oracle_kind = direction_kind(oracle_bearing, ORACLE_FORWARD_CONE_DEG)
    choice_label = label_for_choices(original, desired, oracle_kind)
    inherited_weight = float(labels.get("sample_weight") or 0.0)
    weight = sample_weight(inherited_weight, oracle_bearing)

    arbiter_inputs = {
        "desired_kind": desired,
        "desired_bearing_deg": float(bearing),
        "desired_distance_m": arbiter.get("desired_distance_m"),
        "target_anchor_index": arbiter.get("target_anchor_index"),
        "relocalization_confidence": arbiter.get(
            "relocalization_confidence"
        ),
    }
    return (
        {
            "schema": SCHEMA,
            "task": "hint_action_decision",
            "episode": {
                "episode_key": terminal["episode"]["episode_key"],
                "physical_episode_id": terminal["episode"][
                    "physical_episode_id"
                ],
                "scene_id": terminal["episode"]["scene_id"],
                "split": terminal["episode"]["split"],
            },
            "time": dict(terminal["time"]),
            "inputs": {
                "movement": terminal["inputs"].get("movement") or {},
                "route_memory": terminal["inputs"].get("route_memory") or {},
                "vlm_action_kind": original,
                "arbiter_proposal": arbiter_inputs,
                "anchor_state_summary": terminal["inputs"].get(
                    "anchor_state_summary"
                ),
            },
            "labels": {
                "decision": choice_label,
                "sample_weight": weight,
                "oracle_direction_kind": oracle_kind,
                "oracle_bearing_to_route_target_deg": oracle_bearing,
                "oracle_next_anchor_index": int(oracle_anchor_index),
                "terminal_class": labels["terminal_class"],
            },
            "oracle_alignment": terminal.get("oracle_alignment"),
            "historical_policy": {
                "override": bool(arbiter.get("override")),
                "reason": arbiter.get("reason"),
                "clear_path_available": arbiter.get("clear_path_available"),
                "clear_path": arbiter.get("clear_path"),
                "clear_path_source": arbiter.get("clear_path_source"),
                "min_clearance_m": arbiter.get("min_clearance_m"),
            },
            "provenance": {
                "parent_terminal_dataset_sha256": episode[
                    "_terminal_dataset_sha256"
                ],
                "trajectory_sha256": episode["source"][
                    "trajectory_sha256"
                ],
                "anchors_sha256": episode["source"]["anchors_sha256"],
            },
        },
        "included",
    )


def historical_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [
        row
        for row in rows
        if row["labels"]["sample_weight"] > 0.0
        and row["labels"]["decision"] != "abstain"
    ]
    true_positive = sum(
        row["labels"]["decision"] == "override_hint"
        and row["historical_policy"]["override"]
        for row in evaluated
    )
    false_positive = sum(
        row["labels"]["decision"] == "keep_vlm"
        and row["historical_policy"]["override"]
        for row in evaluated
    )
    false_negative = sum(
        row["labels"]["decision"] == "override_hint"
        and not row["historical_policy"]["override"]
        for row in evaluated
    )
    true_negative = sum(
        row["labels"]["decision"] == "keep_vlm"
        and not row["historical_policy"]["override"]
        for row in evaluated
    )
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    return {
        "evaluated_rows": len(evaluated),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "override_precision": precision,
        "override_recall": recall,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    episodes_path = Path(args.episodes).resolve()
    terminal_path = Path(args.terminal).resolve()
    output_path = Path(args.output).resolve()
    audit_path = Path(args.audit).resolve()
    terminal_sha = sha256_file(terminal_path)
    terminal_rows = load_terminal_rows(terminal_path)

    rows: list[dict[str, Any]] = []
    exclusions: collections.Counter[str] = collections.Counter()
    episodes_with_rows = set()
    for episode in read_jsonl(episodes_path):
        episode["_terminal_dataset_sha256"] = terminal_sha
        episode_key = episode["episode_key"]
        if episode_key not in terminal_rows:
            exclusions["episode_missing_from_terminal_dataset"] += 1
            continue
        trajectory_path = Path(episode["source"]["trajectory"])
        anchors_path = Path(episode["source"]["anchors"])
        try:
            trajectory_rows, trajectory_sha = base.load_trajectory(
                trajectory_path
            )
            if trajectory_sha != episode["source"]["trajectory_sha256"]:
                exclusions["trajectory_hash_mismatch"] += 1
                continue
            anchors = {
                int(anchor["index"]): anchor
                for anchor in base.load_anchors(anchors_path)
            }
        except Exception as exc:
            exclusions[f"source_{type(exc).__name__}"] += 1
            continue

        query_by_step = {
            int(row["step"]): row for row in base.query_rows(trajectory_rows)
        }
        for step, terminal in sorted(terminal_rows[episode_key].items()):
            trajectory = query_by_step.get(step)
            if trajectory is None:
                exclusions["query_step_not_in_trajectory"] += 1
                continue
            row, status = build_row(
                episode, terminal, trajectory, anchors
            )
            exclusions[status] += 1
            if row is not None:
                rows.append(row)
                episodes_with_rows.add(episode_key)

    if not rows:
        raise RuntimeError("no hint-action rows were built")
    rows.sort(
        key=lambda row: (
            row["episode"]["episode_key"],
            int(row["time"]["step"]),
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(compact_json(row))
            handle.write("\n")
    os.replace(temporary, output_path)

    split_counts = collections.Counter(
        row["episode"]["split"] for row in rows
    )
    class_counts = collections.Counter(
        row["labels"]["decision"] for row in rows
    )
    positive_weight_counts = collections.Counter(
        row["labels"]["decision"]
        for row in rows
        if row["labels"]["sample_weight"] > 0.0
    )
    oracle_source_rows = sum(route_memory_provenance_is_oracle(row) for row in rows)
    audit = {
        "schema": SCHEMA,
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "parent_terminal_dataset": str(terminal_path),
        "parent_terminal_dataset_sha256": terminal_sha,
        "rows": len(rows),
        "episodes": len(episodes_with_rows),
        "scenes": sorted({row["episode"]["scene_id"] for row in rows}),
        "split_counts": dict(sorted(split_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "positive_weight_class_counts": dict(
            sorted(positive_weight_counts.items())
        ),
        "oracle_source_rows_excluded_at_training": oracle_source_rows,
        "historical_policy": historical_metrics(rows),
        "exclusions": dict(sorted(exclusions.items())),
        "label_policy": {
            "scope": "movement_direction_conflicts_while_oracle_far",
            "stop_authority": "excluded_owned_by_terminal_model",
            "collision_authority": "independent_hard_gate_not_a_model_label",
            "oracle_forward_cone_deg": ORACLE_FORWARD_CONE_DEG,
            "arbiter_forward_cone_deg": ARBITER_FORWARD_CONE_DEG,
            "arbiter_forward_conflict_deg": ARBITER_FORWARD_CONFLICT_DEG,
            "boundary_margin_deg": BOUNDARY_MARGIN_DEG,
        },
    }
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", default=str(DEFAULT_EPISODES))
    parser.add_argument("--terminal", default=str(DEFAULT_TERMINAL))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    return parser.parse_args()


def main() -> None:
    audit = build(parse_args())
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
