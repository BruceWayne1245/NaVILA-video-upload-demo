import json
import pickle

import numpy as np
import pytest

from reliability.v11_portable import export_v11_portable
from reliability.v11_runtime import (
    V11DecisionShadowPolicy,
    V11ShadowJsonlSession,
)
from reliability.v11_training import load_v11_npz
from reliability_v11_portable_runtime import PortableV11Bundle


def test_v11_portable_is_shadow_locked(tmp_path):
    output = tmp_path / "portable.json"
    export_v11_portable(
        "artifacts/reliability_v1_1_development.pkl", output
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="enforcement is intentionally locked"):
        PortableV11Bundle(payload, mode="enforce")


def test_v11_portable_matches_sklearn_sample(tmp_path):
    output = tmp_path / "portable.json"
    export_v11_portable(
        "artifacts/reliability_v1_1_development.pkl", output
    )
    portable = PortableV11Bundle.load(str(output))
    data = load_v11_npz(
        "experiments/2026-07-23-prospective-results/prospective_v1_1.npz"
    )
    with open("artifacts/reliability_v1_1_development.pkl", "rb") as handle:
        artifact = pickle.load(handle)
    indices = np.linspace(0, len(data["features"]) - 1, 256, dtype=int)
    field_by_head = {
        "bearing": "p_bearing_bad_30",
        "distance": "p_distance_bad_0p5",
        "pose": "p_pose_bad",
    }
    portable_results = [
        portable.predict_vector(data["features"][index].tolist())
        for index in indices
    ]
    for head, field in field_by_head.items():
        values = artifact["heads"][head]
        selected = np.asarray(values["feature_indices"], dtype=int)
        raw = values["model"].predict_proba(
            data["features"][indices][:, selected]
        )[:, 1]
        expected = values["calibrator"].predict(raw)
        actual = np.asarray(
            [getattr(result, field) for result in portable_results]
        )
        assert np.max(np.abs(expected - actual)) <= 1e-12
        assert np.array_equal(
            expected <= float(values["trusted_threshold"]),
            np.asarray([
                getattr(result, f"{head}_trusted")
                for result in portable_results
            ]),
        )


def test_v11_live_shadow_jsonl_is_fail_open_and_logs_features(tmp_path):
    bundle = PortableV11Bundle.load(
        "artifacts/reliability_v1_1_portable_shadow.json"
    )
    log_path = tmp_path / "shadow.jsonl"
    session = V11ShadowJsonlSession(
        bundle,
        episode_key="canary::ep1",
        log_path=log_path,
    )
    records = [
        {
            "attempt": 1,
            "anchor_index": 4,
            "confidence": 0.9,
            "overlap_ratio": 0.8,
            "median_residual_m": 0.1,
            "icp_top_basins": [],
        },
        {
            "attempt": 1,
            "anchor_index": 3,
            "confidence": 0.8,
            "overlap_ratio": 0.7,
            "median_residual_m": 0.2,
            "icp_top_basins": [],
        },
    ]
    outputs = session.score_records(records, step=101)
    assert len(outputs) == 2
    assert all(len(output["features"]) == 249 for output in outputs)
    assert all(output["enforced"] is False for output in outputs)
    # A malformed shadow call must not escape into the navigation controller.
    assert session.score_records([], step=102) == []
    session.record_controller_snapshot(
        step=101,
        attempt=1,
        accepted_event={"accepted": True},
        target_anchor_index=4,
    )
    summary = session.summary()
    assert summary["calls"] == 1
    assert summary["candidates"] == 2
    assert summary["shadow_exceptions"] == 1
    assert summary["enforcement_enabled"] is False
    session.close()

    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == [
        "v11_shadow_session_start",
        "v11_shadow_score",
        "v11_shadow_exception",
        "v11_shadow_controller_snapshot",
        "v11_shadow_session_end",
    ]
    assert events[1]["controller_effect"] is False
    assert events[1]["outputs"][0]["features"]["yaw_score_entropy"] is None


def test_v11_decision_shadow_defers_untrusted_selected_without_identity_override():
    policy = V11DecisionShadowPolicy.load(
        "configs/v11_decision_shadow_v1.json"
    )
    accepted_event = {
        "accepted": True,
        "anchor_index": 16,
        "target_anchor_index": 16,
    }
    original_event = dict(accepted_event)
    outputs = [
        {
            "anchor_index": 16,
            "anchor_role": "current",
            "p_bearing_bad_30": 0.82,
            "p_distance_bad_0p5": 0.01,
            "p_pose_bad": 0.84,
            "bearing_trusted": False,
            "distance_trusted": True,
            "pose_trusted": False,
            "jointly_trusted": False,
        },
        {
            "anchor_index": 15,
            "anchor_role": "next",
            "p_bearing_bad_30": 0.01,
            "p_distance_bad_0p5": 0.01,
            "p_pose_bad": 0.01,
            "bearing_trusted": True,
            "distance_trusted": True,
            "pose_trusted": True,
            "jointly_trusted": True,
        },
    ]

    decision = policy.evaluate(
        outputs,
        accepted_event=accepted_event,
        target_anchor_index=16,
    )

    assert accepted_event == original_event
    assert (
        decision["counterfactual"]["action"]
        == "would_defer_entire_relocalization_update_current_untrusted"
    )
    assert decision["counterfactual"]["forwarded_anchor_indices"] == []
    assert (
        decision["counterfactual"]["selected_assessment_action"]
        == "selected_candidate_untrusted"
    )
    assert decision["counterfactual"]["advisory_alternate_anchor_index"] == 15
    assert decision["counterfactual"]["alternate_is_advisory_only"] is True
    assert decision["counterfactual"]["identity_override_authorized"] is False
    assert decision["controller_effect"] is False
    assert decision["activation_approved"] is False

    policy.attach_posthoc_ground_truth(
        decision,
        [
            {
                "anchor_index": 16,
                "estimated_bearing_to_anchor_deg": 100.0,
                "estimated_distance_to_anchor_m": 2.0,
            },
            {
                "anchor_index": 15,
                "estimated_bearing_to_anchor_deg": 5.0,
                "estimated_distance_to_anchor_m": 1.0,
            },
        ],
        {
            16: {
                "true_bearing_to_anchor_deg": -100.0,
                "true_distance_to_anchor_m": 1.0,
            },
            15: {
                "true_bearing_to_anchor_deg": 0.0,
                "true_distance_to_anchor_m": 1.0,
            },
        },
    )
    truth = decision["posthoc_ground_truth"]
    assert truth["used_for_decision"] is False
    assert truth["available_rows"] == 2
    assert truth["candidate_labels"][0]["label_pose_bad"] == 1
    assert truth["candidate_labels"][1]["label_pose_bad"] == 0


def test_v11_decision_shadow_jsonl_is_separate_from_controller_snapshot(tmp_path):
    bundle = PortableV11Bundle.load(
        "artifacts/reliability_v1_1_portable_shadow.json"
    )
    policy = V11DecisionShadowPolicy.load(
        "configs/v11_decision_shadow_v1.json"
    )
    log_path = tmp_path / "decision-shadow.jsonl"
    session = V11ShadowJsonlSession(
        bundle,
        episode_key="decision-canary::ep1",
        log_path=log_path,
        decision_policy=policy,
        physical_episode_id=1,
        scene_id="test-scene",
    )
    outputs = session.score_records(
        [
            {
                "attempt": 1,
                "anchor_index": 4,
                "confidence": 0.9,
                "overlap_ratio": 0.8,
                "median_residual_m": 0.1,
                "icp_top_basins": [],
            },
            {
                "attempt": 1,
                "anchor_index": 3,
                "confidence": 0.8,
                "overlap_ratio": 0.7,
                "median_residual_m": 0.2,
                "icp_top_basins": [],
            },
        ],
        step=101,
    )
    controller_event = {"accepted": True, "anchor_index": 4}
    assert session.record_controller_snapshot(
        step=101,
        attempt=1,
        accepted_event=controller_event,
        target_anchor_index=4,
    ) is None
    assert controller_event == {"accepted": True, "anchor_index": 4}
    assert len(outputs) == 2
    summary = session.summary()
    assert summary["decision_shadow_enabled"] is True
    assert summary["decision_count"] == 1
    assert summary["decision_exceptions"] == 0
    session.close()

    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == [
        "v11_shadow_session_start",
        "v11_shadow_score",
        "v11_shadow_controller_snapshot",
        "v11_shadow_decision",
        "v11_shadow_session_end",
    ]
    decision = events[3]
    assert decision["observation_only"] is True
    assert decision["activation_approved"] is False
    assert decision["enforcement_enabled"] is False
    assert decision["controller_effect"] is False
    assert decision["physical_episode_id"] == 1
    assert decision["scene_id"] == "test-scene"
    assert (
        decision["counterfactual"]["identity_override_authorized"] is False
    )


def test_v11_decision_policy_rejects_enforcement_approval():
    payload = dict(
        V11DecisionShadowPolicy.load(
            "configs/v11_decision_shadow_v1.json"
        ).payload
    )
    payload["enforcement_approved"] = True
    with pytest.raises(ValueError, match="forbid enforcement"):
        V11DecisionShadowPolicy(payload)


def test_v11_role_safe_policy_never_forwards_untrusted_next():
    policy = V11DecisionShadowPolicy.load(
        "configs/v11_decision_shadow_v1.json"
    )
    trusted = {
        "p_bearing_bad_30": 0.01,
        "p_distance_bad_0p5": 0.01,
        "p_pose_bad": 0.01,
        "bearing_trusted": True,
        "distance_trusted": True,
        "pose_trusted": True,
        "jointly_trusted": True,
    }
    untrusted = {
        "p_bearing_bad_30": 0.9,
        "p_distance_bad_0p5": 0.9,
        "p_pose_bad": 0.9,
        "bearing_trusted": False,
        "distance_trusted": False,
        "pose_trusted": False,
        "jointly_trusted": False,
    }
    decision = policy.evaluate(
        [
            {
                "anchor_index": 4,
                "anchor_role": "current",
                **trusted,
            },
            {
                "anchor_index": 3,
                "anchor_role": "next",
                **untrusted,
            },
        ],
        accepted_event={"accepted": True, "anchor_index": 4},
        target_anchor_index=4,
    )
    assert (
        decision["counterfactual"]["action"]
        == "would_forward_trusted_current_only"
    )
    assert decision["counterfactual"]["forwarded_anchor_indices"] == [4]


def test_v11_posthoc_truth_wraps_bearing_without_leaking_into_decision():
    policy = V11DecisionShadowPolicy.load(
        "configs/v11_decision_shadow_v1.json"
    )
    decision = {"counterfactual": {"action": "unchanged"}}
    policy.attach_posthoc_ground_truth(
        decision,
        [{
            "anchor_index": 4,
            "estimated_bearing_to_anchor_deg": 170.0,
            "estimated_distance_to_anchor_m": 1.0,
        }],
        {4: {
            "true_bearing_to_anchor_deg": -170.0,
            "true_distance_to_anchor_m": 1.0,
        }},
    )
    row = decision["posthoc_ground_truth"]["candidate_labels"][0]
    assert row["bearing_error_deg"] == pytest.approx(20.0)
    assert row["label_bearing_bad"] == 0
    assert decision["counterfactual"]["action"] == "unchanged"
