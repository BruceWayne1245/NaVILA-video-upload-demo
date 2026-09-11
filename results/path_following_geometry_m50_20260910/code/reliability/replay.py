"""Counterfactual replay for pinned-current and missed-stop cases."""

from __future__ import annotations

from collections import defaultdict
import glob
import json
import os
import re
from typing import Any

from .bundle import ReliabilityBundle


PINNED_ANCHORS = {
    5: 11,
    20: 8,
    319: 4,
    367: 11,
    498: 5,
    500: 10,
    669: 4,
    680: 6,
    813: 6,
    889: 9,
    994: 6,
    1038: 4,
    653: 10,
}


def _score(bundle: ReliabilityBundle, row: dict[str, Any]) -> dict[str, Any]:
    cached = row.get("_reliability")
    return cached if isinstance(cached, dict) else bundle.predict_features(row).as_dict()


def _first_streak(observations: list[tuple[int, bool]], length: int) -> int | None:
    streak = 0
    previous = None
    for attempt, value in observations:
        if previous is not None and attempt != previous + 1:
            streak = 0
        streak = streak + 1 if value else 0
        if streak >= length:
            return attempt
        previous = attempt
    return None


def replay_pinned(
    rows: list[dict[str, Any]],
    bundle: ReliabilityBundle,
    batch: str,
    consecutive: int = 10,
    high_risk_threshold: float = 0.7,
) -> list[dict[str, Any]]:
    by_episode: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["batch"] == batch and int(row["episode_id"]) in PINNED_ANCHORS:
            by_episode[int(row["episode_id"])].append(row)
    output = []
    for episode_id, anchor_index in PINNED_ANCHORS.items():
        selected = [
            row for row in by_episode.get(episode_id, [])
            if int(row["anchor_index"]) == anchor_index and row.get("anchor_role") == "current"
        ]
        # One reading per attempt/anchor is expected; de-duplicate defensively.
        selected_by_attempt = {int(row["attempt"]): row for row in selected}
        observations = []
        risks = []
        actual = []
        for attempt, row in sorted(selected_by_attempt.items()):
            result = _score(bundle, row)
            high_risk = result["status"] != "trusted" or float(result["p_pose_bad"]) >= high_risk_threshold
            observations.append((attempt, high_risk))
            risks.append(float(result["p_pose_bad"]))
            actual.append(int(row["label_pose_bad"]))
        output.append({
            "episode_id": episode_id,
            "pinned_anchor_index": anchor_index,
            "readings": len(observations),
            "actual_pose_bad_rate": sum(actual) / len(actual) if actual else None,
            "mean_predicted_pose_bad": sum(risks) / len(risks) if risks else None,
            "high_risk_rate": sum(value for _, value in observations) / len(observations) if observations else None,
            "first_eviction_recommendation_attempt": _first_streak(observations, consecutive),
            "detected": _first_streak(observations, consecutive) is not None,
        })
    return output


def replay_current_eviction_false_positives(
    rows: list[dict[str, Any]],
    bundle: ReliabilityBundle,
    batch: str,
    consecutive: int,
    high_risk_threshold: float,
    healthy_bad_rate_max: float = 0.2,
) -> dict[str, Any]:
    groups: dict[tuple[int, int], dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        if row["batch"] == batch and row.get("anchor_role") == "current":
            groups[(int(row["episode_id"]), int(row["anchor_index"]))][int(row["attempt"])] = row
    healthy = []
    for (episode_id, anchor_index), by_attempt in groups.items():
        if len(by_attempt) < consecutive or PINNED_ANCHORS.get(episode_id) == anchor_index:
            continue
        actual_bad_rate = sum(int(row["label_pose_bad"]) for row in by_attempt.values()) / len(by_attempt)
        if actual_bad_rate > healthy_bad_rate_max:
            continue
        observations = []
        for attempt, row in sorted(by_attempt.items()):
            result = _score(bundle, row)
            high_risk = result["status"] != "trusted" or float(result["p_pose_bad"]) >= high_risk_threshold
            observations.append((attempt, high_risk))
        fired = _first_streak(observations, consecutive)
        healthy.append({
            "episode_id": episode_id,
            "anchor_index": anchor_index,
            "readings": len(by_attempt),
            "actual_pose_bad_rate": actual_bad_rate,
            "eviction_recommendation_attempt": fired,
        })
    false_positives = [item for item in healthy if item["eviction_recommendation_attempt"] is not None]
    return {
        "healthy_current_segments": len(healthy),
        "false_positive_segments": len(false_positives),
        "false_positive_rate": len(false_positives) / len(healthy) if healthy else None,
        "false_positives": false_positives,
        "healthy_definition": f"non-pinned current-anchor segment with actual pose-bad rate <= {healthy_bad_rate_max}",
    }


def discover_missed_stop_cases(evaluation_root: str, batch: str, radius_m: float = 3.0) -> dict[int, float]:
    """Use raw episode outcomes/trajectories, including episodes with no late ICP row."""
    result = {}
    for run_dir in sorted(glob.glob(os.path.join(evaluation_root, f"*{batch}*_ep*"))):
        episode_match = re.search(r"_ep(\d+)$", run_dir)
        measurements = []
        for path in glob.glob(os.path.join(run_dir, "measurements", "*.json")):
            step_match = re.search(r"(\d+)\.json$", path)
            if step_match:
                measurements.append((int(step_match.group(1)), path))
        if not episode_match or not measurements:
            continue
        step, measurement_path = max(measurements)
        try:
            measurement = json.load(open(measurement_path, encoding="utf-8"))
        except Exception:
            continue
        round_trip = measurement.get("round_trip") or {}
        if not round_trip.get("outbound_success") or round_trip.get("return_success"):
            continue
        trajectory_path = os.path.join(run_dir, "trajectories", f"output_{step}.jsonl")
        last_return = None
        try:
            with open(trajectory_path, encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    if row.get("phase") == "return":
                        last_return = row
        except Exception:
            continue
        if last_return is None or last_return.get("distance_to_start_m") is None:
            continue
        distance = float(last_return["distance_to_start_m"])
        if distance <= radius_m:
            result[int(episode_match.group(1))] = distance
    return result


def _representative_attempt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_attempt: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_attempt[int(row["attempt"])].append(row)
    selected = []
    for attempt in sorted(by_attempt):
        candidates = by_attempt[attempt]
        next_rows = [row for row in candidates if row.get("anchor_role") == "next"]
        selected.append(next_rows[0] if next_rows else min(candidates, key=lambda row: int(row["anchor_index"])))
    return selected


def replay_stops(
    rows: list[dict[str, Any]],
    bundle: ReliabilityBundle,
    batch: str,
    missed_stop_cases: dict[int, float],
    radius_m: float = 3.0,
    streak_length: int = 3,
) -> dict[str, Any]:
    by_episode: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["batch"] == batch:
            by_episode[int(row["episode_id"])].append(row)
    missed_stop_ids = sorted(missed_stop_cases)
    episode_reports = []
    false_stop_ids = []
    for episode_id, episode_rows in sorted(by_episode.items()):
        representative = _representative_attempt_rows(episode_rows)
        if not representative:
            continue
        final_distance = float(representative[-1]["robot_distance_to_start_m"])
        outbound_success = bool(int(representative[-1]["outbound_success"]))
        return_success = bool(int(representative[-1]["return_success"]))
        is_missed_stop = episode_id in missed_stop_cases
        qualifying = []
        false_qualifying = []
        for row in representative:
            result = _score(bundle, row)
            predicted_close = float(row["estimated_distance_to_start_m"]) <= radius_m
            trusted_close = bool(result["distance_trusted"]) and predicted_close
            true_close = float(row["robot_distance_to_start_m"]) <= radius_m
            qualifying.append((int(row["attempt"]), trusted_close and true_close))
            false_qualifying.append((int(row["attempt"]), trusted_close and not true_close))
        recovery_attempt = _first_streak(qualifying, streak_length)
        false_attempt = _first_streak(false_qualifying, streak_length)
        if false_attempt is not None:
            false_stop_ids.append(episode_id)
        if is_missed_stop:
            episode_reports.append({
                "episode_id": episode_id,
                "final_true_distance_to_start_m": missed_stop_cases[episode_id],
                "counterfactual_forced_stop_attempt": recovery_attempt,
                "recovered": recovery_attempt is not None,
            })
    covered_ids = {item["episode_id"] for item in episode_reports}
    for episode_id in missed_stop_ids:
        if episode_id not in covered_ids:
            episode_reports.append({
                "episode_id": episode_id,
                "final_true_distance_to_start_m": missed_stop_cases[episode_id],
                "counterfactual_forced_stop_attempt": None,
                "recovered": False,
                "reason": "no_usable_reliability_rows",
            })
    episode_reports.sort(key=lambda item: item["episode_id"])
    return {
        "missed_stop_episode_ids": missed_stop_ids,
        "missed_stop_count": len(missed_stop_ids),
        "counterfactual_recovered_count": sum(bool(item["recovered"]) for item in episode_reports),
        "false_stop_streak_episode_ids": false_stop_ids,
        "false_stop_streak_count": len(false_stop_ids),
        "episodes": episode_reports,
        "method": (
            "Representative next-role reading per attempt; counterfactual stop requires three consecutive "
            "distance-trusted readings with both estimated and true distance-to-start within radius."
        ),
    }
