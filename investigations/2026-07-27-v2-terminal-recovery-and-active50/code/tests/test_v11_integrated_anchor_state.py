import copy
import json
from pathlib import Path

import pytest

from reliability.v11_integrated_anchor_state import (
    V11IntegratedAnchorStateShadow,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "v11_integrated_anchor_state_shadow_v1.json"
RECOVERY_POLICY = (
    ROOT / "configs" / "v11_integrated_anchor_state_recovery_shadow_v1.json"
)


def proposal(
    *,
    current_trusted=True,
    next_trusted=True,
    current_index=4,
    next_index=3,
    pre_closure_vote=False,
    baseline_vote=False,
    attempt=1,
    current_p_pose_bad=None,
    next_p_pose_bad=None,
):
    if current_p_pose_bad is None and current_trusted is not None:
        current_p_pose_bad = 0.01 if current_trusted else 0.90
    if next_p_pose_bad is None and next_trusted is not None:
        next_p_pose_bad = 0.01 if next_trusted else 0.90
    return {
        "current_anchor_index": current_index,
        "next_anchor_index": next_index,
        "current_assessment_available": current_trusted is not None,
        "next_assessment_available": next_trusted is not None,
        "current_jointly_trusted": current_trusted,
        "next_jointly_trusted": next_trusted,
        "current_p_pose_bad": current_p_pose_bad,
        "next_p_pose_bad": next_p_pose_bad,
        "pre_closure_vote": pre_closure_vote,
        "baseline_vote": baseline_vote,
        "attempt": attempt,
        "step": attempt * 5,
    }


def test_untrusted_next_enters_temporary_quarantine_without_control_effect():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(current_trusted=True, next_trusted=False, attempt=i))
        for i in range(1, 4)
    ]
    assert decisions[-1].action == "temporarily_quarantine_next"
    assert decisions[-1].shadow_quarantined_anchors == (3,)
    assert decisions[-1].controller_effect is False
    assert decisions[-1].requires_expanded_candidates is True
    assert decisions[-1].next_state == "strongly_untrusted"
    assert decisions[-1].next_strong_untrusted_count == 3


def test_recovery_policy_uses_geometry_before_scan_or_quarantine():
    state = V11IntegratedAnchorStateShadow.load(RECOVERY_POLICY)
    state.start_episode("ep205")
    decisions = [
        state.observe(proposal(
            current_trusted=True,
            next_trusted=False,
            current_index=2,
            next_index=1,
            next_p_pose_bad=0.98,
            attempt=i,
        ))
        for i in range(1, 6)
    ]
    decision = decisions[-1]
    assert decision.action == "use_trusted_current_geometry_fallback"
    assert decision.geometry_fallback_active is True
    assert decision.geometry_fallback_streak == 3
    assert decision.geometry_fallback_attempt_limit == 12
    assert decision.shadow_quarantined_anchors == ()
    assert decision.requires_expanded_candidates is False
    assert decision.active_scan_latched is False


def test_recovery_policy_requests_scan_after_geometry_budget_expires():
    state = V11IntegratedAnchorStateShadow.load(RECOVERY_POLICY)
    state.start_episode("ep205")
    decisions = [
        state.observe(proposal(
            current_trusted=True,
            next_trusted=False,
            current_index=2,
            next_index=1,
            next_p_pose_bad=0.98,
            attempt=i,
        ))
        for i in range(1, 16)
    ]
    requests = [
        decision for decision in decisions
        if decision.action
        == "request_active_scan_geometry_fallback_exhausted"
    ]
    assert len(requests) == 1
    assert requests[0].geometry_fallback_streak == 13
    assert requests[0].shadow_quarantined_anchors == ()
    assert requests[0].active_scan_latched is True


def test_abstentions_do_not_accumulate_as_strong_negative_evidence():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep5")
    probabilities = (0.216, 0.556, 0.872, 0.807, 0.935, 0.570, 0.403)
    decisions = [
        state.observe(proposal(
            current_trusted=True,
            next_trusted=probability < 0.30,
            next_p_pose_bad=probability,
            attempt=attempt,
        ))
        for attempt, probability in enumerate(probabilities, start=20)
    ]
    assert not any(
        decision.action == "temporarily_quarantine_next"
        for decision in decisions
    )
    assert decisions[-1].next_state == "uncertain"
    assert decisions[-1].next_strong_untrusted_count == 1


def test_strong_next_requires_trusted_current_before_quarantine():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(
            current_trusted=False,
            next_trusted=False,
            current_p_pose_bad=0.60,
            next_p_pose_bad=0.98,
            attempt=i,
        ))
        for i in range(1, 4)
    ]
    assert decisions[-1].current_state == "uncertain"
    assert decisions[-1].next_state == "strongly_untrusted"
    assert (
        decisions[-1].action
        == "hold_strong_next_without_current_authority"
    )
    assert decisions[-1].shadow_quarantined_anchors == ()


def test_trusted_reentry_releases_quarantine_before_ttl():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    for i in range(1, 4):
        state.observe(proposal(current_trusted=True, next_trusted=False, attempt=i))
    released = None
    for i in range(4, 10):
        released = state.observe(
            proposal(current_trusted=True, next_trusted=True, attempt=i)
        )
        if released.action == "release_quarantine_on_trusted_reentry":
            break
    assert released is not None
    assert released.action == "release_quarantine_on_trusted_reentry"
    assert released.released_quarantines == (3,)
    assert released.shadow_quarantined_anchors == ()


def test_repeated_quarantine_requests_active_scan():
    payload = json.loads(POLICY.read_text())
    payload["quarantine_ttl_attempts"] = 2
    payload["max_quarantine_cycles_per_anchor"] = 1
    state = V11IntegratedAnchorStateShadow(payload)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(current_trusted=True, next_trusted=False, attempt=i))
        for i in range(1, 8)
    ]
    assert decisions[2].action == "temporarily_quarantine_next"
    requests = [
        decision
        for decision in decisions
        if decision.action == "request_active_scan_repeated_quarantine"
    ]
    assert len(requests) == 1
    assert requests[0].requires_expanded_candidates is True
    assert decisions[-1].action == "hold_active_scan_request"


def test_rolling_window_prevents_single_sample_quarantine_reentry():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    for i in range(1, 4):
        state.observe(proposal(current_trusted=True, next_trusted=False, attempt=i))
    one_good = state.observe(
        proposal(current_trusted=True, next_trusted=True, attempt=4)
    )
    assert one_good.action == "hold_temporary_quarantine"
    assert one_good.shadow_quarantined_anchors == (3,)
    assert one_good.next_trusted_fraction == pytest.approx(0.25)


def test_scan_request_is_edge_triggered_and_latched():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(
            current_trusted=False,
            next_trusted=False,
            attempt=i,
        ))
        for i in range(1, 16)
    ]
    requests = [
        decision
        for decision in decisions
        if decision.action == "request_active_scan_both_untrusted"
    ]
    assert len(requests) == 1
    assert decisions[-1].action == "hold_active_scan_request"
    assert decisions[-1].active_scan_latched is True
    assert (
        decisions[-1].active_scan_trigger_action
        == "request_active_scan_both_untrusted"
    )


def test_both_untrusted_scan_cancels_after_trusted_recovery():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    decisions = []
    for i in range(1, 11):
        decisions.append(state.observe(proposal(
            current_trusted=False,
            next_trusted=False,
            attempt=i,
        )))
    for i in range(11, 19):
        decisions.append(state.observe(proposal(
            current_trusted=True,
            next_trusted=True,
            attempt=i,
        )))
    requests = [
        decision
        for decision in decisions
        if decision.action == "request_active_scan_both_untrusted"
    ]
    cancellations = [
        decision
        for decision in decisions
        if decision.action == "cancel_active_scan_on_trust_recovery"
    ]
    assert len(requests) == 1
    assert len(cancellations) == 1
    assert (
        cancellations[0].cancelled_active_scan_trigger_action
        == "request_active_scan_both_untrusted"
    )
    assert cancellations[0].active_scan_latched is False


def test_repeated_quarantine_scan_does_not_cancel_on_trusted_current_only():
    payload = json.loads(POLICY.read_text())
    payload["quarantine_ttl_attempts"] = 2
    payload["max_quarantine_cycles_per_anchor"] = 1
    state = V11IntegratedAnchorStateShadow(payload)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(
            current_trusted=True,
            next_trusted=False,
            attempt=i,
        ))
        for i in range(1, 14)
    ]
    assert any(
        decision.action == "request_active_scan_repeated_quarantine"
        for decision in decisions
    )
    assert decisions[-1].action == "hold_active_scan_request"
    assert decisions[-1].active_scan_latched is True


def test_quarantine_cycle_history_survives_reentry():
    payload = json.loads(POLICY.read_text())
    payload["quarantine_ttl_attempts"] = 20
    payload["max_quarantine_cycles_per_anchor"] = 1
    state = V11IntegratedAnchorStateShadow(payload)
    state.start_episode("ep1")
    decisions = []
    attempt = 0
    for trust, count in ((False, 8), (True, 8), (False, 8)):
        for _ in range(count):
            attempt += 1
            decisions.append(state.observe(proposal(
                current_trusted=True,
                next_trusted=trust,
                attempt=attempt,
            )))
    assert any(
        decision.action == "release_quarantine_on_trusted_reentry"
        for decision in decisions
    )
    assert any(
        decision.action == "request_active_scan_repeated_quarantine"
        for decision in decisions
    )


def test_bad_current_cannot_veto_trusted_next_evidence():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(
            current_trusted=False,
            next_trusted=True,
            pre_closure_vote=True,
            baseline_vote=False,
            attempt=i,
        ))
        for i in range(1, 4)
    ]
    assert decisions[-1].action == "admit_next_evidence_without_current_veto"


def test_both_untrusted_requests_active_scan_and_suppresses_precise_hint():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    decisions = [
        state.observe(proposal(
            current_trusted=False,
            next_trusted=False,
            attempt=i,
        ))
        for i in range(1, 11)
    ]
    assert decisions[-1].action == "request_active_scan_both_untrusted"
    assert decisions[-1].would_suppress_precise_hint is True


def test_current_change_resets_quarantine_chain():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep1")
    for i in range(1, 4):
        state.observe(proposal(current_trusted=True, next_trusted=False, attempt=i))
    changed = state.observe(proposal(
        current_trusted=True,
        next_trusted=True,
        current_index=3,
        next_index=2,
        attempt=4,
    ))
    assert changed.current_changed is True
    assert changed.shadow_quarantined_anchors == ()
    assert changed.quarantine_chain_anchors == ()
    assert changed.current_pose_bad_window_size == 1
    assert changed.next_pose_bad_window_size == 1


def test_current_change_does_not_reuse_stale_strong_negative_window():
    state = V11IntegratedAnchorStateShadow.load(POLICY)
    state.start_episode("ep5")
    for i in range(1, 4):
        state.observe(proposal(
            current_index=13,
            next_index=11,
            current_trusted=True,
            next_trusted=False,
            attempt=i,
        ))
    changed = state.observe(proposal(
        current_index=12,
        next_index=11,
        current_trusted=False,
        next_trusted=False,
        current_p_pose_bad=0.403,
        next_p_pose_bad=0.970,
        attempt=4,
    ))
    assert changed.current_changed is True
    assert changed.next_state == "uncertain"
    assert changed.action == "accumulate_evidence"
    assert changed.shadow_quarantined_anchors == ()
    assert changed.next_strong_untrusted_count == 1


def test_policy_is_structurally_shadow_locked():
    payload = json.loads(POLICY.read_text())
    for mutation in (
        {"mode": "active"},
        {"enforcement_approved": True},
        {"identity_override_authorized": True},
    ):
        invalid = copy.deepcopy(payload)
        invalid.update(mutation)
        with pytest.raises(ValueError):
            V11IntegratedAnchorStateShadow(invalid)
