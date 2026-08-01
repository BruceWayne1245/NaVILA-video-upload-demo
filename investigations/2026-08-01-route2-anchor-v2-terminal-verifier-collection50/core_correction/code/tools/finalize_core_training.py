#!/usr/bin/env python3
"""Audit, compare and freeze the three cleaned Route 2 model artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import joblib


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.v11_core_downstream_features import (
    assert_core_compliant,
    is_forbidden_raw_quality_feature,
    is_v11_feature,
    is_v11_feature_for_head,
)


SOURCE_ROOT = Path("/home/teambruce/navila-anchor-terminal-training-data-20260729")
ARTIFACTS = {
    "anchor_transition": ROOT / "models/core_v1/anchor_transition_core_v1.joblib",
    "terminal_decision": ROOT / "models/core_v1/terminal_decision_core_v1.joblib",
    "hint_action": ROOT / "models/core_v1/hint_action_core_v1.joblib",
}
NEW_REPORTS = {
    "anchor_transition": ROOT / "reports/core_v1/anchor/training_report.json",
    "terminal_decision": ROOT / "reports/core_v1/terminal_report.json",
    "hint_action": ROOT / "reports/core_v1/hint_report.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_report(task: str) -> dict[str, Any]:
    value = json.loads(NEW_REPORTS[task].read_text(encoding="utf-8"))
    if task == "anchor_transition":
        return value["tasks"][task]
    return value


def old_summary() -> dict[str, Any]:
    v1 = json.loads(
        (SOURCE_ROOT / "reports/v1/training_report.json").read_text(encoding="utf-8")
    )["tasks"]["anchor_transition"]
    terminal = json.loads(
        (SOURCE_ROOT / "reports/v2/terminal_v2_robust_report.json").read_text(encoding="utf-8")
    )
    hint = json.loads(
        (SOURCE_ROOT / "reports/v2/hint_action_v2_binary_report.json").read_text(encoding="utf-8")
    )
    return {
        "anchor_transition": {
            "features": v1["feature_count"],
            "test_balanced_accuracy": v1["metrics"]["test"]["balanced_accuracy"],
        },
        "terminal_decision": {
            "features": terminal["feature_count"],
            "test_balanced_accuracy": terminal["metrics"]["test"]["balanced_accuracy"],
            "test_arrived_recall": terminal["sequence_policy"]["test"]["arrived_recall"],
            "test_true_far_false_arrived": terminal["sequence_policy"]["test"]["true_far_false_arrived"],
        },
        "hint_action": {
            "features": hint["feature_count"],
            "test_balanced_accuracy": hint["metrics"]["test"]["balanced_accuracy"],
            "test_average_precision": hint["average_precision"]["test"],
        },
    }


def new_metrics(task: str, report: dict[str, Any]) -> dict[str, Any]:
    if task == "anchor_transition":
        return {
            "features": report["feature_count"],
            "test_balanced_accuracy": report["metrics"]["test"]["balanced_accuracy"],
            "validation_balanced_accuracy": report["metrics"]["validation"]["balanced_accuracy"],
        }
    if task == "terminal_decision":
        return {
            "features": report["feature_count"],
            "test_balanced_accuracy": report["metrics"]["test"]["balanced_accuracy"],
            "test_arrived_recall": report["sequence_policy"]["test"]["arrived_recall"],
            "test_true_far_false_arrived": report["sequence_policy"]["test"]["true_far_false_arrived"],
            "development_arrived_recall": report["sequence_policy"]["development_oof"]["arrived_recall"],
        }
    return {
        "features": report["feature_count"],
        "test_balanced_accuracy": report["metrics"]["test"]["balanced_accuracy"],
        "test_average_precision": report["average_precision"]["test"],
        "test_execution_precision": report["execution_policy"]["test"]["precision"],
        "test_execution_recall": report["execution_policy"]["test"]["recall"],
    }


def main() -> None:
    old = old_summary()
    audit: dict[str, Any] = {
        "schema": "navila-route2-core-training-audit-v1",
        "source_split_contract": {
            "train_scenes": 7,
            "validation_scenes": ["EU6Fwq7SyZv"],
            "test_scenes": ["zsNo4HB9uLZ"],
            "scene_disjoint": True,
        },
        "artifacts": {},
        "training_source_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted((ROOT / "training/core_v1_src").glob("*.py"))
        },
        "feature_firewall_sha256": sha256(
            ROOT / "training/v11_core_downstream_features.py"
        ),
    }
    for task, path in ARTIFACTS.items():
        bundle = joblib.load(path)
        report = load_report(task)
        names = list(bundle["feature_names"])
        head = str(bundle["required_v11_head"])
        if bundle.get("schema") != "navila-route2-core-downstream-bundle-v1":
            raise RuntimeError(f"wrong core schema for {task}")
        if bundle.get("raw_icp_quality_authority") is not False:
            raise RuntimeError(f"raw ICP authority not disabled for {task}")
        if bundle.get("legacy_u_authority") is not False:
            raise RuntimeError(f"legacy U authority not disabled for {task}")
        if bundle.get("integration_status") != "shadow_only" and (
            bundle.get("scope") or {}
        ).get("integration_status") != "shadow_only":
            raise RuntimeError(f"new artifact is not locked shadow-only: {task}")
        assert_core_compliant(
            {name: 0.0 for name in names}, required_head=head
        )
        forbidden = [name for name in names if is_forbidden_raw_quality_feature(name)]
        wrong_head = [
            name for name in names
            if is_v11_feature(name) and not is_v11_feature_for_head(name, head)
        ]
        matching = [
            name for name in names
            if is_v11_feature(name) and is_v11_feature_for_head(name, head)
        ]
        if forbidden or wrong_head or not matching:
            raise RuntimeError(f"feature firewall audit failed for {task}")
        current = new_metrics(task, report)
        comparisons = {
            key: current[key] - old[task][key]
            for key in current.keys() & old[task].keys()
            if isinstance(current[key], (int, float))
            and isinstance(old[task][key], (int, float))
        }
        audit["artifacts"][task] = {
            "path": str(path),
            "sha256": sha256(path),
            "schema": bundle["schema"],
            "required_v11_head": head,
            "feature_count": len(names),
            "matching_v11_feature_count": len(matching),
            "raw_icp_quality_proxy_count": len(forbidden),
            "wrong_v11_head_feature_count": len(wrong_head),
            "integration_status": "shadow_only",
            "old": old[task],
            "new": current,
            "new_minus_old": comparisons,
        }

    output = ROOT / "reports/core_v1/core_training_audit.json"
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
