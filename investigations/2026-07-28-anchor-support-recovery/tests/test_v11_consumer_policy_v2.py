import copy
import json
from pathlib import Path

import pytest

from reliability.v11_consumer_policy_v2 import V11ConsumerGuardV2


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "v11_consumer_policy_v2.json"


def output(anchor_index=4, jointly_trusted=True):
    return {
        "anchor_index": anchor_index,
        "anchor_role": "current",
        "p_bearing_bad_30": 0.01,
        "p_distance_bad_0p5": 0.01,
        "p_pose_bad": 0.01,
        "bearing_trusted": jointly_trusted,
        "distance_trusted": jointly_trusted,
        "pose_trusted": jointly_trusted,
        "jointly_trusted": jointly_trusted,
    }


def active_payload():
    payload = json.loads(POLICY.read_text())
    payload["mode"] = "active"
    payload["enforcement_approved"] = True
    return payload


def test_shadow_records_veto_but_preserves_baseline():
    guard = V11ConsumerGuardV2.load(POLICY)
    guard.start_episode("ep1")
    guard.observe_scores([output(jointly_trusted=False)], attempt=1, step=10)
    decision = guard.evaluate("forced_stop", anchor_index=4)
    assert decision.counterfactual_allow is False
    assert decision.executed_allow is True
    assert decision.controller_effect is False


def test_relocalization_update_is_never_gated():
    guard = V11ConsumerGuardV2.load(POLICY)
    guard.start_episode("ep1")
    guard.observe_scores([output(jointly_trusted=False)], attempt=1, step=10)
    decision = guard.evaluate("relocalization_update", anchor_index=4)
    assert decision.counterfactual_allow is True
    assert decision.executed_allow is True


def test_active_guard_vetoes_only_guarded_operation():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep1")
    guard.observe_scores([output(jointly_trusted=False)], attempt=1, step=10)
    decision = guard.evaluate("hint_action_override", anchor_index=4)
    assert decision.counterfactual_allow is False
    assert decision.executed_allow is False
    assert decision.controller_effect is True


def test_one_hop_derived_bearing_uses_trusted_source_not_bad_target():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep205")
    guard.observe_scores(
        [
            output(anchor_index=2, jointly_trusted=True),
            output(anchor_index=1, jointly_trusted=False),
        ],
        attempt=100,
        step=3201,
    )
    decision = guard.evaluate(
        "hint_action_override",
        anchor_index=1,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=2,
        edge_hop_count=1,
        evidence_age_updates=0,
        derived_evidence_mode="active",
    )
    assert decision.executed_allow is True
    assert decision.counterfactual_allow is True
    assert decision.authority_anchor_index == 2
    assert decision.trust_field_used == "bearing_trusted"
    assert decision.reason == "derived_one_hop_bearing_source_trusted"


def test_bounded_multi_hop_derived_bearing_uses_trusted_source():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep205-multihop")
    guard.observe_scores(
        [
            output(anchor_index=12, jointly_trusted=True),
            output(anchor_index=7, jointly_trusted=False),
        ],
        attempt=100,
        step=3201,
    )
    decision = guard.evaluate(
        "route_hint",
        anchor_index=7,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=12,
        edge_hop_count=5,
        evidence_age_updates=0,
        derived_evidence_mode="active",
        derived_max_edge_hops=8,
    )
    assert decision.executed_allow is True
    assert decision.authority_anchor_index == 12
    assert decision.reason == "derived_bounded_hop_bearing_source_trusted"


def test_derived_distance_cannot_force_stop_but_preserves_stop_veto():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep205")
    guard.observe_scores(
        [
            output(anchor_index=2, jointly_trusted=True),
            output(anchor_index=1, jointly_trusted=False),
        ],
        attempt=100,
        step=3201,
    )
    kwargs = {
        "anchor_index": 1,
        "evidence_kind": "geometry_reconstructed",
        "source_anchor_index": 2,
        "edge_hop_count": 1,
        "evidence_age_updates": 0,
        "derived_evidence_mode": "active",
    }
    forced = guard.evaluate("forced_stop", **kwargs)
    veto = guard.evaluate("vlm_stop_veto", **kwargs)

    assert forced.executed_allow is False
    assert forced.reason == "derived_distance_not_authorized_for_forced_stop"
    assert veto.executed_allow is True
    assert veto.reason == "preserve_independent_vlm_stop_veto"


def test_derived_shadow_logs_recovery_but_executes_legacy_guard():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep205")
    guard.observe_scores(
        [
            output(anchor_index=2, jointly_trusted=True),
            output(anchor_index=1, jointly_trusted=False),
        ],
        attempt=100,
        step=3201,
    )
    decision = guard.evaluate(
        "route_hint",
        anchor_index=1,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=2,
        edge_hop_count=1,
        evidence_age_updates=0,
        derived_evidence_mode="shadow",
    )
    assert decision.counterfactual_allow is True
    assert decision.legacy_counterfactual_allow is False
    assert decision.executed_allow is False
    assert decision.controller_effect is True


@pytest.mark.parametrize(
    ("edge_hop_count", "age", "reason"),
    [
        (2, 0, "derived_bearing_requires_exactly_one_edge"),
        (1, 26, "derived_bearing_evidence_expired"),
    ],
)
def test_derived_bearing_is_bounded_by_hop_and_age(
    edge_hop_count,
    age,
    reason,
):
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep205")
    guard.observe_scores(
        [output(anchor_index=2, jointly_trusted=True)],
        attempt=100,
        step=3201,
    )
    decision = guard.evaluate(
        "route_hint",
        anchor_index=1,
        evidence_kind="geometry_reconstructed",
        source_anchor_index=2,
        edge_hop_count=edge_hop_count,
        evidence_age_updates=age,
        derived_evidence_mode="active",
        derived_max_age_updates=25,
    )
    assert decision.executed_allow is False
    assert decision.reason == reason


def test_missing_assessment_vetoes_consumer_without_disabling_episode():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep1")
    bootstrap = guard.evaluate("route_hint", anchor_index=4)
    assert bootstrap.executed_allow is True
    assert bootstrap.fail_open is False
    assert guard.episode_disabled is False
    guard.observe_scores([output(anchor_index=3)], attempt=1, step=10)
    missing = guard.evaluate("forced_stop", anchor_index=4)
    assert missing.executed_allow is False
    assert missing.fail_open is False
    assert guard.episode_disabled is False
    guard.disable_fail_open("synthetic_runtime_failure")
    later = guard.evaluate("anchor_promotion", anchor_index=4)
    assert later.executed_allow is True
    assert "episode_disabled_fail_open" in later.reason


def test_shadow_artifact_cannot_be_loaded_active():
    with pytest.raises(RuntimeError):
        V11ConsumerGuardV2.load(POLICY, mode="active")


def test_duplicate_or_nonfinite_outputs_disable_fail_open():
    for outputs in (
        [output(), output()],
        [{**output(), "p_pose_bad": float("nan")}],
    ):
        guard = V11ConsumerGuardV2(active_payload(), mode="active")
        guard.start_episode("ep1")
        guard.observe_scores(copy.deepcopy(outputs), attempt=1, step=10)
        assert guard.episode_disabled is True
        decision = guard.evaluate("forced_stop", anchor_index=4)
        assert decision.executed_allow is True


def test_promotion_veto_streak_has_bounded_fail_open():
    payload = active_payload()
    payload["promotion_veto_warning_streak"] = 2
    payload["promotion_veto_fallback_streak"] = 3
    guard = V11ConsumerGuardV2(payload, mode="active")
    guard.start_episode("ep1")
    guard.observe_scores([output(jointly_trusted=False)], attempt=1, step=10)
    assert guard.evaluate("anchor_promotion", anchor_index=4).executed_allow is False
    assert guard.evaluate("anchor_promotion", anchor_index=4).executed_allow is False
    fallback = guard.evaluate("anchor_promotion", anchor_index=4)
    assert fallback.executed_allow is True
    assert fallback.fail_open is True
    assert guard.episode_disabled is True


def test_integrated_shadow_blocks_untrusted_next_before_vote_history():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep1")
    guard.observe_scores(
        [
            output(anchor_index=4, jointly_trusted=True),
            output(anchor_index=3, jointly_trusted=False),
        ],
        attempt=1,
        step=10,
    )
    decision = guard.evaluate_promotion_evidence(
        current_anchor_index=4,
        next_anchor_index=3,
        pre_closure_vote=True,
        baseline_vote=True,
        closure_rejected=False,
    )
    assert decision.counterfactual_vote is False
    assert decision.executed_vote is True
    assert decision.controller_effect is False
    assert decision.current_p_pose_bad == pytest.approx(0.01)
    assert decision.next_p_pose_bad == pytest.approx(0.01)


def test_integrated_shadow_releases_bad_current_closure_veto():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep1")
    guard.observe_scores(
        [
            output(anchor_index=4, jointly_trusted=False),
            output(anchor_index=3, jointly_trusted=True),
        ],
        attempt=1,
        step=10,
    )
    decision = guard.evaluate_promotion_evidence(
        current_anchor_index=4,
        next_anchor_index=3,
        pre_closure_vote=True,
        baseline_vote=False,
        closure_rejected=True,
    )
    assert decision.counterfactual_vote is True
    assert decision.executed_vote is False
    assert decision.reason == (
        "current_untrusted_next_trusted_ignore_current_closure_veto"
    )
    assert guard.events[-1]["event"] == (
        "v11_integrated_promotion_shadow_decision"
    )


def test_anchor_assessment_is_defensive_copy():
    guard = V11ConsumerGuardV2.load(POLICY)
    guard.start_episode("ep1")
    guard.observe_scores([output(anchor_index=4)], attempt=1, step=10)
    assessment = guard.anchor_assessment(4)
    assert assessment is not None
    assessment["jointly_trusted"] = False
    assert guard.anchor_assessment(4)["jointly_trusted"] is True


def test_integrated_shadow_ignores_legacy_promotion_streak_fail_open():
    payload = active_payload()
    payload["promotion_veto_warning_streak"] = 1
    payload["promotion_veto_fallback_streak"] = 1
    guard = V11ConsumerGuardV2(payload, mode="active")
    guard.start_episode("ep1")
    guard.observe_scores(
        [
            output(anchor_index=4, jointly_trusted=True),
            output(anchor_index=3, jointly_trusted=False),
        ],
        attempt=1,
        step=10,
    )
    legacy = guard.evaluate("anchor_promotion", anchor_index=3)
    assert legacy.fail_open is True
    assert guard.episode_disabled is True

    decision = guard.evaluate_promotion_evidence(
        current_anchor_index=4,
        next_anchor_index=3,
        pre_closure_vote=True,
        baseline_vote=True,
        closure_rejected=False,
    )
    assert decision.counterfactual_vote is False
    assert decision.executed_vote is True
    assert decision.episode_disabled is True
    assert decision.legacy_promotion_fail_open_ignored is True


def test_integrated_shadow_preserves_baseline_after_model_failure():
    guard = V11ConsumerGuardV2(active_payload(), mode="active")
    guard.start_episode("ep1")
    guard.observe_scores(
        [{**output(anchor_index=3), "p_pose_bad": float("nan")}],
        attempt=1,
        step=10,
    )
    decision = guard.evaluate_promotion_evidence(
        current_anchor_index=4,
        next_anchor_index=3,
        pre_closure_vote=True,
        baseline_vote=True,
        closure_rejected=False,
    )
    assert decision.counterfactual_vote is True
    assert decision.executed_vote is True
    assert decision.legacy_promotion_fail_open_ignored is False
    assert decision.reason.startswith("episode_disabled_fail_open:model_output_invalid")
