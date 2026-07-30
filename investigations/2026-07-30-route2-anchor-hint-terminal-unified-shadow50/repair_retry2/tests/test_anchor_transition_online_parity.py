from __future__ import annotations

import pathlib
import sys

import joblib
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAINING_ROOT = pathlib.Path(
    "/home/teambruce/navila-anchor-terminal-training-data-20260729"
)
sys.path[:0] = [
    str(ROOT),
    str(TRAINING_ROOT / "runtime_shadow"),
    str(TRAINING_ROOT / "tools"),
    str(TRAINING_ROOT / "training"),
]

import build_training_datasets as builder  # noqa: E402
import score_episode  # noqa: E402
from anchor_transition_runtime import (  # noqa: E402
    OnlineAnchorTransitionV1,
    build_runtime_anchor_row,
)


MODEL = TRAINING_ROOT / "models/v1/anchor_transition_v1.joblib"
MODEL_SHA = "4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55"
EP189 = pathlib.Path(
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/"
    "round_trip_phase_prompt_go2_matterport_vision_loco_"
    "2024-09-25_23-22-02_three_model_readonly_shadow30_20260729_ep189"
)


def runtime_only(row):
    return {
        "schema": row["schema"],
        "task": row["task"],
        "episode": {
            key: row["episode"][key]
            for key in (
                "episode_key",
                "physical_episode_id",
                "scene_id",
                "split",
            )
        },
        "time": dict(row["time"]),
        "inputs": row["inputs"],
    }


def test_online_wrapper_matches_frozen_postepisode_scorer_exactly():
    lookup = builder.load_scene_lookup(builder.DEFAULT_EPISODE_DATASET)
    source, measurement = builder.discover_episode(EP189, lookup)
    rows, _terminal, _episode = builder.build_episode_rows(
        source, measurement
    )
    bundle = joblib.load(MODEL)
    records, _metrics = score_episode.predict_rows(
        "anchor_state", rows, bundle
    )
    adapter = OnlineAnchorTransitionV1(
        model_path=MODEL,
        feature_module_root=TRAINING_ROOT / "training",
        expected_model_sha256=MODEL_SHA,
    )
    online = [
        adapter.observe_complete_attempt(runtime_only(row)) for row in rows
    ]
    assert [item.action for item in online] == [
        item["prediction"]["class"] for item in records
    ]
    expected = np.asarray(
        [
            [
                item["prediction"]["probabilities"][label]
                for label in bundle["classes"]
            ]
            for item in records
        ]
    )
    actual = np.asarray(
        [
            [item.probabilities[label] for label in bundle["classes"]]
            for item in online
        ]
    )
    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)


def test_online_wrapper_rejects_postepisode_supervision_fields():
    lookup = builder.load_scene_lookup(builder.DEFAULT_EPISODE_DATASET)
    source, measurement = builder.discover_episode(EP189, lookup)
    rows, _terminal, _episode = builder.build_episode_rows(
        source, measurement
    )
    adapter = OnlineAnchorTransitionV1(
        model_path=MODEL,
        feature_module_root=TRAINING_ROOT / "training",
        expected_model_sha256=MODEL_SHA,
    )
    try:
        adapter.observe_complete_attempt(rows[0])
    except ValueError as exc:
        assert "non-runtime fields" in str(exc)
    else:
        raise AssertionError("supervision-bearing row was accepted")


def test_runtime_row_builder_matches_frozen_dataset_inputs():
    lookup = builder.load_scene_lookup(builder.DEFAULT_EPISODE_DATASET)
    source, measurement = builder.discover_episode(EP189, lookup)
    rows, _terminal, _episode = builder.build_episode_rows(
        source, measurement
    )
    round_trip = measurement["round_trip"]
    grouped = builder.group_covisibility(round_trip)
    v11 = builder.load_v11_attempts(source.directory)
    support = builder.support_events_by_attempt(round_trip)
    for expected in rows:
        attempt = int(expected["time"]["attempt"])
        actual = build_runtime_anchor_row(
            episode_key=expected["episode"]["episode_key"],
            physical_episode_id=expected["episode"]["physical_episode_id"],
            scene_id=expected["episode"]["scene_id"],
            attempt=attempt,
            step=expected["time"]["step"],
            movement=expected["inputs"]["movement"],
            route_memory=expected["inputs"]["route_memory"],
            support=support.get(attempt),
            raw_candidates=grouped[attempt],
            v11_outputs=(v11.get(attempt) or {}).get("outputs") or [],
        )
        assert actual["inputs"] == expected["inputs"]
