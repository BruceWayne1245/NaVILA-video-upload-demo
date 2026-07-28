from copy import deepcopy

from reliability.v11_anchor_support_recovery import V11AnchorSupportRecovery


POLICY = {
    "schema": "navila-v11-anchor-support-recovery-active-v1",
    "mode": "active",
    "enforcement_approved": True,
    "identity_semantics": "guidance_support_not_localization",
    "trust_window_attempts": 1,
    "trusted_min_observations": 1,
    "trusted_min_count": 1,
    "strong_untrusted_window_attempts": 1,
    "strong_untrusted_min_observations": 1,
    "strong_untrusted_min_count": 1,
    "strong_untrusted_pose_probability_threshold": 0.8,
    "pair_recovery_offsets": [[1, 0], [1, -1], [2, -1], [2, -2], [2, -3]],
    "probe_direction": "failed_next_minus_one_to_anchor_zero",
    "scan_role": "shadow_observer_only",
}


def score(anchor, trusted):
    return {
        "anchor_index": anchor,
        "jointly_trusted": trusted,
        "p_pose_bad": 0.05 if trusted else 0.95,
    }


def observe(controller, current, next_anchor, current_ok, next_ok, attempt):
    return controller.observe_scores(
        [score(current, current_ok), score(next_anchor, next_ok)],
        requested_current_index=current,
        requested_next_index=next_anchor,
        attempt=attempt,
        step=attempt * 5,
    )


def controller():
    instance = V11AnchorSupportRecovery(deepcopy(POLICY))
    instance.start_episode("ep")
    return instance


def test_trusted_current_reconstructs_and_blocks_bad_next_promotion():
    decision = observe(controller(), 10, 9, True, False, 1)
    assert decision.mode == "reconstruct_next"
    assert decision.reconstruct_next_from_current
    assert decision.current_anchor_index == 10
    assert decision.next_anchor_index == 9
    assert decision.promotion_blocked_anchors == (9,)
    assert decision.raw_hint_blocked_anchors == (9,)
    assert decision.route_consumers_enabled


def test_raw_hint_block_clears_on_recovered_trust_but_promotion_block_persists():
    instance = controller()
    first = observe(instance, 10, 9, True, False, 1)
    assert first.raw_hint_blocked_anchors == (9,)

    recovered = observe(instance, 10, 9, True, True, 2)
    assert recovered.mode == "normal"
    assert recovered.promotion_blocked_anchors == (9,)
    assert recovered.raw_hint_blocked_anchors == ()


def test_trusted_next_is_used_without_bad_current_veto():
    decision = observe(controller(), 10, 9, False, True, 1)
    assert decision.mode == "next_only"
    assert decision.next_anchor_index == 9
    assert decision.action == "use_trusted_next_without_current_veto"
    assert decision.route_consumers_enabled


def test_both_bad_follow_exact_alternating_support_search_then_vlm_only():
    instance = controller()
    pairs = []
    requested = (10, 9)
    for attempt in range(1, 7):
        decision = observe(instance, *requested, False, False, attempt)
        pairs.append((decision.current_anchor_index, decision.next_anchor_index))
        requested = pairs[-1]
    assert pairs[:5] == [(11, 9), (11, 8), (12, 8), (12, 7), (12, 6)]
    assert pairs[5] == (12, 6)
    assert decision.mode == "vlm_only_probing"
    assert decision.vlm_only
    assert not decision.route_consumers_enabled
    assert decision.probe_anchor_indices == tuple(range(8, -1, -1))


def test_vlm_only_probe_recovery_uses_closest_trusted_forward_anchor():
    instance = controller()
    requested = (10, 9)
    for attempt in range(1, 7):
        decision = observe(instance, *requested, False, False, attempt)
        requested = (decision.current_anchor_index, decision.next_anchor_index)
    outputs = [score(index, index in (7, 5)) for index in range(8, -1, -1)]
    decision = instance.observe_scores(
        outputs,
        requested_current_index=12,
        requested_next_index=6,
        attempt=7,
        step=35,
    )
    assert decision.mode == "next_only"
    assert decision.next_anchor_index == 7
    assert decision.route_consumers_enabled
    assert not decision.vlm_only


def test_vlm_only_can_resume_when_rear_support_recovers():
    instance = controller()
    requested = (10, 9)
    for attempt in range(1, 7):
        decision = observe(instance, *requested, False, False, attempt)
        requested = (decision.current_anchor_index, decision.next_anchor_index)
    decision = observe(instance, 12, 6, True, False, 7)
    assert decision.mode == "reconstruct_next"
    assert decision.reconstruct_next_from_current
    assert decision.route_consumers_enabled
    assert decision.action == "resume_from_recovered_current_and_reconstruct_next"


def test_scan_shadow_field_cannot_change_active_transition():
    first = controller()
    second = controller()
    left = observe(first, 10, 9, False, False, 1).as_dict()
    right = observe(second, 10, 9, False, False, 1).as_dict()
    # A logger may choose to ignore this observer-only field.  Every active
    # field remains byte-identical.
    left.pop("shadow_scan_recommended")
    right.pop("shadow_scan_recommended")
    assert left == right


def test_template_must_not_arm_active_behavior():
    policy = deepcopy(POLICY)
    policy["enforcement_approved"] = False
    try:
        V11AnchorSupportRecovery(policy)
    except ValueError as exc:
        assert "not approved" in str(exc)
    else:
        raise AssertionError("unapproved active policy was accepted")
