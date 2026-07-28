import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STOP_GATE_PATH = (
    ROOT / "policy_v2_live_candidate" / "scripts" / "stop_gate.py"
)
spec = importlib.util.spec_from_file_location(
    "terminal_stop_gate_candidate",
    STOP_GATE_PATH,
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ReturnStopGate = module.ReturnStopGate


class Progress:
    def __init__(
        self,
        distance,
        *,
        role="next",
        kind="raw_icp",
        age=0,
        confidence=0.95,
        source="anchor_relocalization",
        hops=0,
    ):
        self.distance_to_start_m = float(distance)
        self.relocalization_confidence = float(confidence)
        self.filter_std_m = None
        self.source = source
        self.estimate_role = role
        self.estimate_kind = kind
        self.estimate_edge_hop_count = int(hops)
        self.evidence_age_updates = age


def gate(**kwargs):
    return ReturnStopGate(
        r_in=3.0,
        r_out=3.0,
        accept_confirm_steps=2,
        confirm_steps=3,
        verify_queries=2,
        blind_max_queries=3,
        visual_confirm_steps=2,
        **kwargs,
    )


def test_fresh_trusted_next_near_requires_two_queries_then_accepts():
    subject = gate()
    progress = Progress(1.0)

    first = subject.check(
        progress,
        vlm_issued_stop=True,
        evidence_trusted=True,
    )
    second = subject.check(
        progress,
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert first.decision == "verifying"
    assert first.suggested_command == [0.0, 0.0, 0.0]
    assert second.decision == "accepted"
    assert second.evidence_authority == "trusted_next_raw"


def test_untrusted_near_reading_never_accepts_stop():
    subject = gate()
    decision = subject.check(
        Progress(0.2),
        vlm_issued_stop=True,
        evidence_trusted=False,
    )

    assert decision.decision == "verifying"
    assert decision.evidence_authority == "untrusted"
    assert not decision.terminal


def test_trusted_current_rear_support_has_no_terminal_authority():
    subject = gate()
    progress = Progress(0.2, role="current")

    first = subject.check(
        progress,
        vlm_issued_stop=True,
        evidence_trusted=True,
    )
    second = subject.check(
        progress,
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert first.decision == "verifying"
    assert second.decision == "resume"
    assert second.state == "terminal_blind"
    assert second.evidence_authority == "rear_current_no_terminal_authority"


def test_stale_trusted_next_cannot_accept_or_veto():
    subject = gate(max_evidence_age_updates=25)
    stale_near = subject.check(
        Progress(0.2, age=26),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert stale_near.decision == "verifying"
    assert stale_near.evidence_authority == "stale"


def test_fresh_trusted_far_rejects_stop_without_bearing_motion():
    subject = gate()
    decision = subject.check(
        Progress(5.0),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert decision.decision == "resume"
    assert decision.suggested_command == [0.0, 0.0, 0.0]
    assert decision.state == "navigating"
    assert not decision.navigation_paused


def test_bounded_reconstruction_can_reject_far_but_not_accept_near():
    far_subject = gate()
    far = far_subject.check(
        Progress(
            5.0,
            kind="geometry_reconstructed",
            hops=1,
        ),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )
    near_subject = gate()
    near = near_subject.check(
        Progress(
            0.2,
            kind="geometry_reconstructed",
            hops=1,
        ),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert far.decision == "resume"
    assert far.evidence_authority == "trusted_bounded_reconstruction"
    assert near.decision == "verifying"
    assert not near.terminal


def test_multihop_reconstruction_has_no_terminal_authority():
    subject = gate(max_reconstructed_edge_hops=1)
    decision = subject.check(
        Progress(
            8.0,
            kind="geometry_reconstructed",
            hops=2,
        ),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert decision.decision == "verifying"
    assert decision.evidence_authority == "reconstruction_out_of_bounds"


def test_repeated_a0_visual_plus_vlm_stop_can_accept_without_icp():
    subject = gate()

    first = subject.check(
        None,
        vlm_issued_stop=True,
        home_visual_probe=lambda: True,
    )
    second = subject.check(
        None,
        vlm_issued_stop=True,
        home_visual_probe=lambda: True,
    )

    assert first.decision == "verifying"
    assert second.decision == "accepted"
    assert second.evidence_authority == "a0_rgbd_plus_repeated_vlm_stop"


def test_missing_all_signals_exhausts_blind_budget_as_safe_fail():
    subject = gate()

    decisions = [
        subject.check(None, vlm_issued_stop=True)
        for _ in range(4)
    ]

    assert [decision.decision for decision in decisions] == [
        "verifying",
        "resume",
        "resume",
        "safe_fail",
    ]
    assert decisions[-1].state == "safe_fail"
    assert decisions[-1].reason == (
        "blind_probe_budget_exhausted_without_terminal_evidence"
    )


def test_last_trusted_distance_envelope_can_only_disprove_arrival():
    subject = gate()
    subject.notify_sim_step([0.0, 0.0, 0.0])
    subject.check(
        Progress(8.0),
        vlm_issued_stop=False,
        evidence_trusted=True,
    )
    subject.notify_sim_step([0.5, 0.0, 0.0])

    decision = subject.check(
        None,
        vlm_issued_stop=True,
        evidence_trusted=None,
    )

    assert decision.decision == "resume"
    assert decision.evidence_authority == "last_trusted_motion_envelope"
    assert decision.distance_interval_m[0] > 3.0


def test_far_last_trusted_envelope_still_has_bounded_blind_budget():
    subject = gate()
    subject.notify_sim_step([0.0, 0.0, 0.0])
    subject.check(
        Progress(10.0),
        vlm_issued_stop=False,
        evidence_trusted=True,
    )

    decisions = [
        subject.check(None, vlm_issued_stop=True)
        for _ in range(4)
    ]

    assert decisions[-1].decision == "safe_fail"


def test_large_motion_makes_last_trusted_envelope_unknown_not_near():
    subject = gate()
    subject.notify_sim_step([0.0, 0.0, 0.0])
    subject.check(
        Progress(5.0),
        vlm_issued_stop=False,
        evidence_trusted=True,
    )
    for x in (1.0, 2.0, 3.0, 4.0):
        subject.notify_sim_step([x, 0.0, 0.0])

    decision = subject.check(None, vlm_issued_stop=True)

    assert decision.decision == "verifying"
    assert not decision.terminal


def test_fresh_trusted_next_can_force_only_after_near_streak():
    subject = gate()
    progress = Progress(1.0)

    decisions = [
        subject.check(
            progress,
            vlm_issued_stop=False,
            evidence_trusted=True,
        )
        for _ in range(3)
    ]

    assert [decision.decision for decision in decisions] == [
        "pass",
        "pass",
        "forced",
    ]


def test_current_anchor_never_forces_even_when_trusted_and_near():
    subject = gate()
    progress = Progress(0.1, role="current")

    decisions = [
        subject.check(
            progress,
            vlm_issued_stop=False,
            evidence_trusted=True,
        )
        for _ in range(5)
    ]

    assert all(decision.decision == "pass" for decision in decisions)


def test_teleport_stop_is_held_and_does_not_pass_through():
    subject = gate()
    subject.notify_sim_step([0.0, 0.0, 0.0])
    subject.notify_sim_step([10.0, 0.0, 0.0])

    decision = subject.check(
        Progress(0.1),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )

    assert decision.decision == "verifying"
    assert decision.is_teleport_frame
    assert decision.suggested_command == [0.0, 0.0, 0.0]


def test_blind_prompt_explicitly_forbids_unverified_stop():
    subject = gate()
    subject.check(None, vlm_issued_stop=True)
    subject.check(None, vlm_issued_stop=True)

    prompt = subject.prompt_suffix()
    assert "Do not stop solely from route numbers" in prompt
    assert "probes A0" in prompt


def test_log_contains_state_authority_interval_and_reason():
    subject = gate()
    decision = subject.check(
        Progress(5.0),
        vlm_issued_stop=True,
        evidence_trusted=True,
    )
    record = decision.as_log_dict()

    assert record["gate_state"] == "navigating"
    assert record["gate_evidence_authority"] == "trusted_next_raw"
    assert record["gate_distance_interval_m"] == [4.65, 5.35]
    assert record["gate_reason"]
