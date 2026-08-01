import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_core_training_audit_has_no_reliability_bypass():
    audit = json.loads(
        (ROOT / "reports/core_v1/core_training_audit.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "anchor_transition": "pose",
        "terminal_decision": "distance",
        "hint_action": "bearing",
    }
    for model, head in expected.items():
        item = audit["artifacts"][model]
        assert item["required_v11_head"] == head
        assert item["matching_v11_feature_count"] > 0
        assert item["raw_icp_quality_proxy_count"] == 0
        assert item["wrong_v11_head_feature_count"] == 0
        assert item["integration_status"] == "shadow_only"


def test_cohorts_are_frozen_and_role_separated():
    lock = json.loads(
        (ROOT / "config/route2_core_cohort_lock_v1.json").read_text(
            encoding="utf-8"
        )
    )
    dev_path = ROOT / "manifest/route2_core_development24.tsv"
    val_path = ROOT / "manifest/route2_core_locked_validation20.tsv"
    dev = rows(dev_path)
    val = rows(val_path)
    assert len(dev) == 24 and len(val) == 20
    assert {row["cohort_role"] for row in dev} == {"training_development"}
    assert {row["cohort_role"] for row in val} == {"locked_validation"}
    assert len({row["scene"] for row in dev}) == 9
    assert len({row["scene"] for row in val}) == 4
    assert not ({row["episode_idx"] for row in dev} & {row["episode_idx"] for row in val})
    assert lock["development"]["manifest_sha256"] == digest(dev_path)
    assert lock["locked_validation"]["manifest_sha256"] == digest(val_path)
    assert lock["state"] == "sealed_before_execution"
    assert lock["execution_authorized"] is False
    assert lock["queue_authorized"] is False
    assert lock["current_50_control_effect"] == "none"
    for key, value in lock["locked_validation"].items():
        if key.endswith("overlap"):
            assert value == 0
    assert lock["locked_validation"]["may_enter_future_training"] is False
    assert lock["locked_validation"]["may_tune_thresholds"] is False


def test_locked_evidence_is_fresh_and_route_pair_disjoint():
    evidence = rows(ROOT / "manifest/route2_core_cohort_evidence.tsv")
    dev = [row for row in evidence if row["cohort_role"] == "training_development"]
    val = [row for row in evidence if row["cohort_role"] == "locked_validation"]
    assert not ({row["route_pair_sha256"] for row in dev} & {row["route_pair_sha256"] for row in val})
    for row in val:
        assert row["old_training_overlap"] == "False"
        assert row["current50_overlap"] == "False"
        assert row["historical_attempt_overlap"] == "False"
        assert row["selection_reason"] == "sealed_fresh_physical_id_and_geometry"


def test_launcher_cannot_implicitly_launch_or_queue():
    launcher = (ROOT / "launch/run_route2_core_cohort.sh").read_text(
        encoding="utf-8"
    )
    assert "--launch-development" in launcher
    assert "--launch-locked-validation" in launcher
    assert "static_preflight" in launcher
    assert "refusing overlap. Nothing was stopped or queued" in launcher
    assert "--reliability_v11_core_mode=active" in launcher
    assert "--anchor_transition_guard_mode=shadow" in launcher
    assert "--reliability_v11_consumer_mode=off" not in launcher.split(
        "for forbidden", 1
    )[0]
