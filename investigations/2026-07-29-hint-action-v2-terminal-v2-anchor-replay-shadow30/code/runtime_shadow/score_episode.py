#!/usr/bin/env python3
"""Score one completed episode with the learned controllers, without control effects."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, f1_score


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "training"))

import build_training_datasets as builder  # noqa: E402
import train_models  # noqa: E402
from model_features import CausalFeatureState, assert_runtime_only  # noqa: E402


OUTPUT_SCHEMA = "navila-learned-controller-replay-shadow-v1"


def compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def training_episode_ids(path: Path) -> set[int]:
    result = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                result.add(int(json.loads(line)["physical_episode_id"]))
    return result


def route_source_is_oracle(row: dict[str, Any]) -> bool:
    memory = row["inputs"].get("route_memory") or {}
    provenance = " ".join(
        str(memory.get(field) or "").lower()
        for field in ("source", "configured_source", "relocalization_backend")
    )
    return "oracle" in provenance or "isaac" in provenance


def predict_rows(
    task: str,
    rows: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_task = (
        "anchor_transition" if task == "anchor_state" else "terminal_decision"
    )
    if bundle.get("task") != expected_task:
        raise RuntimeError(
            f"bundle task mismatch: expected={expected_task} actual={bundle.get('task')}"
        )
    state = CausalFeatureState()
    usable_rows = []
    features = []
    skipped_oracle = 0
    for row in rows:
        if route_source_is_oracle(row):
            skipped_oracle += 1
            continue
        feature = state.transform(row)
        assert_runtime_only(feature)
        features.append(feature)
        usable_rows.append(row)
    if not usable_rows:
        return [], {
            "rows": 0,
            "skipped_oracle_source_rows": skipped_oracle,
        }

    matrix = bundle["vectorizer"].transform(features)
    model_order = [
        list(bundle["model"].classes_).index(label)
        for label in bundle["classes"]
    ]
    raw = bundle["model"].predict_proba(matrix)[:, model_order]
    probabilities = train_models.apply_temperature(raw, bundle["temperature"])
    predicted = np.asarray(bundle["classes"])[np.argmax(probabilities, axis=1)]
    label_field = (
        "transition_action" if task == "anchor_state" else "terminal_class"
    )
    labels = np.asarray(
        [row["labels"][label_field] for row in usable_rows], dtype=object
    )
    weights = np.asarray(
        [float(row["labels"]["sample_weight"]) for row in usable_rows],
        dtype=np.float64,
    )
    positive = weights > 0

    records = []
    for row, probability, prediction in zip(
        usable_rows, probabilities, predicted
    ):
        record = {
            "schema": OUTPUT_SCHEMA,
            "task": expected_task,
            "episode": row["episode"],
            "time": row["time"],
            "prediction": {
                "class": str(prediction),
                "probabilities": {
                    label: float(value)
                    for label, value in zip(bundle["classes"], probability)
                },
                "temperature": float(bundle["temperature"]),
            },
            "oracle_evaluation": {
                "class": row["labels"][label_field],
                "sample_weight": float(row["labels"]["sample_weight"]),
                "route_distance_to_a0_m": row["labels"].get(
                    "oracle_route_distance_to_a0_m"
                ),
                "next_anchor_index": row["labels"].get(
                    "oracle_next_anchor_index"
                ),
                "alignment_quality": (
                    row.get("oracle_alignment") or {}
                ).get("quality"),
            },
            "historical_policy": row.get("historical_policy"),
            "control_effect": "none",
        }
        if task == "terminal_decision":
            arrived_threshold = bundle["decision_policy"][
                "arrived_zero_false_positive"
            ]["threshold"]
            arrived_score = record["prediction"]["probabilities"]["arrived"]
            record["prediction"]["diagnostic_arrived_threshold_pass"] = bool(
                arrived_score >= arrived_threshold
            )
            record["prediction"]["diagnostic_threshold_control_authority"] = False
        records.append(record)

    if not np.any(positive):
        metrics = {
            "rows": len(usable_rows),
            "positive_weight_rows": 0,
            "skipped_oracle_source_rows": skipped_oracle,
        }
    else:
        y_true = labels[positive]
        y_pred = predicted[positive]
        y_weight = weights[positive]
        metrics = {
            "rows": len(usable_rows),
            "positive_weight_rows": int(positive.sum()),
            "skipped_oracle_source_rows": skipped_oracle,
            "balanced_accuracy": float(
                balanced_accuracy_score(
                    y_true, y_pred, sample_weight=y_weight
                )
            ),
            "macro_f1": float(
                f1_score(
                    y_true,
                    y_pred,
                    labels=bundle["classes"],
                    average="macro",
                    sample_weight=y_weight,
                    zero_division=0,
                )
            ),
            "confusion_matrix": confusion_matrix(
                y_true,
                y_pred,
                labels=bundle["classes"],
                sample_weight=y_weight,
            ).tolist(),
        }
        if task == "terminal_decision":
            arrived_index = bundle["classes"].index("arrived")
            threshold = bundle["decision_policy"][
                "arrived_zero_false_positive"
            ]["threshold"]
            threshold_pass = probabilities[:, arrived_index] >= threshold
            metrics["diagnostic_arrived_threshold"] = float(threshold)
            metrics["diagnostic_arrived_false_positives"] = int(
                np.sum(threshold_pass & (labels != "arrived") & positive)
            )
            metrics["diagnostic_arrived_true_positives"] = int(
                np.sum(threshold_pass & (labels == "arrived") & positive)
            )
            metrics["diagnostic_threshold_control_authority"] = False
    return records, metrics


def write_atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(compact_json(row))
            handle.write("\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument(
        "--model-dir", type=Path, default=ROOT / "models" / "v1"
    )
    parser.add_argument(
        "--training-episodes",
        type=Path,
        default=ROOT / "data" / "v1" / "episodes.jsonl",
    )
    parser.add_argument(
        "--episode-dataset",
        type=Path,
        default=builder.DEFAULT_EPISODE_DATASET,
    )
    parser.add_argument(
        "--allow-training-overlap",
        action="store_true",
        help="Testing only: permit scoring an episode already present in training.",
    )
    args = parser.parse_args()
    result_dir = args.result_dir.resolve()
    scene_lookup = builder.load_scene_lookup(args.episode_dataset)
    source, measurement = builder.discover_episode(result_dir, scene_lookup)
    seen_training = source.physical_episode_id in training_episode_ids(
        args.training_episodes
    )
    if seen_training and not args.allow_training_overlap:
        raise RuntimeError(
            f"episode {source.physical_episode_id} appears in the training corpus"
        )
    anchor_rows, terminal_rows, episode_record = builder.build_episode_rows(
        source, measurement
    )
    anchor_bundle = joblib.load(
        args.model_dir / "anchor_transition_v1.joblib"
    )
    terminal_bundle = joblib.load(
        args.model_dir / "terminal_decision_v1.joblib"
    )
    anchor_predictions, anchor_metrics = predict_rows(
        "anchor_state", anchor_rows, anchor_bundle
    )
    terminal_predictions, terminal_metrics = predict_rows(
        "terminal_decision", terminal_rows, terminal_bundle
    )
    predictions = anchor_predictions + terminal_predictions
    summary = {
        "schema": OUTPUT_SCHEMA,
        "episode": {
            "episode_key": source.episode_key,
            "physical_episode_id": source.physical_episode_id,
            "scene_id": source.scene_id,
            "prospective_not_in_training_corpus": not seen_training,
        },
        "control_effect": "none",
        "model_artifacts": {
            "anchor_transition": str(
                (args.model_dir / "anchor_transition_v1.joblib").resolve()
            ),
            "terminal_decision": str(
                (args.model_dir / "terminal_decision_v1.joblib").resolve()
            ),
        },
        "source_episode": episode_record,
        "tasks": {
            "anchor_transition": anchor_metrics,
            "terminal_decision": terminal_metrics,
        },
    }
    write_atomic_jsonl(
        result_dir / "learned_controller_replay_shadow_v1.jsonl",
        predictions,
    )
    write_atomic_json(
        result_dir / "learned_controller_replay_shadow_v1_summary.json",
        summary,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
