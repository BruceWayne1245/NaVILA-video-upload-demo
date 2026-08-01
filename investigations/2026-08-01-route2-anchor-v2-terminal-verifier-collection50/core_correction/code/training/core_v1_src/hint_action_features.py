"""Runtime-only causal features for the dedicated hint-action model."""

from __future__ import annotations

import collections
import math
from typing import Any

from model_features import (
    _candidate_aggregates,
    _candidate_roles,
    _finite_number,
    _flatten,
    assert_runtime_only,
)


MAX_HISTORY = 16
TEMPORAL_KEYS = (
    "route_memory.distance_to_start_m",
    "route_memory.target_anchor_index",
    "route_memory.evidence_age_updates",
    "route_memory.relocalization_confidence",
    "proposal.desired_bearing_deg",
    "proposal.desired_distance_m",
    "proposal.relocalization_confidence",
    "movement.translation_since_previous_m",
    "candidate.current.confidence",
    "candidate.current.v11.p_bearing_bad_30",
    "candidate.next.confidence",
    "candidate.next.v11.p_bearing_bad_30",
    "candidate_agg.pose_trusted_fraction",
)


def base_features(row: dict[str, Any]) -> dict[str, float]:
    inputs = row["inputs"]
    features: dict[str, float] = {}
    _flatten(features, "movement", inputs.get("movement") or {})
    _flatten(features, "route_memory", inputs.get("route_memory") or {})
    _flatten(features, "vlm.action_kind", inputs.get("vlm_action_kind"))
    _flatten(features, "proposal", inputs.get("arbiter_proposal") or {})

    summary = inputs.get("anchor_state_summary") or {}
    support = summary.get("support") or {}
    candidates = summary.get("candidates") or []
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

    bearing = _finite_number(
        (inputs.get("arbiter_proposal") or {}).get("desired_bearing_deg")
    )
    if bearing is not None:
        features["proposal.abs_bearing_deg"] = abs(bearing)
        features["proposal.bearing_sign"] = (
            1.0 if bearing > 0.0 else -1.0 if bearing < 0.0 else 0.0
        )
    return features


class HintActionCausalFeatureState:
    def __init__(self) -> None:
        self._history = {
            key: collections.deque(maxlen=MAX_HISTORY)
            for key in TEMPORAL_KEYS
        }

    def transform(self, row: dict[str, Any]) -> dict[str, float]:
        features = base_features(row)
        for key in TEMPORAL_KEYS:
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
                variance = sum(
                    (value - mean) ** 2 for value in values
                ) / len(values)
                prefix = f"temporal.{key}.w{window}"
                features[f"{prefix}.mean"] = mean
                features[f"{prefix}.std"] = math.sqrt(variance)
                features[f"{prefix}.min"] = min(values)
                features[f"{prefix}.max"] = max(values)
                features[f"{prefix}.count"] = float(len(values))
            if current is not None:
                history.append(current)
        assert_runtime_only(features)
        return features
