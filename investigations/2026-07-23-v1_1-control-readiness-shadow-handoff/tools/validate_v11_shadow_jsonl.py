#!/usr/bin/env python3
"""Validate one online V1.1 shadow JSONL log and optional measurement replay."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CANDIDATE = ROOT / "candidate" / "scripts"
if str(CANDIDATE) not in sys.path:
    sys.path.insert(0, str(CANDIDATE))

from reliability.v11_runtime import (
    CausalV11FeatureBuilder,
    V11DecisionShadowPolicy,
)
from reliability_v11_portable_runtime import PortableV11Bundle


PROBABILITY_FIELDS = (
    "p_bearing_bad_30",
    "p_distance_bad_0p5",
    "p_pose_bad",
)
TRUST_FIELDS = (
    "bearing_trusted",
    "distance_trusted",
    "pose_trusted",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shadow_log")
    parser.add_argument("--measurement")
    parser.add_argument(
        "--portable",
        default=str(ROOT / "artifacts" / "reliability_v1_1_portable_shadow.json"),
    )
    parser.add_argument(
        "--policy",
        default=str(ROOT / "configs" / "v11_decision_shadow_v1.json"),
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    events = [
        json.loads(line)
        for line in Path(args.shadow_log).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    starts = [event for event in events if event.get("event") == "v11_shadow_session_start"]
    scores = [event for event in events if event.get("event") == "v11_shadow_score"]
    exceptions = [event for event in events if event.get("event") == "v11_shadow_exception"]
    snapshots = [
        event for event in events
        if event.get("event") == "v11_shadow_controller_snapshot"
    ]
    decisions = [
        event for event in events
        if event.get("event") == "v11_shadow_decision"
    ]
    decision_exceptions = [
        event for event in events
        if event.get("event") == "v11_shadow_decision_exception"
    ]
    ends = [event for event in events if event.get("event") == "v11_shadow_session_end"]
    portable = PortableV11Bundle.load(args.portable, mode="shadow")
    decision_policy = V11DecisionShadowPolicy.load(args.policy)

    rows = []
    duplicate_keys = 0
    seen_keys = set()
    nonfinite_probabilities = 0
    feature_width_failures = 0
    control_contract_failures = 0
    rescore_max_difference = {field: 0.0 for field in PROBABILITY_FIELDS}
    rescore_trust_mismatches = {field: 0 for field in TRUST_FIELDS}
    for event in scores:
        control_contract_failures += int(
            event.get("enforcement_enabled") is not False
            or event.get("controller_effect") is not False
        )
        for output in event.get("outputs", []):
            key = (
                int(output["attempt"]),
                int(output["anchor_index"]),
            )
            duplicate_keys += int(key in seen_keys)
            seen_keys.add(key)
            features = output.get("features", {})
            feature_width_failures += int(len(features) != len(portable.feature_names))
            expected = portable.predict_features(features)
            for field in PROBABILITY_FIELDS:
                value = float(output[field])
                nonfinite_probabilities += int(not math.isfinite(value))
                rescore_max_difference[field] = max(
                    rescore_max_difference[field],
                    abs(value - float(getattr(expected, field))),
                )
            for field in TRUST_FIELDS:
                rescore_trust_mismatches[field] += int(
                    bool(output[field]) != bool(getattr(expected, field))
                )
            control_contract_failures += int(output.get("enforced") is not False)
            rows.append(output)

    decision_shadow_enabled = bool(
        len(starts) == 1 and starts[0].get("decision_shadow_enabled") is True
    )
    decision_contract_failures = 0
    for event in decisions:
        policy = event.get("policy", {})
        counterfactual = event.get("counterfactual", {})
        posthoc = event.get("posthoc_ground_truth", {})
        candidate_count = len(event.get("candidate_assessments", []))
        baseline = event.get("baseline", {})
        reconstructed_event = (
            {
                "accepted": True,
                "anchor_index": baseline.get("selected_anchor_index"),
                "backend": baseline.get("controller_backend"),
            }
            if baseline.get("controller_accepted") is True else None
        )
        expected_decision = decision_policy.evaluate(
            event.get("candidate_assessments", []),
            accepted_event=reconstructed_event,
            target_anchor_index=baseline.get("target_anchor_index"),
        )
        plan_fields = (
            "action",
            "integration_point",
            "input_anchor_indices",
            "forwarded_anchor_indices",
            "would_change_candidate_set",
            "would_defer_entire_relocalization_update",
            "current_anchor_index",
            "current_jointly_trusted",
            "next_anchor_index",
            "next_jointly_trusted",
            "identity_override_authorized",
        )
        plan_mismatch = any(
            counterfactual.get(field)
            != expected_decision["counterfactual"].get(field)
            for field in plan_fields
        )
        decision_contract_failures += int(
            event.get("physical_episode_id") is None
            or not event.get("scene_id")
            or event.get("mode") != "shadow"
            or event.get("observation_only") is not True
            or event.get("activation_approved") is not False
            or event.get("enforcement_enabled") is not False
            or event.get("controller_effect") is not False
            or policy.get("mode") != "shadow"
            or policy.get("enforcement_approved") is not False
            or policy.get("identity_override_authorized") is not False
            or counterfactual.get("identity_override_authorized") is not False
            or counterfactual.get("alternate_is_advisory_only") is not True
            or counterfactual.get("integration_point")
            != "filter_raw_candidates_before_route_memory_agent"
            or posthoc.get("used_for_features") is not False
            or posthoc.get("used_for_scoring") is not False
            or posthoc.get("used_for_decision") is not False
            or int(posthoc.get("available_rows", -1)) != candidate_count
            or int(posthoc.get("missing_rows", -1)) != 0
            or (policy.get("policy_sha256") != decision_policy.policy_sha256)
            or plan_mismatch
        )
    control_contract_failures += decision_contract_failures

    measurement_rows = None
    feature_mismatch_rows = None
    missing_logged_keys = None
    extra_logged_keys = None
    if args.measurement:
        measurement = json.loads(Path(args.measurement).read_text(encoding="utf-8"))
        records = (
            measurement.get("round_trip", {})
            .get("route_relocalization_diagnostics", {})
            .get("covisibility_records", [])
        )
        by_attempt = defaultdict(list)
        for record in records:
            by_attempt[int(record["attempt"])].append(record)
        episode_key = str(starts[0]["episode_key"]) if len(starts) == 1 else "invalid"
        builder = CausalV11FeatureBuilder(portable.feature_names)
        builder.start_episode(episode_key)
        expected_vectors = {}
        for attempt in sorted(by_attempt):
            for candidate in builder.build_attempt(
                episode_key, attempt, by_attempt[attempt]
            ):
                expected_vectors[(attempt, candidate.anchor_index)] = np.asarray(
                    portable.vector_from_mapping(candidate.features),
                    dtype=np.float32,
                )
        logged_vectors = {
            (int(row["attempt"]), int(row["anchor_index"])): np.asarray(
                portable.vector_from_mapping(row["features"]),
                dtype=np.float32,
            )
            for row in rows
        }
        common = expected_vectors.keys() & logged_vectors.keys()
        feature_mismatch_rows = sum(
            not np.array_equal(
                expected_vectors[key],
                logged_vectors[key],
                equal_nan=True,
            )
            for key in common
        )
        missing_logged_keys = len(expected_vectors.keys() - logged_vectors.keys())
        extra_logged_keys = len(logged_vectors.keys() - expected_vectors.keys())
        measurement_rows = len(expected_vectors)

    contract_passed = bool(
        len(starts) == 1
        and len(ends) == 1
        and not exceptions
        and len(scores) == len(snapshots)
        and (
            not decision_shadow_enabled
            or len(decisions) == len(snapshots)
        )
        and not decision_exceptions
        and duplicate_keys == 0
        and nonfinite_probabilities == 0
        and feature_width_failures == 0
        and control_contract_failures == 0
        and max(rescore_max_difference.values(), default=0.0) <= 1e-15
        and sum(rescore_trust_mismatches.values()) == 0
        and (feature_mismatch_rows in (None, 0))
        and (missing_logged_keys in (None, 0))
        and (extra_logged_keys in (None, 0))
    )
    evaluable = bool(rows)
    status = (
        "passed"
        if contract_passed and evaluable
        else "not_evaluable_no_score_rows"
        if contract_passed
        else "failed"
    )
    report = {
        "status": status,
        "passed": (
            True if status == "passed"
            else None if status == "not_evaluable_no_score_rows"
            else False
        ),
        "contract_passed": contract_passed,
        "evaluable": evaluable,
        "events": len(events),
        "score_calls": len(scores),
        "controller_snapshots": len(snapshots),
        "decision_shadow_enabled": decision_shadow_enabled,
        "decisions": len(decisions),
        "decision_exceptions": len(decision_exceptions),
        "decision_contract_failures": decision_contract_failures,
        "rows": len(rows),
        "exceptions": len(exceptions),
        "duplicate_keys": duplicate_keys,
        "nonfinite_probabilities": nonfinite_probabilities,
        "feature_width_failures": feature_width_failures,
        "control_contract_failures": control_contract_failures,
        "rescore_maximum_probability_difference": rescore_max_difference,
        "rescore_trusted_mismatches": rescore_trust_mismatches,
        "measurement_rows": measurement_rows,
        "feature_mismatch_rows": feature_mismatch_rows,
        "missing_logged_keys": missing_logged_keys,
        "extra_logged_keys": extra_logged_keys,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if status != "failed" else 1)


if __name__ == "__main__":
    main()
