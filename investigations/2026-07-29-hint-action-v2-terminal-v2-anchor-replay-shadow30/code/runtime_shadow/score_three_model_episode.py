#!/usr/bin/env python3
"""Score one saved episode with frozen Anchor, Terminal, and Hint models.

The evaluator never imports this module.  Scoring starts only after the
episode process exits and writes counterfactual diagnostics with no control
authority.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

import joblib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime_shadow"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "training"))

import build_training_datasets as builder  # noqa: E402
import score_episode as anchor_scorer  # noqa: E402
import score_hint_terminal_v2_prospective as prospective  # noqa: E402
import score_hint_v2_prospective as hint_v2_scorer  # noqa: E402


SCHEMA = "navila-three-model-readonly-shadow-v1"
OUTPUT_NAME = "three_model_readonly_shadow_summary.json"


def training_episode_ids(path: Path) -> set[int]:
    result = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                result.add(int(json.loads(line)["physical_episode_id"]))
    return result


def sha256_file(path: Path) -> str:
    return prospective.builder.sha256_file(path)


def clearance_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: collections.Counter[str] = collections.Counter()
    weights: collections.Counter[str] = collections.Counter()
    for row in rows:
        weight = float(row["labels"].get("sample_weight") or 0.0)
        if weight <= 0.0:
            continue
        clearance = hint_v2_scorer.clearance_metadata(row)
        if clearance["available"] and clearance["clear"] is True:
            state = "clear"
        elif clearance["available"] and clearance["clear"] is False:
            state = "occupied"
        else:
            state = "unavailable"
        counts[state] += 1
        weights[state] += weight
    return {
        "rows": dict(sorted(counts.items())),
        "weighted_rows": {
            key: float(value)
            for key, value in sorted(weights.items())
        },
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument(
        "--training-episodes",
        type=Path,
        default=ROOT / "data" / "v1" / "episodes.jsonl",
    )
    parser.add_argument(
        "--anchor-model",
        type=Path,
        default=ROOT / "models" / "v1" / "anchor_transition_v1.joblib",
    )
    parser.add_argument(
        "--terminal-model",
        type=Path,
        default=ROOT / "models" / "v2"
        / "terminal_decision_v2_robust.joblib",
    )
    parser.add_argument(
        "--hint-v1-model",
        type=Path,
        default=ROOT / "models" / "v1"
        / "hint_action_decision_v1.joblib",
    )
    parser.add_argument(
        "--hint-v2-model",
        type=Path,
        default=ROOT / "models" / "v2"
        / "hint_action_decision_v2_binary.joblib",
    )
    parser.add_argument(
        "--episode-dataset",
        type=Path,
        default=builder.DEFAULT_EPISODE_DATASET,
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_dir = args.result_dir.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else result_dir / OUTPUT_NAME
    )
    base_summary: dict[str, Any] = {
        "schema": SCHEMA,
        "result_dir": str(result_dir),
        "control_effect": "none",
        "scoreable": False,
        "models": {
            "anchor_v1": {
                "path": str(args.anchor_model.resolve()),
                "sha256": sha256_file(args.anchor_model),
            },
            "terminal_v2_robust": {
                "path": str(args.terminal_model.resolve()),
                "sha256": sha256_file(args.terminal_model),
            },
            "hint_v1": {
                "path": str(args.hint_v1_model.resolve()),
                "sha256": sha256_file(args.hint_v1_model),
            },
            "hint_v2_binary": {
                "path": str(args.hint_v2_model.resolve()),
                "sha256": sha256_file(args.hint_v2_model),
            },
        },
    }
    try:
        scene_lookup = builder.load_scene_lookup(args.episode_dataset)
        source, measurement = builder.discover_episode(
            result_dir, scene_lookup
        )
        if source.physical_episode_id in training_episode_ids(
            args.training_episodes
        ):
            raise RuntimeError(
                f"episode {source.physical_episode_id} overlaps training corpus"
            )
        anchor_rows, terminal_rows, episode_record = (
            builder.build_episode_rows(source, measurement)
        )
        hint_rows = prospective.build_hint_rows(source, terminal_rows)
        anchor_bundle = joblib.load(args.anchor_model)
        terminal_bundle = joblib.load(args.terminal_model)
        hint_v1_bundle = joblib.load(args.hint_v1_model)
        hint_v2_bundle = joblib.load(args.hint_v2_model)
        _anchor_records, anchor_metrics = anchor_scorer.predict_rows(
            "anchor_state", anchor_rows, anchor_bundle
        )
        base_summary.update(
            {
                "scoreable": True,
                "episode": {
                    "episode_key": source.episode_key,
                    "physical_episode_id": source.physical_episode_id,
                    "scene_id": source.scene_id,
                    "prospective_not_in_training_corpus": True,
                },
                "source_episode": episode_record,
                "tasks": {
                    "anchor_v1": anchor_metrics,
                    "terminal_v2_robust": prospective.score_terminal(
                        terminal_rows, terminal_bundle
                    ),
                    "hint_v1": prospective.score_hint(
                        hint_rows, hint_v1_bundle
                    ),
                    "hint_v2_binary": hint_v2_scorer.score_rows(
                        hint_rows, hint_v2_bundle
                    ),
                },
                "hint_clearance": clearance_distribution(hint_rows),
            }
        )
    except Exception as exc:
        base_summary["error"] = f"{type(exc).__name__}:{exc}"
    write_summary(output, base_summary)
    print(
        json.dumps(
            prospective.json_safe(base_summary),
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if base_summary["scoreable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
