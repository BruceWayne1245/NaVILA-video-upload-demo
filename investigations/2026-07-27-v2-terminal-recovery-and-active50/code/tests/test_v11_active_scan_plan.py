import copy
import json
from pathlib import Path

import pytest

from reliability.v11_active_scan_plan import V11ActiveScanPlanShadow


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "v11_active_scan_plan_shadow_v1.json"


def proposal(action="request_active_scan", state_action="request_active_scan_both_untrusted"):
    return {
        "sequence": 10,
        "attempt": 100,
        "step": 3201,
        "current_anchor_index": 2,
        "route1_next_anchor_index": 1,
        "state_action": state_action,
        "proposal_action": action,
        "reason": "both_anchors_confirmed_untrusted",
    }


def test_scan_plan_is_bounded_rotation_only_and_returns_to_heading():
    planner = V11ActiveScanPlanShadow.load(POLICY)
    planner.start_episode("ep205")
    plan = planner.observe_proposal(proposal())

    assert plan is not None
    assert len(plan.rotations) == 7
    assert plan.rotations[-1].target_offset_deg == 0.0
    assert all(rotation.duration_s > 0.0 for rotation in plan.rotations)
    assert sum(
        rotation.duration_s for rotation in plan.rotations
    ) == pytest.approx(9.0)
    assert plan.translation_authorized is False
    assert plan.stop_authorized is False
    assert plan.motor_effect is False
    assert plan.max_scan_cycles == 1


def test_scan_latch_emits_one_plan_until_cancelled():
    planner = V11ActiveScanPlanShadow.load(POLICY)
    planner.start_episode("ep205")
    assert planner.observe_proposal(proposal()) is not None
    assert planner.observe_proposal(proposal(action="hold_active_scan_request")) is None
    planner.observe_proposal(proposal(
        action="preserve_route1_next",
        state_action="cancel_active_scan_on_trust_recovery",
    ))
    assert planner.observe_proposal(proposal()) is not None


@pytest.mark.parametrize(
    "mutation",
    [
        {"mode": "active"},
        {"enforcement_approved": True},
        {"motor_rotation_authorized": True},
        {"motor_translation_authorized": True},
        {"stop_authorized": True},
        {"target_yaw_offsets_deg": [-30.0, 30.0]},
        {"max_scan_cycles": 2},
    ],
)
def test_shadow_scan_policy_is_default_closed(mutation):
    payload = json.loads(POLICY.read_text())
    payload.update(copy.deepcopy(mutation))
    with pytest.raises(ValueError):
        V11ActiveScanPlanShadow(payload)
