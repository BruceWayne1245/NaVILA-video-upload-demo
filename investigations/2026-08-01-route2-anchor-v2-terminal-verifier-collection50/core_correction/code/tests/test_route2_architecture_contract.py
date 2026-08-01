import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "runtime_candidate" / "scripts" / "round_trip_eval.py"
STOP_GATE = ROOT / "runtime_candidate" / "scripts" / "stop_gate.py"


def test_evaluator_uses_core_guard_and_distance_head_for_terminal():
    source = EVALUATOR.read_text()
    assert "V11ConsumerGuardV3" in source
    assert '"vlm_stop_veto"' in source
    assert '"forced_stop"' in source
    assert "v11_consumer_guard.evaluate(" in source
    policy = (ROOT / "reliability" / "v11_consumer_policy_v3.py").read_text()
    assert '"forced_stop": "distance"' in policy
    assert '"vlm_stop_veto": "distance"' in policy
    assert "V11ConsumerGuardV2.load" not in source


def test_stop_gate_does_not_upgrade_raw_confidence_to_authority():
    source = STOP_GATE.read_text()
    assert "Confidence alone never upgrades an ICP reading" in source
    assert "if evidence_trusted is not True:" in source


def test_contract_forbids_legacy_and_raw_quality_authority():
    contract = json.loads(
        (ROOT / "config" / "route2_consumer_contract_v1.json").read_text()
    )
    assert contract["root_model"] == "reliability_v1_1"
    assert contract["raw_icp_quality_authority"] is False
    assert contract["legacy_u_authority"] is False
    assert contract["preserve_reversible_relocalization"] is True
