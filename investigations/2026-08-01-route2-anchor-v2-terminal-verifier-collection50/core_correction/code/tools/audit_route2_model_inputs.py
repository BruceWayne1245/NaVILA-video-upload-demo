#!/usr/bin/env python3
"""Audit frozen Route 2 downstream artifacts for V1.1 and raw quality inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import joblib


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from training.v11_core_downstream_features import (  # noqa: E402
    is_forbidden_raw_quality_feature,
)

DEFAULT_ARTIFACTS = {
    "anchor_transition_v1": Path(
        "/home/teambruce/navila-anchor-terminal-training-data-20260729/"
        "models/v1/anchor_transition_v1.joblib"
    ),
    "terminal_v2_robust": Path(
        "/home/teambruce/navila-anchor-terminal-training-data-20260729/"
        "models/v2/terminal_decision_v2_robust.joblib"
    ),
    "hint_binary_v2": Path(
        "/home/teambruce/navila-anchor-terminal-training-data-20260729/"
        "models/v2/hint_action_decision_v2_binary.joblib"
    ),
}
def classify(features: list[str]) -> dict:
    v11 = [
        name
        for name in features
        if ".v11." in name
        or "candidate_agg.p_pose_bad" in name
        or "pose_trusted_fraction" in name
    ]
    raw = [
        name
        for name in features
        if name not in v11 and is_forbidden_raw_quality_feature(name)
    ]
    return {
        "feature_count": len(features),
        "v11_feature_count": len(v11),
        "raw_quality_proxy_count": len(raw),
        "core_compliant": bool(v11) and not raw,
        "v11_features": v11,
        "raw_quality_proxies": raw,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "schema": "navila-route2-model-input-audit-v1",
        "route1_assets_in_scope": False,
        "artifacts": {},
    }
    for name, path in DEFAULT_ARTIFACTS.items():
        bundle = joblib.load(path)
        features = list(bundle.get("feature_names") or [])
        report["artifacts"][name] = {
            "path": str(path),
            "schema": bundle.get("schema"),
            **classify(features),
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
