from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = (
    ROOT / "runtime_candidate/scripts/round_trip_eval.py"
).read_text(encoding="utf-8")
AGENT = (
    ROOT / "runtime_candidate/scripts/route_memory_agent.py"
).read_text(encoding="utf-8")


def test_guard_is_default_off_and_requires_explicit_active_arm():
    assert '"--anchor_transition_guard_mode"' in EVALUATOR
    assert 'choices=("off", "shadow", "active")' in EVALUATOR
    assert 'default="off"' in EVALUATOR
    assert "anchor_transition_guard_active_armed" in EVALUATOR
    assert "anchor_transition_guard_kill_switch_path" in EVALUATOR


def test_complete_attempt_is_observed_after_controller_snapshot():
    snapshot = EVALUATOR.index(
        "v11_shadow_session.record_controller_snapshot("
    )
    observation = EVALUATOR.index(
        "anchor_transition_online.observe_complete_attempt("
    )
    reset = EVALUATOR.index("v11_shadow_last_attempt = None", snapshot)
    assert snapshot < observation < reset


def test_route_agent_forbids_guard_from_creating_promotion():
    assert "anchor_transition_promotion_guard" in AGENT
    assert "guard cannot create a promotion" in AGENT


def test_anchor_runtime_uses_unique_package_not_v11_reliability_namespace():
    assert "from anchor_transition_runtime import (" in EVALUATOR
    assert "from reliability.anchor_transition_online import (" not in EVALUATOR
