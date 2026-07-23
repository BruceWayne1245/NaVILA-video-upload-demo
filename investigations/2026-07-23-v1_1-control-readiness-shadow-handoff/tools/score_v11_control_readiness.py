#!/usr/bin/env python3
"""Score whether V1.1's frozen role-safe consumer mapping is activation-ready."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.v11_runtime import V11DecisionShadowPolicy


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _episode_balanced_weights(rows: list[dict[str, Any]]) -> list[float]:
    counts = Counter(int(row["episode_id"]) for row in rows)
    return [1.0 / counts[int(row["episode_id"])] for row in rows]


def _weighted_rate(
    rows: list[dict[str, Any]],
    weights: list[float],
    numerator,
    denominator=lambda row: True,
) -> float | None:
    denominator_weight = sum(
        weight
        for row, weight in zip(rows, weights)
        if denominator(row)
    )
    if denominator_weight <= 0.0:
        return None
    return sum(
        weight
        for row, weight in zip(rows, weights)
        if denominator(row) and numerator(row)
    ) / denominator_weight


def _cluster_risk_ucb(
    rows: list[dict[str, Any]],
    *,
    label: str,
    samples: int,
    seed: int,
) -> float | None:
    by_episode: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_episode[int(row["episode_id"])].append(row)
    episodes = sorted(by_episode)
    if not episodes:
        return None
    per_episode = {}
    for episode in episodes:
        values = by_episode[episode]
        forwarded = [row for row in values if row["forwarded"]]
        per_episode[episode] = (
            sum(int(row[label]) for row in forwarded),
            len(forwarded),
            len(values),
        )
    rng = random.Random(seed)
    risks = []
    for _ in range(samples):
        bad_weight = 0.0
        forwarded_weight = 0.0
        for _draw in episodes:
            episode = episodes[rng.randrange(len(episodes))]
            bad, forwarded, total = per_episode[episode]
            if total:
                bad_weight += bad / total
                forwarded_weight += forwarded / total
        if forwarded_weight > 0.0:
            risks.append(bad_weight / forwarded_weight)
    if not risks:
        return None
    risks.sort()
    return risks[min(int(math.ceil(0.95 * len(risks))) - 1, len(risks) - 1)]


def _longest_full_defer_streaks(
    decisions: list[dict[str, Any]],
) -> dict[int, int]:
    by_episode: dict[int, list[tuple[int, bool]]] = defaultdict(list)
    for decision in decisions:
        by_episode[int(decision["physical_episode_id"])].append((
            int(decision["attempt"]),
            bool(
                decision["counterfactual"][
                    "would_defer_entire_relocalization_update"
                ]
            ),
        ))
    result = {}
    for episode, values in by_episode.items():
        values.sort()
        longest = current = 0
        previous_attempt = None
        for attempt, deferred in values:
            if deferred and (
                previous_attempt is None or attempt == previous_attempt + 1
            ):
                current += 1
            elif deferred:
                current = 1
            else:
                current = 0
            longest = max(longest, current)
            previous_attempt = attempt
        result[episode] = longest
    return result


def _quantile(values: list[int], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return float(ordered[low])
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _validate_completion_manifests(
    paths: list[str],
) -> tuple[dict[str, Any], set[int]]:
    failures = []
    episodes = set()
    duplicate_episode_manifests = 0
    for source_text in paths:
        source = Path(source_text)
        try:
            manifest = _load_json(source)
        except Exception as exc:
            failures.append({"path": str(source), "error": str(exc)})
            continue
        episode = manifest.get("physical_episode_id")
        if episode is not None:
            duplicate_episode_manifests += int(int(episode) in episodes)
            episodes.add(int(episode))
        if (
            manifest.get("schema") != "navila-v11-capture-completion-v1"
            or manifest.get("complete") is not True
        ):
            failures.append({"path": str(source), "error": "not_complete"})
            continue
        for key in ("trajectory", "measurement"):
            item = manifest.get(key) or {}
            path = source.parent / str(item.get("path") or "")
            if not path.is_file():
                failures.append({
                    "path": str(source),
                    "error": f"missing_{key}",
                })
            elif _sha256(path) != item.get("sha256"):
                failures.append({
                    "path": str(source),
                    "error": f"hash_mismatch_{key}",
                })
        shadow = manifest.get("v11_shadow_log")
        if shadow:
            path = source.parent / str(shadow.get("path") or "")
            if not path.is_file() or _sha256(path) != shadow.get("sha256"):
                failures.append({
                    "path": str(source),
                    "error": "shadow_log_missing_or_hash_mismatch",
                })
    return {
        "manifests": len(paths),
        "unique_physical_episodes": len(episodes),
        "duplicate_episode_manifests": duplicate_episode_manifests,
        "failures": failures,
    }, episodes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shadow_logs", nargs="+")
    parser.add_argument("--completion-manifests", nargs="+", required=True)
    parser.add_argument("--offline-row-predictions-csv", required=True)
    parser.add_argument(
        "--policy",
        default=str(ROOT / "configs" / "v11_decision_shadow_v1.json"),
    )
    parser.add_argument(
        "--gates",
        default=str(
            Path(__file__).resolve().parents[1]
            / "configs"
            / "v11_control_readiness_gates_v1.json"
        ),
    )
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--output")
    args = parser.parse_args()

    gates = _load_json(args.gates)
    policy = V11DecisionShadowPolicy.load(args.policy)
    completion, completed_episodes = _validate_completion_manifests(
        args.completion_manifests
    )
    decisions = []
    contract_failures = []
    exceptions = 0
    policy_hashes = set()
    artifact_hashes = set()
    session_episodes = set()
    duplicate_keys = 0
    seen_keys = set()

    for source_text in args.shadow_logs:
        source = Path(source_text)
        events = _load_jsonl(source)
        starts = [
            event for event in events
            if event.get("event") == "v11_shadow_session_start"
        ]
        ends = [
            event for event in events
            if event.get("event") == "v11_shadow_session_end"
        ]
        scores = [
            event for event in events
            if event.get("event") == "v11_shadow_score"
        ]
        snapshots = [
            event for event in events
            if event.get("event") == "v11_shadow_controller_snapshot"
        ]
        current_decisions = [
            event for event in events
            if event.get("event") == "v11_shadow_decision"
        ]
        current_exceptions = [
            event for event in events
            if event.get("event") in {
                "v11_shadow_exception",
                "v11_shadow_decision_exception",
            }
        ]
        exceptions += len(current_exceptions)
        if len(starts) != 1 or len(ends) != 1:
            contract_failures.append({
                "path": str(source),
                "error": "session_boundary_count",
            })
            continue
        episode_id = starts[0].get("physical_episode_id")
        if episode_id is None:
            contract_failures.append({
                "path": str(source),
                "error": "missing_physical_episode_id",
            })
            continue
        session_episodes.add(int(episode_id))
        artifact_hashes.add(starts[0].get("portable_artifact_sha256"))
        if not (
            len(scores) == len(snapshots) == len(current_decisions)
            and starts[0].get("decision_shadow_enabled") is True
        ):
            contract_failures.append({
                "path": str(source),
                "error": "score_snapshot_decision_count_mismatch",
            })
        for decision in current_decisions:
            key = (
                int(decision["physical_episode_id"]),
                int(decision["attempt"]),
            )
            duplicate_keys += int(key in seen_keys)
            seen_keys.add(key)
            policy_hashes.add(
                (decision.get("policy") or {}).get("policy_sha256")
            )
            baseline = decision.get("baseline") or {}
            reconstructed_event = (
                {
                    "accepted": True,
                    "anchor_index": baseline.get("selected_anchor_index"),
                    "backend": baseline.get("controller_backend"),
                }
                if baseline.get("controller_accepted") is True else None
            )
            expected_decision = policy.evaluate(
                decision.get("candidate_assessments", []),
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
            if any(
                (decision.get("counterfactual") or {}).get(field)
                != expected_decision["counterfactual"].get(field)
                for field in plan_fields
            ):
                contract_failures.append({
                    "path": str(source),
                    "attempt": decision.get("attempt"),
                    "error": "counterfactual_plan_recompute_mismatch",
                })
            posthoc = decision.get("posthoc_ground_truth") or {}
            if (
                decision.get("controller_effect") is not False
                or decision.get("enforcement_enabled") is not False
                or decision.get("activation_approved") is not False
                or (
                    decision.get("counterfactual") or {}
                ).get("identity_override_authorized") is not False
                or posthoc.get("used_for_decision") is not False
            ):
                contract_failures.append({
                    "path": str(source),
                    "attempt": decision.get("attempt"),
                    "error": "shadow_lock_or_truth_isolation_failure",
                })
            decisions.append(decision)

    candidate_rows = []
    missing_truth_rows = 0
    for decision in decisions:
        labels = {
            int(row["anchor_index"]): row
            for row in (
                decision.get("posthoc_ground_truth") or {}
            ).get("candidate_labels", [])
        }
        forwarded = {
            int(anchor)
            for anchor in (
                decision.get("counterfactual") or {}
            ).get("forwarded_anchor_indices", [])
        }
        episode_id = int(decision["physical_episode_id"])
        scene_id = str(decision.get("scene_id") or "unknown")
        attempt = int(decision["attempt"])
        for assessment in decision.get("candidate_assessments", []):
            anchor = int(assessment["anchor_index"])
            truth = labels.get(anchor)
            if not truth or truth.get("available") is not True:
                missing_truth_rows += 1
                continue
            candidate_rows.append({
                "episode_id": episode_id,
                "scene_id": scene_id,
                "attempt": attempt,
                "anchor_index": anchor,
                "anchor_role": str(assessment["anchor_role"]),
                "forwarded": anchor in forwarded,
                "p_bearing_bad_30": float(
                    assessment["p_bearing_bad_30"]
                ),
                "p_distance_bad_0p5": float(
                    assessment["p_distance_bad_0p5"]
                ),
                "p_pose_bad": float(assessment["p_pose_bad"]),
                "bearing_trusted": bool(assessment["bearing_trusted"]),
                "distance_trusted": bool(assessment["distance_trusted"]),
                "pose_trusted": bool(assessment["pose_trusted"]),
                "jointly_trusted": bool(assessment["jointly_trusted"]),
                "label_bearing_bad": int(truth["label_bearing_bad"]),
                "label_distance_bad": int(truth["label_distance_bad"]),
                "label_pose_bad": int(truth["label_pose_bad"]),
            })

    offline_rows = {}
    offline_duplicate_keys = 0
    with Path(args.offline_row_predictions_csv).open(
        newline="",
        encoding="utf-8",
    ) as handle:
        for row in csv.DictReader(handle):
            key = (
                int(row["episode_id"]),
                int(row["attempt"]),
                int(row["anchor_index"]),
            )
            offline_duplicate_keys += int(key in offline_rows)
            offline_rows[key] = row
    online_keys = {
        (
            int(row["episode_id"]),
            int(row["attempt"]),
            int(row["anchor_index"]),
        )
        for row in candidate_rows
    }
    offline_keys = set(offline_rows)
    offline_missing_keys = sorted(online_keys - offline_keys)
    offline_extra_keys = sorted(offline_keys - online_keys)
    offline_label_mismatches = 0
    offline_trust_mismatches = 0
    offline_probability_max_difference = {
        "p_bearing_bad_30": 0.0,
        "p_distance_bad_0p5": 0.0,
        "p_pose_bad": 0.0,
    }
    online_by_key = {
        (
            int(row["episode_id"]),
            int(row["attempt"]),
            int(row["anchor_index"]),
        ): row
        for row in candidate_rows
    }
    for key in sorted(online_keys & offline_keys):
        online = online_by_key[key]
        offline = offline_rows[key]
        for field in (
            "label_bearing_bad",
            "label_distance_bad",
            "label_pose_bad",
        ):
            offline_label_mismatches += int(
                int(online[field]) != int(offline[field])
            )
        for field in (
            "bearing_trusted",
            "distance_trusted",
            "pose_trusted",
            "jointly_trusted",
        ):
            offline_trust_mismatches += int(
                bool(online[field]) != bool(int(offline[field]))
            )
        for field in offline_probability_max_difference:
            offline_probability_max_difference[field] = max(
                offline_probability_max_difference[field],
                abs(float(online[field]) - float(offline[field])),
            )
    offline_join = {
        "online_rows": len(candidate_rows),
        "offline_rows": len(offline_rows),
        "matched_rows": len(online_keys & offline_keys),
        "offline_duplicate_keys": offline_duplicate_keys,
        "missing_offline_keys": len(offline_missing_keys),
        "extra_offline_keys": len(offline_extra_keys),
        "missing_offline_key_examples": offline_missing_keys[:20],
        "extra_offline_key_examples": offline_extra_keys[:20],
        "label_mismatches": offline_label_mismatches,
        "trust_mismatches": offline_trust_mismatches,
        "probability_max_difference": offline_probability_max_difference,
    }

    current_rows = [
        row for row in candidate_rows if row["anchor_role"] == "current"
    ]
    next_rows = [
        row for row in candidate_rows if row["anchor_role"] == "next"
    ]
    current_weights = _episode_balanced_weights(current_rows)
    next_weights = _episode_balanced_weights(next_rows)

    def role_metrics(rows, weights, seed_offset):
        if not rows:
            return {}
        return {
            "rows": len(rows),
            "physical_episodes": len({
                int(row["episode_id"]) for row in rows
            }),
            "forwarded_coverage": _weighted_rate(
                rows, weights, lambda row: row["forwarded"]
            ),
            "bad_block_recall": {
                label: _weighted_rate(
                    rows,
                    weights,
                    lambda row: not row["forwarded"],
                    lambda row, field=label: bool(row[field]),
                )
                for label in (
                    "label_bearing_bad",
                    "label_distance_bad",
                    "label_pose_bad",
                )
            },
            "good_defer_rate": {
                label: _weighted_rate(
                    rows,
                    weights,
                    lambda row: not row["forwarded"],
                    lambda row, field=label: not bool(row[field]),
                )
                for label in (
                    "label_bearing_bad",
                    "label_distance_bad",
                    "label_pose_bad",
                )
            },
            "forwarded_bad_rate": {
                label: _weighted_rate(
                    rows,
                    weights,
                    lambda row, field=label: bool(row[field]),
                    lambda row: row["forwarded"],
                )
                for label in (
                    "label_bearing_bad",
                    "label_distance_bad",
                    "label_pose_bad",
                )
            },
            "forwarded_bad_rate_upper_95": {
                label: _cluster_risk_ucb(
                    rows,
                    label=label,
                    samples=args.bootstrap_samples,
                    seed=args.seed + seed_offset + index,
                )
                for index, label in enumerate((
                    "label_bearing_bad",
                    "label_distance_bad",
                    "label_pose_bad",
                ))
            },
        }

    current_metrics = role_metrics(current_rows, current_weights, 0)
    next_metrics = role_metrics(next_rows, next_weights, 10)
    scoreable_episodes = sorted({
        int(row["episode_id"]) for row in current_rows
    })
    current_forwarded_by_episode: dict[int, list[int]] = defaultdict(list)
    for row in current_rows:
        if row["forwarded"]:
            current_forwarded_by_episode[int(row["episode_id"])].append(
                int(row["attempt"])
            )
    any_forwarded_fraction = (
        sum(bool(current_forwarded_by_episode[episode])
            for episode in scoreable_episodes) / len(scoreable_episodes)
        if scoreable_episodes else 0.0
    )
    first10_fraction = (
        sum(
            any(attempt <= 10 for attempt in current_forwarded_by_episode[episode])
            for episode in scoreable_episodes
        ) / len(scoreable_episodes)
        if scoreable_episodes else 0.0
    )
    streaks = _longest_full_defer_streaks(decisions)
    streak_values = list(streaks.values())

    scene_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in current_rows:
        if row["forwarded"]:
            scene_rows[row["scene_id"]].append(row)
    scene_metrics = {}
    gated_scene_failures = []
    for scene, rows in sorted(scene_rows.items()):
        pose_bad_rate = (
            sum(row["label_pose_bad"] for row in rows) / len(rows)
            if rows else None
        )
        scene_metrics[scene] = {
            "forwarded_current_rows": len(rows),
            "pose_bad_rate": pose_bad_rate,
        }
        if (
            len(rows)
            >= int(gates["scene_minimum_forwarded_current_rows_for_gate"])
            and pose_bad_rate
            > float(gates["scene_forwarded_current_pose_bad_rate_maximum"])
        ):
            gated_scene_failures.append(scene)

    checks = {
        "completion_manifest_count": (
            completion["unique_physical_episodes"]
            == int(gates["scheduled_physical_episodes"])
        ),
        "completion_manifest_integrity": not completion["failures"],
        "completion_manifest_uniqueness": (
            completion["duplicate_episode_manifests"] == 0
        ),
        "scoreable_episode_minimum": (
            len(scoreable_episodes)
            >= int(gates["minimum_scoreable_physical_episodes"])
        ),
        "shadow_contract": (
            not contract_failures
            and duplicate_keys == 0
            and len(policy_hashes) == 1
            and policy_hashes == {policy.policy_sha256}
            and len(artifact_hashes) == 1
        ),
        "exceptions": (
            exceptions
            <= int(gates["maximum_shadow_or_decision_exceptions"])
        ),
        "online_truth_complete": (
            missing_truth_rows
            <= int(gates["maximum_missing_online_truth_rows"])
        ),
        "offline_online_exact_join": (
            offline_duplicate_keys == 0
            and not offline_missing_keys
            and not offline_extra_keys
            and offline_label_mismatches == 0
            and offline_trust_mismatches == 0
            and max(offline_probability_max_difference.values()) <= 1e-15
        ),
        "current_forwarded_coverage": (
            current_metrics.get("forwarded_coverage", 0.0)
            >= float(gates["current_forwarded_coverage_minimum"])
        ),
        "current_bad_block_recall": (
            (
                current_metrics.get("bad_block_recall", {})
                .get("label_pose_bad")
            ) is not None
            and current_metrics["bad_block_recall"]["label_pose_bad"]
            >= float(gates["current_bad_block_recall_minimum"])
        ),
        "current_forwarded_bearing_risk_ucb": (
            (
                current_metrics.get("forwarded_bad_rate_upper_95", {})
                .get("label_bearing_bad")
            ) is not None
            and current_metrics["forwarded_bad_rate_upper_95"][
                "label_bearing_bad"
            ]
            <= float(
                gates[
                    "current_forwarded_bearing_bad_rate_upper_95_maximum"
                ]
            )
        ),
        "current_forwarded_distance_risk_ucb": (
            (
                current_metrics.get("forwarded_bad_rate_upper_95", {})
                .get("label_distance_bad")
            ) is not None
            and current_metrics["forwarded_bad_rate_upper_95"][
                "label_distance_bad"
            ]
            <= float(
                gates[
                    "current_forwarded_distance_bad_rate_upper_95_maximum"
                ]
            )
        ),
        "current_forwarded_pose_risk_ucb": (
            (
                current_metrics.get("forwarded_bad_rate_upper_95", {})
                .get("label_pose_bad")
            ) is not None
            and current_metrics["forwarded_bad_rate_upper_95"][
                "label_pose_bad"
            ]
            <= float(
                gates["current_forwarded_pose_bad_rate_upper_95_maximum"]
            )
        ),
        "episode_any_current_forwarded": (
            any_forwarded_fraction
            >= float(
                gates["episode_any_current_forwarded_fraction_minimum"]
            )
        ),
        "episode_current_forwarded_first10": (
            first10_fraction
            >= float(
                gates[
                    "episode_current_forwarded_within_first_10_fraction_minimum"
                ]
            )
        ),
        "full_defer_streak_p95": (
            _quantile(streak_values, 0.95) is not None
            and _quantile(streak_values, 0.95)
            <= float(gates["full_defer_streak_p95_maximum_attempts"])
        ),
        "full_defer_streak_absolute": (
            bool(streak_values)
            and max(streak_values)
            <= int(gates["full_defer_streak_absolute_maximum_attempts"])
        ),
        "scene_forwarded_current_pose_risk": not gated_scene_failures,
    }
    all_passed = all(checks.values())
    report = {
        "schema": "navila-v11-control-readiness-report-v1",
        "passed": all_passed,
        "recommendation": (
            "eligible_for_10ep_guarded_active_canary"
            if all_passed
            else "remain_shadow_and_review_failed_gates"
        ),
        "important_boundary": (
            "Passing never directly authorizes an active 100ep run; the frozen "
            "protocol requires a 10ep guarded active canary first."
        ),
        "gates": gates,
        "checks": checks,
        "completion": completion,
        "shadow_logs": len(args.shadow_logs),
        "session_physical_episodes": len(session_episodes),
        "scoreable_physical_episodes": len(scoreable_episodes),
        "decisions": len(decisions),
        "candidate_rows": len(candidate_rows),
        "missing_truth_rows": missing_truth_rows,
        "offline_online_join": offline_join,
        "exceptions": exceptions,
        "contract_failures": contract_failures,
        "duplicate_decision_keys": duplicate_keys,
        "policy_hashes": sorted(str(value) for value in policy_hashes),
        "portable_artifact_hashes": sorted(
            str(value) for value in artifact_hashes
        ),
        "actions": dict(Counter(
            str(decision["counterfactual"]["action"])
            for decision in decisions
        )),
        "current_role": current_metrics,
        "next_role": next_metrics,
        "episode_availability": {
            "scoreable_episodes": len(scoreable_episodes),
            "any_current_forwarded_fraction": any_forwarded_fraction,
            "current_forwarded_within_first_10_fraction": first10_fraction,
            "full_defer_streak_p95": _quantile(streak_values, 0.95),
            "full_defer_streak_maximum": (
                max(streak_values) if streak_values else None
            ),
            "full_defer_streak_by_episode": {
                str(key): value for key, value in sorted(streaks.items())
            },
        },
        "scene_forwarded_current": scene_metrics,
        "gated_scene_failures": gated_scene_failures,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
