#!/usr/bin/env python3
"""Post-episode Hint recheck and Terminal evidence ablation scorer.

Ground-truth distance is used only after the saved episode has completed.  The
evaluator never imports this file or any learned model.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TRAINING = Path("/home/teambruce/navila-anchor-terminal-training-data-20260729")
V3 = Path("/home/teambruce/navila-hint-terminal-v3-safety-20260730")
sys.path[:0] = [
    str(TRAINING / "runtime_shadow"),
    str(TRAINING / "tools"),
    str(TRAINING / "training"),
    str(V3 / "tools"),
]

import build_training_datasets as builder  # noqa: E402
import evaluate_hint_recheck_v3 as hint_recheck  # noqa: E402
import score_hint_terminal_v2_prospective as prospective  # noqa: E402
from terminal_v2_features import TerminalV2FeatureState  # noqa: E402


SCHEMA = "navila-hint-terminal-evidence-shadow-v1"
OUTPUT_NAME = "hint_terminal_evidence_shadow_summary.json"
TERMINAL_MODEL = (
    TRAINING / "models/v2/terminal_decision_v2_robust.joblib"
)
HINT_MODEL = TRAINING / "models/v2/hint_action_decision_v2_binary.joblib"
HINT_POLICY = V3 / "models/hint_recheck_policy_v3.json"
ABLATION = ROOT / "config/terminal_evidence_ablation_v1.json"
TRAINING_EPISODES = TRAINING / "data/v1/episodes.jsonl"
PRIOR_SHADOW = TRAINING / "runtime_shadow/three_model_shadow30.tsv"
PRIOR_FIVE = {319, 498, 295, 430, 1008}


def sha256(path: Path) -> str:
    return prospective.builder.sha256_file(path)


def training_ids() -> set[int]:
    return {
        int(json.loads(line)["physical_episode_id"])
        for line in TRAINING_EPISODES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def prior_shadow_ids() -> set[int]:
    lines = PRIOR_SHADOW.read_text(encoding="utf-8").splitlines()
    return {
        int(line.split("\t", 1)[0])
        for line in lines[1:]
        if line.strip()
    }


def distance_band(distance: float, config: dict[str, Any]) -> str:
    bands = config["distance_bands_m"]
    if distance <= float(bands["arrived_max"]):
        return "arrived"
    if distance > float(bands["direct_far_strictly_greater_than"]):
        return "direct_far"
    return "boundary"


def first_accept_summary(
    records: list[dict[str, Any]],
    policy_fields: list[str],
) -> dict[str, Any]:
    result = {}
    for field in policy_fields:
        accepted = next(
            (record for record in records if record[field]), None
        )
        bands = {"arrived": 0, "boundary": 0, "direct_far": 0}
        if accepted is not None:
            bands[accepted["direct_distance_band"]] = 1
        result[field] = {
            "accepted": accepted is not None,
            "first_accept_step": (
                accepted["step"] if accepted is not None else None
            ),
            "first_accept_direct_distance_m": (
                accepted["direct_distance_to_start_m"]
                if accepted is not None
                else None
            ),
            "first_accept_band": (
                accepted["direct_distance_band"]
                if accepted is not None
                else None
            ),
            "bands": bands,
        }
    return result


def score_terminal(
    rows: list[dict[str, Any]],
    trajectory_rows: list[dict[str, Any]],
    bundle: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    probabilities, usable = prospective.model_probabilities(
        rows, TerminalV2FeatureState, bundle
    )
    arrived_index = bundle["classes"].index("arrived")
    policy = bundle["decision_policy"]["arrived_sequence_confirmation"]
    threshold = float(policy["threshold"])
    required_terminal_streak = int(policy["streak"])
    query_distance = {
        int(row["step"]): float(row["distance_to_start_m"])
        for row in builder.query_rows(trajectory_rows)
    }
    visual_config = config["a0_visual"]
    strong_threshold = float(
        visual_config["diagnostic_strong_min_confidence"]
    )
    max_visual_distance = float(
        visual_config["max_reported_distance_m"]
    )
    required_visual_streak = int(
        visual_config["required_consecutive_queries"]
    )

    terminal_streak = 0
    vlm_stop_streak = 0
    legacy_visual_streak = 0
    strong_visual_streak = 0
    records = []
    for row, probability in sorted(
        zip(usable, probabilities[:, arrived_index]),
        key=lambda value: int(value[0]["time"]["step"]),
    ):
        step = int(row["time"]["step"])
        terminal_streak = (
            terminal_streak + 1
            if float(probability) >= threshold
            else 0
        )
        terminal_confirmed = terminal_streak >= required_terminal_streak
        vlm_stop = bool(row["inputs"]["vlm_requested_stop"])
        vlm_stop_streak = vlm_stop_streak + 1 if vlm_stop else 0
        visual = row["inputs"].get("a0_visual") or {}
        legacy_positive = bool(
            vlm_stop and visual.get("confirmed") is True
        )
        legacy_visual_streak = (
            legacy_visual_streak + 1 if legacy_positive else 0
        )
        confidence = visual.get("confidence")
        visual_distance = visual.get("distance_to_a0_m")
        strong_positive = bool(
            vlm_stop
            and visual.get("available") is True
            and confidence is not None
            and float(confidence) >= strong_threshold
            and visual_distance is not None
            and float(visual_distance) <= max_visual_distance
        )
        strong_visual_streak = (
            strong_visual_streak + 1 if strong_positive else 0
        )
        gate = row["historical_policy"]["stop_gate"]
        interval = gate.get("gate_distance_interval_m")
        authority = str(gate.get("gate_evidence_authority") or "")
        authorized = authority in {
            "trusted_next_raw",
            "direct_oracle",
            "trusted_bounded_reconstruction",
        }
        trusted_far = bool(
            authorized
            and interval is not None
            and float(interval[0]) > float(
                config["distance_bands_m"][
                    "direct_far_strictly_greater_than"
                ]
            )
        )
        trusted_raw_near_legacy = bool(
            gate.get("gate_decision") in {"accepted", "forced"}
            and authority in {"trusted_next_raw", "direct_oracle"}
            and gate.get("gate_reason") in {
                "repeated_vlm_stop_and_fresh_trusted_next_near",
                "fresh_trusted_next_near_streak_without_vlm_stop",
            }
        )
        legacy_fallback = bool(
            vlm_stop_streak >= required_visual_streak
            and legacy_visual_streak >= required_visual_streak
        )
        strong_fallback = bool(
            vlm_stop_streak >= required_visual_streak
            and strong_visual_streak >= required_visual_streak
        )
        direct = query_distance[step]
        records.append(
            {
                "step": step,
                "direct_distance_to_start_m": direct,
                "direct_distance_band": distance_band(direct, config),
                "terminal_arrived_probability": float(probability),
                "terminal_probability_streak": terminal_streak,
                "vlm_requested_stop": vlm_stop,
                "vlm_stop_streak": vlm_stop_streak,
                "a0_probe_recorded": visual.get("available") is not None,
                "a0_available": visual.get("available"),
                "a0_confirmed_legacy": visual.get("confirmed"),
                "a0_confidence": confidence,
                "a0_reported_distance_m": visual_distance,
                "a0_legacy_streak": legacy_visual_streak,
                "a0_strong_streak": strong_visual_streak,
                "route_evidence_authority": authority or None,
                "route_distance_interval_m": interval,
                "trusted_far": trusted_far,
                "historical_gate_decision": gate.get("gate_decision"),
                "historical_gate_reason": gate.get("gate_reason"),
                "terminal_model_only": terminal_confirmed,
                "a0_hard_required_with_terminal": bool(
                    terminal_confirmed
                    and strong_visual_streak >= required_visual_streak
                    and not trusted_far
                ),
                "legacy_a0_sufficient_fallback": bool(
                    legacy_fallback and not trusted_far
                ),
                "strong_a0_sufficient_fallback": bool(
                    strong_fallback and not trusted_far
                ),
                "conditional_hierarchical": bool(
                    not trusted_far
                    and (trusted_raw_near_legacy or strong_fallback)
                ),
            }
        )

    blind = [
        record
        for record, row in zip(records, sorted(
            usable, key=lambda value: int(value["time"]["step"])
        ))
        if (
            row["historical_policy"]["stop_gate"].get("gate_state")
            == "terminal_blind"
        )
    ]
    blind_with_probe = sum(
        record["a0_probe_recorded"] for record in blind
    )
    fields = list(config["policies"])
    return {
        "rows": len(records),
        "frozen_terminal_threshold": threshold,
        "frozen_terminal_streak": required_terminal_streak,
        "terminal_blind_probe_coverage": {
            "terminal_blind_query_rows": len(blind),
            "rows_with_a0_probe_record": blind_with_probe,
            "fraction": (
                blind_with_probe / len(blind) if blind else None
            ),
            "complete": blind_with_probe == len(blind),
        },
        "policy_first_accept": first_accept_summary(records, fields),
        "records": records,
    }


def write_summary(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            prospective.json_safe(value),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result_dir = args.result_dir.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else result_dir / OUTPUT_NAME
    )
    config = json.loads(ABLATION.read_text(encoding="utf-8"))
    hint_policy = json.loads(HINT_POLICY.read_text(encoding="utf-8"))
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "result_dir": str(result_dir),
        "scoreable": False,
        "control_effect": "none",
        "artifacts": {
            "terminal_model_sha256": sha256(TERMINAL_MODEL),
            "hint_model_sha256": sha256(HINT_MODEL),
            "hint_policy_sha256": sha256(HINT_POLICY),
            "terminal_ablation_sha256": sha256(ABLATION),
        },
    }
    try:
        scene_lookup = builder.load_scene_lookup(
            builder.DEFAULT_EPISODE_DATASET
        )
        source, measurement = builder.discover_episode(
            result_dir, scene_lookup
        )
        excluded = training_ids() | prior_shadow_ids() | PRIOR_FIVE
        if source.physical_episode_id in excluded:
            raise RuntimeError(
                f"episode_overlap:{source.physical_episode_id}"
            )
        _anchor, terminal_rows, _episode = builder.build_episode_rows(
            source, measurement
        )
        hint_rows = prospective.build_hint_rows(source, terminal_rows)
        trajectory_rows, _ = builder.load_trajectory(
            source.trajectory_path
        )
        terminal_bundle = joblib.load(TERMINAL_MODEL)
        hint_bundle = joblib.load(HINT_MODEL)
        terminal = score_terminal(
            terminal_rows, trajectory_rows, terminal_bundle, config
        )
        hint_scored = hint_recheck.apply_bounds(
            hint_recheck.predict_rows(hint_rows, hint_bundle),
            hint_policy,
        )
        summary.update(
            {
                "scoreable": True,
                "episode": {
                    "physical_episode_id": source.physical_episode_id,
                    "scene_id": source.scene_id,
                    "prospective_not_in_training_or_prior_shadow": True,
                },
                "terminal_evidence_ablation": terminal,
                "hint_bounded_recheck": (
                    hint_recheck.weighted_summary(hint_scored)
                ),
            }
        )
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}:{exc}"
    write_summary(output, summary)
    print(json.dumps(prospective.json_safe(summary), indent=2, sort_keys=True))
    return 0 if summary["scoreable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
