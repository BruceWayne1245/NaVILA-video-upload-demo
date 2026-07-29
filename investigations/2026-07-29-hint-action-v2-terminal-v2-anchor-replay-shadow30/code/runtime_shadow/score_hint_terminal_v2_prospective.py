#!/usr/bin/env python3
"""Read-only scoring of hint v1 and robust terminal v2 on prospective runs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "training"))

import build_hint_action_dataset as hint_builder  # noqa: E402
import build_training_datasets as builder  # noqa: E402
from hint_action_features import HintActionCausalFeatureState  # noqa: E402
from terminal_v2_features import TerminalV2FeatureState  # noqa: E402
from train_hint_action_model import (  # noqa: E402
    historical_metrics,
    intervention_metrics,
)
from train_models import apply_temperature, evaluate  # noqa: E402
from train_terminal_v2 import sequence_metrics  # noqa: E402


SCHEMA = "navila-hint-terminal-v2-prospective-replay"
DEFAULT_EVAL_ROOT = Path(
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
)
RUN_PREFIX = (
    "round_trip_phase_prompt_go2_matterport_vision_loco_"
    "2024-09-25_23-22-02_"
    "learned_anchor_terminal_replay_shadow_5ep_20260729_ep"
)


def json_safe(value: Any) -> Any:
    """Replace non-finite model metrics with JSON null."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def repaired_measurement(path: Path) -> tuple[dict[str, Any], list[str]]:
    text = path.read_text(encoding="utf-8")
    repairs = []
    fixed = text
    pattern = ']]"normalized_eigenvalues"'
    if pattern in fixed:
        fixed = fixed.replace(pattern, '],"normalized_eigenvalues"')
        repairs.append("double_close_before_normalized_eigenvalues")
    pattern = '"current_points": : ,'
    if pattern in fixed:
        fixed = fixed.replace(pattern, '"current_points": null,')
        repairs.append("missing_current_points_value")
    return json.loads(fixed), repairs


def discover_with_readonly_repair(
    directory: Path,
    scene_lookup: dict[int, str],
) -> tuple[builder.EpisodeSource, dict[str, Any], list[str]]:
    try:
        source, measurement = builder.discover_episode(
            directory, scene_lookup
        )
        source.split = "prospective"
        return source, measurement, []
    except builder.SkipEpisode:
        measurement_paths = sorted((directory / "measurements").glob("*.json"))
        if not measurement_paths:
            raise
        measurement, repairs = repaired_measurement(measurement_paths[0])
        round_trip = measurement.get("round_trip") or {}
        if round_trip.get("completed_phase") != "return":
            raise builder.SkipEpisode("measurement_not_completed_return")
        scene, physical, completion = builder.resolve_scene_and_completion(
            directory, scene_lookup
        )
        trajectory_path = builder.resolve_trajectory(
            directory, round_trip, completion
        )
        anchors_path = directory / "icp_replay_dataset" / "anchors.json"
        source = builder.EpisodeSource(
            directory=directory,
            episode_key=directory.name,
            physical_episode_id=physical,
            scene_id=scene,
            trajectory_path=trajectory_path,
            measurement_path=measurement_paths[0],
            anchors_path=anchors_path,
            trajectory_sha256=builder.sha256_file(trajectory_path),
            measurement_sha256=None,
            anchors_sha256=builder.sha256_file(anchors_path),
            split="prospective",
        )
        return source, measurement, repairs


def model_probabilities(
    rows: list[dict[str, Any]],
    state_type: Any,
    bundle: dict[str, Any],
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    states: dict[str, Any] = {}
    features = []
    usable = []
    for row in rows:
        if hint_builder.route_memory_provenance_is_oracle(row):
            continue
        key = row["episode"]["episode_key"]
        state = states.setdefault(key, state_type())
        features.append(state.transform(row))
        usable.append(row)
    if not usable:
        return np.empty((0, len(bundle["classes"]))), []
    matrix = bundle["vectorizer"].transform(features)
    order = [
        list(bundle["model"].classes_).index(label)
        for label in bundle["classes"]
    ]
    raw = bundle["model"].predict_proba(matrix)[:, order]
    return apply_temperature(raw, bundle["temperature"]), usable


def build_hint_rows(
    source: builder.EpisodeSource,
    terminal_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trajectory_rows, _sha = builder.load_trajectory(source.trajectory_path)
    query_by_step = {
        int(row["step"]): row for row in builder.query_rows(trajectory_rows)
    }
    anchors = {
        int(anchor["index"]): anchor
        for anchor in builder.load_anchors(source.anchors_path)
    }
    episode = {
        "_terminal_dataset_sha256": "prospective_reconstruction",
        "source": {
            "trajectory_sha256": source.trajectory_sha256,
            "anchors_sha256": source.anchors_sha256,
        },
    }
    result = []
    for terminal in terminal_rows:
        step = int(terminal["time"]["step"])
        trajectory = query_by_step.get(step)
        if trajectory is None:
            continue
        row, _status = hint_builder.build_row(
            episode, terminal, trajectory, anchors
        )
        if row is not None:
            result.append(row)
    return result


def score_hint(
    rows: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    probabilities, usable = model_probabilities(
        rows, HintActionCausalFeatureState, bundle
    )
    if not usable:
        return {"rows": 0}
    labels = np.asarray(
        [row["labels"]["decision"] for row in usable], dtype=object
    )
    weights = np.asarray(
        [float(row["labels"]["sample_weight"]) for row in usable],
        dtype=np.float64,
    )
    positive = weights > 0.0
    predicted = np.asarray(bundle["classes"])[
        np.argmax(probabilities, axis=1)
    ]
    metadata = [
        {
            "episode_key": row["episode"]["episode_key"],
            "scene_id": row["episode"]["scene_id"],
            "historical_override": bool(
                row["historical_policy"]["override"]
            ),
        }
        for row in usable
    ]
    threshold = bundle["decision_policy"]["precision_0p90"]["threshold"]
    override_index = bundle["classes"].index("override_hint")
    return {
        "rows": len(usable),
        "positive_weight_rows": int(positive.sum()),
        "three_class": evaluate(
            labels[positive],
            probabilities[positive],
            weights[positive],
            [item for item, keep in zip(metadata, positive) if keep],
            bundle["classes"],
        ),
        "historical_gate": historical_metrics(
            labels[positive],
            weights[positive],
            [item for item, keep in zip(metadata, positive) if keep],
        ),
        "model_validation_precision_0p90_threshold": intervention_metrics(
            labels[positive],
            probabilities[positive, override_index],
            weights[positive],
            threshold,
        ),
        "control_effect": "none",
    }


def score_terminal(
    rows: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    probabilities, usable = model_probabilities(
        rows, TerminalV2FeatureState, bundle
    )
    if not usable:
        return {"rows": 0}
    labels = np.asarray(
        [row["labels"]["terminal_class"] for row in usable], dtype=object
    )
    weights = np.asarray(
        [float(row["labels"]["sample_weight"]) for row in usable],
        dtype=np.float64,
    )
    positive = weights > 0.0
    metadata = [
        {
            "episode_key": row["episode"]["episode_key"],
            "scene_id": row["episode"]["scene_id"],
            "step": int(row["time"]["step"]),
        }
        for row in usable
    ]
    policy = bundle["decision_policy"]["arrived_sequence_confirmation"]
    arrived_index = bundle["classes"].index("arrived")
    return {
        "rows": len(usable),
        "positive_weight_rows": int(positive.sum()),
        "three_class": evaluate(
            labels[positive],
            probabilities[positive],
            weights[positive],
            [item for item, keep in zip(metadata, positive) if keep],
            bundle["classes"],
        ),
        "frozen_sequence_policy": sequence_metrics(
            labels[positive],
            probabilities[positive, arrived_index],
            weights[positive],
            [item for item, keep in zip(metadata, positive) if keep],
            policy["threshold"],
            policy["streak"],
        ),
        "control_effect": "none",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-root", default=str(DEFAULT_EVAL_ROOT))
    parser.add_argument(
        "--episodes", nargs="+", type=int, default=[319, 498, 295, 430, 1008]
    )
    parser.add_argument(
        "--hint-model",
        default=str(ROOT / "models" / "v1" / "hint_action_decision_v1.joblib"),
    )
    parser.add_argument(
        "--terminal-model",
        default=str(
            ROOT / "models" / "v2" / "terminal_decision_v2_robust.joblib"
        ),
    )
    parser.add_argument(
        "--output",
        default=str(
            ROOT / "reports" / "v2" / "prospective5_hint_terminal_v2.json"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    eval_root = Path(args.eval_root).resolve()
    scene_lookup = builder.load_scene_lookup(builder.DEFAULT_EPISODE_DATASET)
    hint_bundle = joblib.load(Path(args.hint_model))
    terminal_bundle = joblib.load(Path(args.terminal_model))
    results = []
    for episode in args.episodes:
        directory = eval_root / f"{RUN_PREFIX}{episode}"
        record: dict[str, Any] = {
            "physical_episode_id": episode,
            "result_dir": str(directory),
        }
        try:
            source, measurement, repairs = discover_with_readonly_repair(
                directory, scene_lookup
            )
            _anchor_rows, terminal_rows, episode_record = (
                builder.build_episode_rows(source, measurement)
            )
            hint_rows = build_hint_rows(source, terminal_rows)
            record.update(
                {
                    "scoreable": True,
                    "scene_id": source.scene_id,
                    "readonly_measurement_repairs": repairs,
                    "source_episode": episode_record,
                    "hint_action": score_hint(hint_rows, hint_bundle),
                    "terminal_v2_robust": score_terminal(
                        terminal_rows, terminal_bundle
                    ),
                    "control_effect": "none",
                }
            )
        except Exception as exc:
            record.update(
                {
                    "scoreable": False,
                    "error": f"{type(exc).__name__}:{exc}",
                    "control_effect": "none",
                }
            )
        results.append(record)
        print(json.dumps(json_safe(record), indent=2, sort_keys=True), flush=True)
    output = {
        "schema": SCHEMA,
        "hint_model": str(Path(args.hint_model).resolve()),
        "terminal_model": str(Path(args.terminal_model).resolve()),
        "episodes": results,
    }
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            json_safe(output),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
