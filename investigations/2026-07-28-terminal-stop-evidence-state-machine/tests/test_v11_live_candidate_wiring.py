import ast
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "policy_v2_live_candidate" / "scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location(
    "policy_v2_candidate_route_memory_agent",
    SCRIPTS / "route_memory_agent.py",
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
RouteMemoryAgent = module.RouteMemoryAgent
RelativeStartProgress = module.RelativeStartProgress
AnchorRelocalization = module.AnchorRelocalization


def test_start_anchor_descriptor_backfill_preserves_a0_identity():
    descriptor = {"local_map_points_body": [[1.0, 0.0], [2.0, 0.5]]}
    agent = RouteMemoryAgent(enabled=True)
    original_pose = list(agent.anchors[0].pose_from_start)
    original_edge = list(agent.anchors[0].edge_from_previous)

    assert agent.initialize_start_anchor_descriptor(
        descriptor,
        metadata={"descriptor_event": "test_reset_capture"},
    ) is True

    anchor = agent.anchors[0]
    assert anchor.index == 0
    assert anchor.pose_from_start == original_pose == [0.0, 0.0, 0.0]
    assert anchor.distance_from_start_m == 0.0
    assert anchor.edge_from_previous == original_edge == [0.0, 0.0, 0.0]
    assert anchor.descriptor is descriptor
    assert anchor.metadata["start_descriptor_initialized"] is True
    assert anchor.metadata["descriptor_event"] == "test_reset_capture"


def test_start_anchor_descriptor_backfill_is_one_shot():
    agent = RouteMemoryAgent(enabled=True)
    first = {"local_map_points_body": [[1.0, 0.0]]}
    second = {"local_map_points_body": [[9.0, 9.0]]}

    assert agent.initialize_start_anchor_descriptor(first) is True
    assert agent.initialize_start_anchor_descriptor(second) is False
    assert agent.anchors[0].descriptor is first


def _agent_with_anchor_count(count):
    agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=0.5)
    for _ in range(1, count):
        agent.update_outbound_motion(
            [0.6, 0.0, 0.0],
            descriptor={"local_map_points_body": [[1.0, 0.0]]},
        )
    return agent


def test_anchor_support_roles_are_independent_and_blocks_do_not_remove_probes():
    agent = _agent_with_anchor_count(13)
    directive = {
        "current_anchor_index": 12,
        "next_anchor_index": 7,
        "probe_anchor_indices": (8, 7, 6, 5),
        "promotion_blocked_anchors": (9, 8),
        "raw_hint_blocked_anchors": (9, 8),
        "route_consumers_enabled": False,
        "vlm_only": True,
        "reconstruct_next_from_current": False,
    }
    agent.apply_v11_anchor_support_directive(
        directive,
        requested_pair=(12, 8),
    )
    current, next_anchor = agent.sequential_target_anchor_pair()
    assert (current.index, next_anchor.index) == (12, 7)
    # A8 remains probe-eligible despite being forbidden from promotion/hints.
    assert [anchor.index for anchor in agent.sequential_probe_anchors()] == [8, 6, 5]
    assert not agent.route_consumers_enabled


def test_anchor_support_reconstruct_flag_is_scoped_to_requested_pair():
    agent = _agent_with_anchor_count(11)
    directive = {
        "current_anchor_index": 10,
        "next_anchor_index": 9,
        "probe_anchor_indices": (),
        "promotion_blocked_anchors": (9,),
        "raw_hint_blocked_anchors": (9,),
        "route_consumers_enabled": True,
        "vlm_only": False,
        "reconstruct_next_from_current": True,
    }
    agent.apply_v11_anchor_support_directive(
        directive,
        requested_pair=(10, 9),
    )
    assert agent.v11_anchor_support_state == {
        "current_anchor_index": 10,
        "next_anchor_index": 9,
        "probe_anchor_indices": [],
        "promotion_blocked_anchors": [9],
        "raw_hint_blocked_anchors": [9],
        "route_consumers_enabled": True,
        "vlm_only": False,
    }


def test_raw_block_removes_just_selected_bad_next_before_next_vlm_query():
    agent = _agent_with_anchor_count(11)
    agent._latest_next_candidate_relocalization = AnchorRelocalization(
        anchor_index=9,
        anchor_dx_m=2.0,
        anchor_dy_m=1.0,
        confidence=0.95,
        backend="sequential_pair",
    )
    agent.apply_v11_anchor_support_directive(
        {
            "current_anchor_index": 10,
            "next_anchor_index": 9,
            "probe_anchor_indices": (),
            "promotion_blocked_anchors": (9,),
            "raw_hint_blocked_anchors": (9,),
            "route_consumers_enabled": True,
            "vlm_only": False,
            "reconstruct_next_from_current": True,
        },
        requested_pair=(10, 9),
    )
    assert agent._latest_next_candidate_relocalization is None


def test_progress_marks_next_and_current_roles_for_terminal_authority():
    next_agent = RouteMemoryAgent(
        enabled=True,
        sequential_pair_report_next_anchor=True,
    )
    next_agent._latest_next_candidate_relocalization = AnchorRelocalization(
        anchor_index=0,
        anchor_dx_m=0.5,
        anchor_dy_m=0.0,
        confidence=0.9,
        evidence_update_count=0,
    )
    next_progress = next_agent._anchor_progress()

    current_agent = RouteMemoryAgent(enabled=True)
    current_agent._latest_relocalization = AnchorRelocalization(
        anchor_index=0,
        anchor_dx_m=0.5,
        anchor_dy_m=0.0,
        confidence=0.9,
        evidence_update_count=0,
    )
    current_progress = current_agent._anchor_progress()

    assert next_progress.estimate_role == "next"
    assert current_progress.estimate_role == "current"


def test_bad_next_is_geometry_reconstructed_but_never_promoted():
    agent = _agent_with_anchor_count(11)
    agent.finalize_outbound()
    agent.sequential_target_anchor_pair()
    agent.apply_v11_anchor_support_directive(
        {
            "current_anchor_index": 10,
            "next_anchor_index": 9,
            "probe_anchor_indices": (),
            "promotion_blocked_anchors": (9,),
            "raw_hint_blocked_anchors": (9,),
            "route_consumers_enabled": True,
            "vlm_only": False,
            "reconstruct_next_from_current": True,
        },
        requested_pair=(10, 9),
    )
    current = AnchorRelocalization(
        anchor_index=10,
        anchor_dx_m=0.2,
        anchor_dy_m=0.0,
        confidence=1.0,
        backend="sequential_pair",
        inlier_count=25,
    )
    bad_next = AnchorRelocalization(
        anchor_index=9,
        anchor_dx_m=3.0,
        anchor_dy_m=2.0,
        confidence=0.9,
        backend="sequential_pair",
        inlier_count=25,
    )
    selected, _observation, reject = agent._select_sequential_pair_relocalization(
        [current, bad_next]
    )
    assert reject is None
    assert selected.anchor_index == 10
    reconstructed = agent._latest_next_candidate_relocalization
    assert reconstructed.anchor_index == 9
    assert reconstructed.estimate_kind == "geometry_reconstructed"
    assert reconstructed.source_anchor_index == 10
    assert reconstructed.target_raw_confidence == 0.9
    assert agent._target_anchor_index == 10


def test_one_hop_reconstruction_uses_source_confidence_and_provenance():
    agent = RouteMemoryAgent(
        enabled=True,
        sequential_pair_closure_check_enabled=True,
        sequential_pair_reconstructed_confidence_source_one_hop=True,
    )
    agent.update_outbound_motion(
        [1.0, 0.0, 0.0],
        descriptor={"local_map_points_body": [[1.0, 0.0]]},
    )
    raw_a0 = AnchorRelocalization(
        anchor_index=0,
        anchor_dx_m=2.0,
        anchor_dy_m=2.0,
        confidence=0.4,
        inlier_count=25,
    )
    trusted_a1 = AnchorRelocalization(
        anchor_index=1,
        anchor_dx_m=0.2,
        anchor_dy_m=0.0,
        confidence=1.0,
        inlier_count=25,
    )

    estimates, reject = agent._sequential_pair_closure_precheck(
        [raw_a0, trusted_a1]
    )
    reconstructed = {
        estimate.anchor_index: estimate for estimate in estimates
    }[0]

    assert reject is None
    assert reconstructed.estimate_kind == "geometry_reconstructed"
    assert reconstructed.source_anchor_index == 1
    assert reconstructed.edge_hop_count == 1
    assert reconstructed.source_confidence == 1.0
    assert reconstructed.target_raw_confidence == 0.4
    assert reconstructed.confidence == 1.0
    assert reconstructed.backend.endswith("+closure_reconstructed")
    assert reconstructed.anchor_dx_m == pytest.approx(-0.8)
    assert reconstructed.anchor_dy_m == pytest.approx(0.0)


def test_route_memory_consumer_hook_defaults_to_allow():
    agent = RouteMemoryAgent()
    assert agent._v11_consumer_allows("anchor_promotion", 3) is True


def test_route_memory_consumer_hook_receives_promotion_identity():
    calls = []
    agent = RouteMemoryAgent(
        v11_consumer_guard=lambda operation, anchor_index: (
            calls.append((operation, anchor_index)) or False
        )
    )
    assert agent._v11_consumer_allows("anchor_promotion", 3) is False
    assert calls == [("anchor_promotion", 3)]


def test_integrated_promotion_hook_receives_pre_vote_state():
    calls = []

    def policy(**proposal):
        calls.append(proposal)
        return proposal["baseline_vote"]

    agent = RouteMemoryAgent(v11_promotion_evidence_policy=policy)
    vote = agent._v11_integrated_promotion_vote(
        current_anchor_index=4,
        next_anchor_index=3,
        pre_closure_vote=True,
        baseline_vote=False,
        closure_rejected=True,
    )
    assert vote is False
    assert calls == [{
        "current_anchor_index": 4,
        "next_anchor_index": 3,
        "pre_closure_vote": True,
        "baseline_vote": False,
        "closure_rejected": True,
    }]


def test_active_candidate_directive_atomically_quarantines_and_suppresses():
    def controller(**_snapshot):
        return {
            "controller_effect": True,
            "suppress_promotion": True,
            "active_quarantined_anchors": (3,),
        }

    agent = RouteMemoryAgent(
        reliability_quarantine_max_chain=4,
        v11_candidate_transition_shadow=controller,
    )
    agent.anchors = [
        type("Anchor", (), {"index": index})()
        for index in range(5)
    ]
    suppress = agent._v11_integrated_candidate_transition_observe(
        current_anchor_index=4,
        next_anchor_index=3,
    )
    assert suppress is True
    assert agent._v11_active_quarantined_anchor_indices == {3}
    assert agent._next_candidate_index(4) == 2


def test_shadow_candidate_observer_has_no_active_side_effect():
    agent = RouteMemoryAgent(
        v11_candidate_transition_shadow=lambda **_snapshot: None,
    )
    suppress = agent._v11_integrated_candidate_transition_observe(
        current_anchor_index=4,
        next_anchor_index=3,
    )
    assert suppress is False
    assert agent._v11_active_quarantined_anchor_indices == set()


def test_round_trip_candidate_has_policy_v2_and_terminal_state_machine_hooks():
    source = (SCRIPTS / "round_trip_eval.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert '"--reliability_v11_consumer_mode"' in source
    assert '"--reliability_v11_integrated_promotion_mode"' in source
    assert '"--reliability_v11_integrated_anchor_state_mode"' in source
    assert '"--reliability_v11_integrated_anchor_state_policy"' in source
    assert (
        '"--reliability_v11_integrated_candidate_selector_mode"'
        in source
    )
    assert (
        '"--reliability_v11_integrated_candidate_controller_mode"'
        in source
    )
    assert (
        '"--reliability_v11_integrated_candidate_controller_active_armed"'
        in source
    )
    assert (
        "reliability_v11_integrated_candidate_controller_kill_switch_path"
        in source
    )
    assert "v11_candidate_transition_shadow=(" in source
    assert "_evaluate_v11_candidate_transition_shadow" in source
    assert "V11IntegratedCandidateControllerActiveV0" in source
    assert 'default="off"' in source
    for operation in (
        "anchor_promotion",
        "route_hint",
        "hint_action_override",
    ):
        assert operation in source or operation in (
            # Promotion executes inside RouteMemoryAgent.
            "anchor_promotion",
        )
    # Stop decisions no longer pass through the legacy generic consumer
    # operation.  The terminal state machine resolves Route-2 trust directly,
    # keeps running while navigation consumers are paused, and safe-fails when
    # its bounded blind budget is exhausted.
    assert "_stop_gate_evidence_trusted(" in source
    assert "home_visual_probe=" in source
    assert 'decision in {"accepted", "forced"}' in source
    assert 'decision == "safe_fail"' in source
    assert "and route_agent.route_consumers_enabled" not in source[
        source.index("# --- Terminal evidence state machine"):
        source.index("if _vlm_stop_requested:", source.index("# --- Terminal evidence state machine"))
    ]
    assert "v11_consumer_guard=" in source
    assert "v11_promotion_evidence_policy=" in source
    assert "V11IntegratedAnchorStateShadow" in source
    assert "v11_anchor_state_shadow.observe(decision)" in source
    assert "reliability_v11_consumer_v2.jsonl" in source
    assert "propose_hint(" in source
    assert "commit_hint_event(" in source
    assert '"--route_memory_capture_start_anchor_descriptor"' in source
    assert "initialize_start_anchor_descriptor(" in source


def _progress(anchor_index=3):
    return RelativeStartProgress(
        target_dx_m=1.0,
        target_dy_m=0.0,
        distance_to_start_m=2.0,
        bearing_to_start_deg=0.0,
        current_pose_from_start=[0.0, 0.0, 0.0],
        return_pose_from_return_start=[0.0, 0.0, 0.0],
        return_start_pose_from_start=[0.0, 0.0, 0.0],
        target_anchor_index=anchor_index,
        anchor_dx_m=1.0,
        anchor_dy_m=0.0,
        distance_to_anchor_m=1.0,
        bearing_to_anchor_deg=0.0,
        anchor_route_remaining_m=1.0,
        anchor_heading_reliable=True,
        relocalization_confidence=1.0,
    )


def test_hint_proposal_is_not_recorded_until_committed():
    agent = RouteMemoryAgent(enabled=True, hint_mode="compact")
    instruction, event = agent.propose_hint(
        "return to the start",
        100,
        progress_override=_progress(),
    )
    assert event is not None
    assert instruction.startswith("[System Hint:")
    assert agent.hint_events == []

    agent.commit_hint_event(event)
    assert agent.hint_events == [event]


def test_stale_hint_is_suppressed_before_consumer_proposal():
    agent = RouteMemoryAgent(
        enabled=True,
        hint_mode="compact",
        sequential_pair_report_next_anchor=True,
        sequential_pair_report_next_anchor_suppress_if_stale=True,
    )
    agent._next_candidate_update_seq = 7
    agent._next_candidate_seq_at_last_hint = 7

    instruction, event = agent.propose_hint(
        "return to the start",
        100,
        progress_override=_progress(),
    )
    assert instruction == "return to the start"
    assert event is None
    assert agent.hint_events == []
