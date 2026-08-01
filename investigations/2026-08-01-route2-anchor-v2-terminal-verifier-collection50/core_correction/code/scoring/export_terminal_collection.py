#!/usr/bin/env python3
"""Export leakage-safe Terminal Core V1 observations and separate labels.

The frozen, distance-head-only Terminal Core V1 remains a proposal generator. This exporter
keeps every return query, including sub-confirmation and near-threshold rows,
so proposer recall can be improved without pretending that those rows were
production candidate events.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import joblib


ROOT = Path(__file__).resolve().parents[1]
TRAINING = Path("/home/teambruce/navila-anchor-terminal-training-data-20260729")
UNIFIED = Path("/home/teambruce/navila-unified-shadow50-20260730")
MODEL = ROOT / "models/core_v1/terminal_decision_core_v1.joblib"
sys.path[:0] = [
    str(ROOT / "training/core_v1_src"),
    str(ROOT / "training"),
    str(TRAINING / "runtime_shadow"),
    str(TRAINING / "tools"),
    str(TRAINING / "training"),
    str(UNIFIED / "scoring"),
    str(ROOT / "scoring"),
]

import build_training_datasets as builder  # noqa: E402
import score_hint_terminal_v2_prospective as prospective  # noqa: E402
from terminal_candidate_verifier_features import (  # noqa: E402
    TerminalCandidateVerifierState,
)
from terminal_v2_features import TerminalV2FeatureState  # noqa: E402


CONTROL_DT_S = 0.02
ARRIVED_MAX_M = 2.65
BOUNDARY_MAX_M = 3.35


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def distance_band(distance: float) -> str:
    if distance <= ARRIVED_MAX_M:
        return "arrived"
    if distance <= BOUNDARY_MAX_M:
        return "boundary"
    return "far"


def action_integrated_motion(
    trajectory: list[dict[str, Any]], query_steps: list[int]
) -> dict[int, dict[str, Any] | None]:
    """Integrate commanded velocities; never read trajectory pose or yaw."""

    return_rows = sorted(
        (row for row in trajectory if row.get("phase") == "return"),
        key=lambda row: int(row["step"]),
    )
    result: dict[int, dict[str, Any] | None] = {}
    previous: int | None = None
    for step in sorted(query_steps):
        if previous is None:
            result[step] = None
            previous = step
            continue
        translation = 0.0
        yaw_radians = 0.0
        covered = 0
        for row in return_rows:
            row_step = int(row["step"])
            if row_step < previous:
                continue
            if row_step >= step:
                break
            command = row.get("command")
            if not isinstance(command, list) or len(command) < 3:
                continue
            x, y, yaw = (finite(command[index]) for index in range(3))
            if x is None or y is None or yaw is None:
                continue
            translation += math.hypot(x, y) * CONTROL_DT_S
            yaw_radians += abs(yaw) * CONTROL_DT_S
            covered += 1
        result[step] = {
            "source": "action_integrated",
            "translation_m": translation,
            "yaw_change_deg": math.degrees(yaw_radians),
            "control_dt_s": CONTROL_DT_S,
            "integrated_control_steps": covered,
        }
        previous = step
    return result


def selected(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value.get(key) for key in keys if key in value}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, allow_nan=False, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def export(result_dir: Path, arm: str) -> dict[str, Any]:
    scene_lookup = builder.load_scene_lookup(builder.DEFAULT_EPISODE_DATASET)
    source, measurement = builder.discover_episode(result_dir, scene_lookup)
    _anchor, rows, _episode = builder.build_episode_rows(source, measurement)
    trajectory, trajectory_sha = builder.load_trajectory(source.trajectory_path)
    bundle = joblib.load(MODEL)
    probabilities, usable = prospective.model_probabilities(
        rows, TerminalV2FeatureState, bundle
    )
    arrived_index = bundle["classes"].index("arrived")
    policy = bundle["decision_policy"]["arrived_sequence_confirmation"]
    threshold = float(policy["threshold"])
    required_streak = int(policy["streak"])
    near_threshold = max(0.50, threshold - 0.15)

    direct_by_step = {
        int(row["step"]): float(row["distance_to_start_m"])
        for row in builder.query_rows(trajectory)
    }
    ordered = sorted(
        zip(usable, probabilities[:, arrived_index]),
        key=lambda value: int(value[0]["time"]["step"]),
    )
    motion = action_integrated_motion(
        trajectory, [int(row["time"]["step"]) for row, _ in ordered]
    )
    verifier = TerminalCandidateVerifierState(terminal_threshold=threshold)
    observations: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    strata: collections.Counter[str] = collections.Counter()
    bands: collections.Counter[str] = collections.Counter()
    candidate_bands: collections.Counter[str] = collections.Counter()

    for row, raw_probability in ordered:
        probability = float(raw_probability)
        step = int(row["time"]["step"])
        deployable_motion = motion[step]
        features = verifier.transform(
            row,
            terminal_probability=probability,
            deployable_motion=deployable_motion,
        )
        streak = int(features["proposal.terminal_streak"])
        if streak == required_streak:
            stratum = "production_candidate_first"
        elif streak > required_streak:
            stratum = "production_candidate_tail"
        elif probability >= threshold:
            stratum = "threshold_hit_preconfirmation"
        elif probability >= near_threshold:
            stratum = "near_threshold_auxiliary"
        else:
            stratum = "background"
        event_id = (
            f"{arm}:ep{int(source.physical_episode_id)}:step{step}"
        )
        inputs = row.get("inputs") or {}
        route = inputs.get("route_memory") or {}
        visual = inputs.get("a0_visual") or {}
        gate = (row.get("historical_policy") or {}).get("stop_gate") or {}
        observations.append(
            {
                "schema": "navila-terminal-active-evidence-observation-v1",
                "event_id": event_id,
                "arm": arm,
                "physical_episode_id": int(source.physical_episode_id),
                "scene_id": source.scene_id,
                "step": step,
                "proposal_stratum": stratum,
                "frozen_proposal": {
                    "arrived_probability": probability,
                    "threshold": threshold,
                    "streak": streak,
                    "required_streak": required_streak,
                },
                "vlm_requested_stop": bool(inputs.get("vlm_requested_stop")),
                "a0_visual": selected(
                    visual,
                    (
                        "available",
                        "confirmed",
                        "confidence",
                        "distance_to_a0_m",
                        "frame_id",
                        "image_path",
                        "probe_reason",
                    ),
                ),
                "motion_since_previous_query": deployable_motion,
                "route_memory": selected(
                    route,
                    (
                        "distance_to_start_m",
                        "bearing_to_start_deg",
                        "relocalization_confidence",
                        "filter_std_m",
                        "target_anchor_index",
                        "relocalization_backend",
                        "estimate_kind",
                        "evidence_age_updates",
                        "relocalization_interval_updates",
                    ),
                ),
                "stop_gate": selected(
                    gate,
                    (
                        "gate_state",
                        "gate_decision",
                        "gate_reason",
                        "gate_evidence_authority",
                        "gate_distance_interval_m",
                    ),
                ),
                "verifier_features": features,
                "artifacts": {
                    "terminal_model_sha256": sha256(MODEL),
                    "trajectory_sha256": trajectory_sha,
                    "exporter_sha256": sha256(Path(__file__).resolve()),
                },
            }
        )
        distance = direct_by_step[step]
        band = distance_band(distance)
        labels.append(
            {
                "schema": "navila-terminal-active-evidence-label-v1",
                "event_id": event_id,
                "direct_distance_to_start_m": distance,
                "terminal_band": band,
            }
        )
        strata[stratum] += 1
        bands[band] += 1
        if stratum == "production_candidate_first":
            candidate_bands[band] += 1

    write_jsonl(result_dir / "terminal_observations.jsonl", observations)
    write_jsonl(result_dir / "terminal_labels.jsonl", labels)
    summary = {
        "schema": "navila-terminal-active-evidence-export-summary-v1",
        "arm": arm,
        "physical_episode_id": int(source.physical_episode_id),
        "scene_id": source.scene_id,
        "query_rows": len(observations),
        "proposal_strata": dict(sorted(strata.items())),
        "label_bands": dict(sorted(bands.items())),
        "production_candidate_first_bands": dict(sorted(candidate_bands.items())),
        "observation_label_files_physically_separate": True,
        "legacy_oracle_trajectory_motion_used_as_feature": False,
        "motion_source": "action_integrated",
    }
    write_json(result_dir / "terminal_collection_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--arm", required=True)
    args = parser.parse_args()
    summary = export(args.result_dir.resolve(), args.arm)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
