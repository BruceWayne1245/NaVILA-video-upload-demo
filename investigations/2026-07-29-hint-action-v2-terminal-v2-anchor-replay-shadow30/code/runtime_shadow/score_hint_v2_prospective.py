#!/usr/bin/env python3
"""Read-only prospective scoring for the robust Hint v2 bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime_shadow"))
sys.path.insert(0, str(ROOT / "training"))

import score_hint_terminal_v2_prospective as base  # noqa: E402
from hint_action_v2_features import (  # noqa: E402
    HintActionV2FeatureState,
    clearance_metadata,
)
from train_hint_action_model import historical_metrics  # noqa: E402
from train_hint_action_v2_robust import policy_metrics  # noqa: E402
from train_models import apply_temperature, evaluate  # noqa: E402


SCHEMA = "navila-hint-v2-prospective-replay"


def score_rows(
    rows: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    states: dict[str, HintActionV2FeatureState] = {}
    features = []
    usable = []
    metadata = []
    for row in rows:
        if base.hint_builder.route_memory_provenance_is_oracle(row):
            continue
        key = row["episode"]["episode_key"]
        state = states.setdefault(key, HintActionV2FeatureState())
        feature = state.transform(row)
        clearance = clearance_metadata(row)
        features.append(feature)
        usable.append(row)
        metadata.append(
            {
                "episode_key": key,
                "scene_id": row["episode"]["scene_id"],
                "step": int(row["time"]["step"]),
                "historical_override": bool(
                    row["historical_policy"]["override"]
                ),
                "clearance_available": clearance["available"],
                "clearance_clear": clearance["clear"],
                "same_kind_streak": int(
                    feature["temporal.proposal.same_kind_streak"]
                ),
                "same_target_streak": int(
                    feature["temporal.proposal.same_target_streak"]
                ),
            }
        )
    if not usable:
        return {"rows": 0}
    matrix = bundle["vectorizer"].transform(features)
    order = [
        list(bundle["model"].classes_).index(label)
        for label in bundle["classes"]
    ]
    probabilities = apply_temperature(
        bundle["model"].predict_proba(matrix)[:, order],
        bundle["temperature"],
    )
    labels = np.asarray(
        [row["labels"]["decision"] for row in usable], dtype=object
    )
    if bundle.get("task") == "hint_action_binary":
        labels = np.asarray(
            [
                "override_hint"
                if label == "override_hint"
                else "do_not_override"
                for label in labels
            ],
            dtype=object,
        )
    weights = np.asarray(
        [float(row["labels"]["sample_weight"]) for row in usable],
        dtype=np.float64,
    )
    positive_weight = weights > 0.0
    labels = labels[positive_weight]
    weights = weights[positive_weight]
    probabilities = probabilities[positive_weight]
    metadata = [
        item for item, keep in zip(metadata, positive_weight) if keep
    ]
    execution = bundle["decision_policy"]["execution"]
    advisory = bundle["decision_policy"]["advisory"]
    override_index = bundle["classes"].index("override_hint")
    policy_args = (
        execution["threshold"],
        execution["same_kind_streak"],
        execution["same_target_streak"],
    )
    return {
        "rows": len(usable),
        "positive_weight_rows": int(positive_weight.sum()),
        "three_class": evaluate(
            labels,
            probabilities,
            weights,
            metadata,
            bundle["classes"],
        ),
        "historical_gate": historical_metrics(
            labels, weights, metadata
        ),
        "threshold_only_route_recommendation": policy_metrics(
            labels,
            probabilities[:, override_index],
            weights,
            metadata,
            execution["threshold"],
            1,
            1,
            False,
        ),
        "frozen_advisory_route_recommendation": policy_metrics(
            labels,
            probabilities[:, override_index],
            weights,
            metadata,
            advisory["threshold"],
            advisory["same_kind_streak"],
            advisory["same_target_streak"],
            False,
        ),
        "frozen_advisory_clearance_gated": policy_metrics(
            labels,
            probabilities[:, override_index],
            weights,
            metadata,
            advisory["threshold"],
            advisory["same_kind_streak"],
            advisory["same_target_streak"],
            True,
        ),
        "frozen_route_recommendation": policy_metrics(
            labels,
            probabilities[:, override_index],
            weights,
            metadata,
            *policy_args,
            False,
        ),
        "frozen_executable_policy": policy_metrics(
            labels,
            probabilities[:, override_index],
            weights,
            metadata,
            *policy_args,
            True,
        ),
        "control_effect": "none",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-root", default=str(base.DEFAULT_EVAL_ROOT))
    parser.add_argument(
        "--episodes", nargs="+", type=int, default=[319, 498, 295, 430, 1008]
    )
    parser.add_argument(
        "--model",
        default=str(
            ROOT / "models" / "v2"
            / "hint_action_decision_v2_robust.joblib"
        ),
    )
    parser.add_argument(
        "--output",
        default=str(
            ROOT / "reports" / "v2"
            / "prospective5_hint_v2_robust.json"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    eval_root = Path(args.eval_root).resolve()
    scene_lookup = base.builder.load_scene_lookup(
        base.builder.DEFAULT_EPISODE_DATASET
    )
    bundle = joblib.load(Path(args.model))
    results = []
    pooled_rows = []
    for episode in args.episodes:
        directory = eval_root / f"{base.RUN_PREFIX}{episode}"
        record: dict[str, Any] = {
            "physical_episode_id": episode,
            "result_dir": str(directory),
        }
        try:
            source, measurement, repairs = (
                base.discover_with_readonly_repair(
                    directory, scene_lookup
                )
            )
            _anchor_rows, terminal_rows, episode_record = (
                base.builder.build_episode_rows(source, measurement)
            )
            hint_rows = base.build_hint_rows(source, terminal_rows)
            pooled_rows.extend(hint_rows)
            record.update(
                {
                    "scoreable": True,
                    "scene_id": source.scene_id,
                    "readonly_measurement_repairs": repairs,
                    "source_episode": episode_record,
                    "hint_action_v2": score_rows(hint_rows, bundle),
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
        print(
            json.dumps(base.json_safe(record), indent=2, sort_keys=True),
            flush=True,
        )
    output = {
        "schema": SCHEMA,
        "model": str(Path(args.model).resolve()),
        "episodes": results,
        "pooled_scoreable": score_rows(pooled_rows, bundle),
        "control_effect": "none",
    }
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            base.json_safe(output),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
