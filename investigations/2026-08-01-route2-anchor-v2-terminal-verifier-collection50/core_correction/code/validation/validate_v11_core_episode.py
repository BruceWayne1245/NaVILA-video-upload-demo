#!/usr/bin/env python3
"""Validate one Route 2 capture against the V1.1 core contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from validation.validate_episode_capture import safe_child, sha256, validate as validate_capture


ARTIFACT_SHA256 = "3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a"
OPERATION_HEAD = {
    "anchor_promotion": "pose",
    "route_hint": "bearing",
    "hint_action_override": "bearing",
    "forced_stop": "distance",
    "vlm_stop_veto": "distance",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"non-object JSONL record at {path}:{line_number}")
        records.append(value)
    return records


def _completion_file(root: Path, completion: dict[str, Any], key: str) -> Path:
    entry = completion.get(key)
    if not isinstance(entry, dict):
        raise ValueError(f"completion manifest missing {key}")
    path = safe_child(root, str(entry.get("path", "")))
    if not path.is_file():
        raise FileNotFoundError(f"declared {key} missing: {path}")
    if sha256(path) != str(entry.get("sha256", "")):
        raise ValueError(f"{key} SHA256 mismatch")
    return path


def validate_v11_core(result_root: Path, expected_episode: int) -> dict[str, Any]:
    capture = validate_capture(result_root, expected_episode)
    root = result_root.resolve()
    completion = json.loads((root / "capture_completion.json").read_text(encoding="utf-8"))
    measurement_path = Path(capture["measurement"])
    measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
    round_trip = measurement.get("round_trip") or {}

    inference = round_trip.get("reliability_v11_inference")
    if not isinstance(inference, dict) or inference.get("enabled") is not True:
        raise ValueError("V1.1 online inference is not enabled")
    if inference.get("inference_role") != "route2_core_root":
        raise ValueError("V1.1 inference was not recorded as the Route 2 core root")
    if inference.get("consumer_mode") != "active":
        raise ValueError("V1.1 core consumer mode is not active")
    if int(inference.get("calls", 0)) <= 0 or int(inference.get("candidates", 0)) <= 0:
        raise ValueError("V1.1 produced no prospective scores")
    for field in ("runtime_exceptions", "shadow_exceptions", "nonfinite_outputs"):
        if int(inference.get(field, 0)) != 0:
            raise ValueError(f"V1.1 inference failure: {field}={inference.get(field)}")

    consumer = round_trip.get("reliability_v11_consumer_core")
    if not isinstance(consumer, dict) or consumer.get("enabled") is not True:
        raise ValueError("V1.1 core consumer is not enabled")
    policy = consumer.get("policy") or {}
    required_policy = {
        "schema": "navila-v11-consumer-policy-v3-core",
        "mode": "active",
        "enforcement_enabled": True,
        "root_model": "reliability_v1_1",
        "raw_icp_quality_authority": False,
        "candidate_flow": "preserve_reversible_candidates",
    }
    for field, expected in required_policy.items():
        if policy.get(field) != expected:
            raise ValueError(f"core policy mismatch: {field}={policy.get(field)!r}")
    if policy.get("operation_heads") != OPERATION_HEAD:
        raise ValueError("core policy operation/head mapping mismatch")
    if consumer.get("episode_disabled") is True:
        raise ValueError(f"core consumer entered invalid state: {consumer.get('disable_reason')}")

    inference_log = _completion_file(root, completion, "v11_shadow_log")
    inference_records = _jsonl(inference_log)
    starts = [row for row in inference_records if row.get("event") == "v11_shadow_session_start"]
    scores = [row for row in inference_records if row.get("event") == "v11_shadow_score"]
    if len(starts) != 1 or not scores:
        raise ValueError("V1.1 inference log lacks one start and at least one score")
    if starts[0].get("portable_artifact_sha256") != ARTIFACT_SHA256:
        raise ValueError("unexpected V1.1 portable artifact hash")
    if any(row.get("event") == "v11_shadow_exception" for row in inference_records):
        raise ValueError("V1.1 inference exception recorded")

    consumer_log = _completion_file(root, completion, "v11_consumer_core_log")
    consumer_records = _jsonl(consumer_log)
    if sum(row.get("event") == "v11_consumer_core_session_start" for row in consumer_records) != 1:
        raise ValueError("core consumer log must have exactly one session start")
    if sum(row.get("event") == "v11_consumer_core_session_end" for row in consumer_records) != 1:
        raise ValueError("core consumer log must have exactly one session end")
    forbidden_events = {"v11_core_invalid_safe_degradation"}
    if any(row.get("event") in forbidden_events for row in consumer_records):
        raise ValueError("core consumer recorded invalid-model safe degradation")

    decisions = [
        row for row in consumer_records
        if row.get("event") == "v11_consumer_v3_core_decision"
    ]
    for row in decisions:
        operation = str(row.get("operation"))
        expected_head = OPERATION_HEAD.get(operation)
        if expected_head is None:
            if operation != "relocalization_update":
                raise ValueError(f"undeclared core operation: {operation}")
            expected_field = None
        else:
            expected_field = f"{expected_head}_trusted"
        if row.get("trust_field_used") != expected_field:
            raise ValueError(f"wrong trust head for {operation}: {row.get('trust_field_used')}")
        if row.get("fail_open") is not False:
            raise ValueError(f"raw-confidence fail-open recorded for {operation}")
        if row.get("mode") != "active" or row.get("enforcement_enabled") is not True:
            raise ValueError(f"non-active consumer decision recorded for {operation}")
        if bool(row.get("executed_allow")) != bool(row.get("counterfactual_allow")):
            raise ValueError(f"active decision was not enforced for {operation}")
        if row.get("assessment_available") is True:
            for field in (
                "head_probability",
                "head_trusted",
                "reliability_envelope_id",
                "assessment_attempt",
                "assessment_step",
                "authority_anchor_index",
            ):
                if row.get(field) is None:
                    raise ValueError(f"decision lacks {field} for {operation}")

    return {
        **capture,
        "v11_artifact_sha256": ARTIFACT_SHA256,
        "v11_calls": int(inference["calls"]),
        "v11_candidates": int(inference["candidates"]),
        "consumer_decisions": len(decisions),
        "operation_counts": consumer.get("operation_counts", {}),
        "core_contract": "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_root", type=Path)
    parser.add_argument("expected_episode", type=int)
    args = parser.parse_args()
    try:
        result = validate_v11_core(args.result_root, args.expected_episode)
    except Exception as exc:
        print(f"[v11_core_integrity_fail] type={type(exc).__name__} error={exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
