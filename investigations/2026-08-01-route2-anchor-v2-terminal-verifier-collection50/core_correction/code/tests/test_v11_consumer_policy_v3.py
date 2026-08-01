import copy
import json
from pathlib import Path

import pytest

from reliability.v11_consumer_policy_v3 import (
    OPERATION_HEAD,
    V11ConsumerGuardV3,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "v11_consumer_policy_v3_core_active.json"


def output(
    anchor=4,
    *,
    bearing=False,
    distance=False,
    pose=False,
):
    return {
        "anchor_index": anchor,
        "anchor_role": "next",
        "p_bearing_bad_30": 0.01 if bearing else 0.99,
        "p_distance_bad_0p5": 0.01 if distance else 0.99,
        "p_pose_bad": 0.01 if pose else 0.99,
        "bearing_trusted": bearing,
        "distance_trusted": distance,
        "pose_trusted": pose,
        "jointly_trusted": bearing and distance and pose,
    }


def guard():
    value = V11ConsumerGuardV3.load(POLICY, mode="active")
    value.start_episode("ep")
    return value


@pytest.mark.parametrize(
    ("operation", "trusted_head"),
    sorted(OPERATION_HEAD.items()),
)
def test_each_consumer_uses_only_its_declared_head(operation, trusted_head):
    flags = {"bearing": False, "distance": False, "pose": False}
    flags[trusted_head] = True
    value = guard()
    value.observe_scores([output(**flags)], attempt=1, step=5)

    decision = value.evaluate(operation, anchor_index=4)

    assert decision.executed_allow is True
    assert decision.trust_field_used == f"{trusted_head}_trusted"
    assert decision.head_trusted is True
    assert decision.head_probability == pytest.approx(0.01)
    assert decision.reliability_envelope_id == "ep:a1:s5:anchor4"
    assert decision.assessment_attempt == 1
    assert decision.assessment_step == 5
    # The operation must still work when unrelated heads make joint trust false.
    assert decision.jointly_trusted is False


@pytest.mark.parametrize("operation", sorted(OPERATION_HEAD))
def test_untrusted_or_missing_head_never_falls_back_to_raw_confidence(operation):
    value = guard()
    assert value.evaluate(operation, anchor_index=4).executed_allow is False

    value.observe_scores([output()], attempt=1, step=5)
    decision = value.evaluate(operation, anchor_index=4)
    assert decision.executed_allow is False
    assert decision.fail_open is False


def test_invalid_model_preserves_relocalization_but_denies_guarded_actions():
    value = guard()
    broken = output(bearing=True, distance=True, pose=True)
    broken["p_pose_bad"] = float("nan")
    value.observe_scores([broken], attempt=1, step=5)

    observation = value.evaluate("relocalization_update", anchor_index=4)
    promotion = value.evaluate("anchor_promotion", anchor_index=4)

    assert observation.executed_allow is True
    assert promotion.executed_allow is False
    assert value.episode_disabled is True
    assert any(
        event["event"] == "v11_core_invalid_safe_degradation"
        for event in value.events
    )


def test_derived_bearing_uses_fresh_one_hop_source_only():
    value = guard()
    value.observe_scores(
        [output(anchor=7, bearing=True)], attempt=1, step=5
    )

    allowed = value.evaluate(
        "route_hint",
        anchor_index=4,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=7,
        edge_hop_count=1,
        evidence_age_updates=3,
        derived_evidence_mode="active",
    )
    stale = value.evaluate(
        "route_hint",
        anchor_index=4,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=7,
        edge_hop_count=1,
        evidence_age_updates=26,
        derived_evidence_mode="active",
    )
    terminal = value.evaluate(
        "forced_stop",
        anchor_index=4,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=7,
        edge_hop_count=1,
        evidence_age_updates=3,
        derived_evidence_mode="active",
    )

    assert allowed.executed_allow is True
    assert stale.executed_allow is False
    assert terminal.executed_allow is False


def test_promotion_streak_requests_recovery_without_raw_fail_open():
    value = guard()
    value.observe_scores([output(pose=False)], attempt=1, step=5)
    decisions = [
        value.evaluate("anchor_promotion", anchor_index=4)
        for _ in range(30)
    ]

    assert all(not decision.executed_allow for decision in decisions)
    assert decisions[-1].recovery_required is True
    assert value.episode_disabled is False


def test_active_policy_cannot_be_loaded_as_shadow_by_accident():
    with pytest.raises(ValueError):
        V11ConsumerGuardV3.load(POLICY, mode="shadow")


def test_policy_mapping_matches_machine_readable_architecture_contract():
    contract = json.loads(
        (ROOT / "config" / "route2_consumer_contract_v1.json").read_text()
    )
    mapped = {
        operation: details["head"]
        for operation, details in contract["consumers"].items()
        if operation in OPERATION_HEAD
    }
    assert mapped == OPERATION_HEAD


def test_policy_rejects_any_raw_confidence_fallback():
    payload = json.loads(POLICY.read_text())
    payload = copy.deepcopy(payload)
    payload["invalid_model_action"] = "fallback_to_raw_confidence"
    with pytest.raises(ValueError):
        V11ConsumerGuardV3(payload, mode="active")
