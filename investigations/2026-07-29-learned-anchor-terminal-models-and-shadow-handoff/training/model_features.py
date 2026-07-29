"""Runtime-only causal feature extraction for anchor and terminal models."""

from __future__ import annotations

import collections
import math
from typing import Any


MAX_HISTORY = 16


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _add_scalar(features: dict[str, float], key: str, value: Any) -> None:
    number = _finite_number(value)
    if number is not None:
        features[key] = number
    elif isinstance(value, str) and value:
        features[f"{key}={value}"] = 1.0
    elif value is None:
        features[f"{key}.__missing"] = 1.0


def _flatten(
    features: dict[str, float],
    prefix: str,
    value: Any,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten(features, f"{prefix}.{key}" if prefix else str(key), child)
        return
    if isinstance(value, (list, tuple)):
        numeric = [
            number
            for item in value
            if (number := _finite_number(item)) is not None
        ]
        features[f"{prefix}.count"] = float(len(value))
        if numeric:
            features[f"{prefix}.min"] = min(numeric)
            features[f"{prefix}.max"] = max(numeric)
            features[f"{prefix}.mean"] = sum(numeric) / len(numeric)
        return
    _add_scalar(features, prefix, value)


def _candidate_map(candidates: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result = {}
    for candidate in candidates:
        index = candidate.get("anchor_index")
        if index is not None:
            result[int(index)] = candidate
    return result


def _candidate_roles(
    candidates: list[dict[str, Any]],
    support: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    by_index = _candidate_map(candidates)
    current_index = support.get("current_anchor_index")
    next_index = support.get("next_anchor_index")
    current = by_index.get(int(current_index)) if current_index is not None else None
    next_candidate = by_index.get(int(next_index)) if next_index is not None else None
    for candidate in candidates:
        role = (candidate.get("v11") or {}).get("anchor_role")
        if role == "current" and current is None:
            current = candidate
        elif role == "next" and next_candidate is None:
            next_candidate = candidate
    if current is None or next_candidate is None:
        ordered = sorted(
            by_index.items(), key=lambda item: item[0], reverse=True
        )
        if current is None and ordered:
            current = ordered[0][1]
        if next_candidate is None and len(ordered) >= 2:
            next_candidate = ordered[1][1]
    return current, next_candidate


def _candidate_aggregates(
    features: dict[str, float],
    candidates: list[dict[str, Any]],
) -> None:
    features["state.candidate_count"] = float(len(candidates))
    fields = (
        "confidence",
        "estimated_distance_to_anchor_m",
        "inlier_count",
        "overlap_ratio",
        "median_residual_m",
        "icp_best_to_second_score_ratio",
    )
    for field in fields:
        values = [
            number
            for candidate in candidates
            if (number := _finite_number(candidate.get(field))) is not None
        ]
        if values:
            features[f"candidate_agg.{field}.min"] = min(values)
            features[f"candidate_agg.{field}.max"] = max(values)
            features[f"candidate_agg.{field}.mean"] = sum(values) / len(values)
    pose_probabilities = [
        number
        for candidate in candidates
        if (
            number := _finite_number(
                (candidate.get("v11") or {}).get("p_pose_bad")
            )
        )
        is not None
    ]
    if pose_probabilities:
        features["candidate_agg.p_pose_bad.min"] = min(pose_probabilities)
        features["candidate_agg.p_pose_bad.max"] = max(pose_probabilities)
        features["candidate_agg.p_pose_bad.mean"] = (
            sum(pose_probabilities) / len(pose_probabilities)
        )
    trusted = [
        bool((candidate.get("v11") or {}).get("pose_trusted"))
        for candidate in candidates
        if (candidate.get("v11") or {}).get("pose_trusted") is not None
    ]
    if trusted:
        features["candidate_agg.pose_trusted_fraction"] = sum(trusted) / len(trusted)


def _base_features(row: dict[str, Any]) -> dict[str, float]:
    inputs = row["inputs"]
    features: dict[str, float] = {}
    _flatten(features, "movement", inputs.get("movement") or {})
    _flatten(features, "route_memory", inputs.get("route_memory") or {})
    if row["task"] == "anchor_state":
        support = inputs.get("support") or {}
        candidates = inputs.get("candidates") or []
    else:
        summary = inputs.get("anchor_state_summary") or {}
        support = summary.get("support") or {}
        candidates = summary.get("candidates") or []
        _flatten(features, "terminal.vlm_requested_stop", inputs.get("vlm_requested_stop"))
        _flatten(features, "terminal.a0_visual", inputs.get("a0_visual") or {})
    _flatten(features, "support", support)
    current, next_candidate = _candidate_roles(candidates, support)
    if current is not None:
        _flatten(features, "candidate.current", current)
    else:
        features["candidate.current.__missing"] = 1.0
    if next_candidate is not None:
        _flatten(features, "candidate.next", next_candidate)
    else:
        features["candidate.next.__missing"] = 1.0
    _candidate_aggregates(features, candidates)
    current_index = support.get("current_anchor_index")
    next_index = support.get("next_anchor_index")
    if current_index is None and current is not None:
        current_index = current.get("anchor_index")
    if next_index is None and next_candidate is not None:
        next_index = next_candidate.get("anchor_index")
    _add_scalar(features, "state.observed_current_anchor_index", current_index)
    _add_scalar(features, "state.observed_next_anchor_index", next_index)
    if current_index is not None and next_index is not None:
        features["state.support_gap"] = float(current_index) - float(next_index)
    return features


TEMPORAL_CORE_KEYS = (
    "route_memory.distance_to_start_m",
    "route_memory.target_anchor_index",
    "route_memory.evidence_age_updates",
    "route_memory.relocalization_confidence",
    "state.observed_current_anchor_index",
    "state.observed_next_anchor_index",
    "state.support_gap",
    "candidate.current.confidence",
    "candidate.current.estimated_distance_to_anchor_m",
    "candidate.current.v11.p_pose_bad",
    "candidate.next.confidence",
    "candidate.next.estimated_distance_to_anchor_m",
    "candidate.next.v11.p_pose_bad",
    "candidate_agg.pose_trusted_fraction",
    "movement.translation_since_previous_m",
    "terminal.vlm_requested_stop",
)


class CausalFeatureState:
    def __init__(self) -> None:
        self._history = {
            key: collections.deque(maxlen=MAX_HISTORY)
            for key in TEMPORAL_CORE_KEYS
        }

    def transform(self, row: dict[str, Any]) -> dict[str, float]:
        features = _base_features(row)
        for key in TEMPORAL_CORE_KEYS:
            current = _finite_number(features.get(key))
            history = self._history[key]
            if current is not None and history:
                features[f"temporal.{key}.delta_previous"] = current - history[-1]
            for window in (4, 16):
                values = list(history)[-window:]
                if not values:
                    features[f"temporal.{key}.w{window}.__missing"] = 1.0
                    continue
                mean = sum(values) / len(values)
                variance = sum((value - mean) ** 2 for value in values) / len(values)
                features[f"temporal.{key}.w{window}.mean"] = mean
                features[f"temporal.{key}.w{window}.std"] = math.sqrt(variance)
                features[f"temporal.{key}.w{window}.min"] = min(values)
                features[f"temporal.{key}.w{window}.max"] = max(values)
                features[f"temporal.{key}.w{window}.count"] = float(len(values))
            if current is not None:
                history.append(current)
        return features


def assert_runtime_only(features: dict[str, float]) -> None:
    banned = ("oracle", "label", "historical_policy", "world_pose", "position")
    offending = [
        key for key in features if any(token in key.lower() for token in banned)
    ]
    if offending:
        raise RuntimeError(f"supervision leaked into features: {offending[:10]}")

