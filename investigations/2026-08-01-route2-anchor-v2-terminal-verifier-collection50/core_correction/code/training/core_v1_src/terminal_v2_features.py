"""Reduced, runtime-only terminal features for stronger scene transfer."""

from __future__ import annotations

import collections
import math
from typing import Any

from model_features import CausalFeatureState, _finite_number, assert_runtime_only


# Absolute route indices let a tree memorize route length and scene-specific
# anchor layouts.  Terminal authority needs distances, freshness, motion,
# evidence quality and relative support geometry instead.
ABSOLUTE_INDEX_TOKENS = (
    "anchor_index",
    "source_anchor_index",
    "target_anchor_index",
)
MAX_HISTORY = 16
DISTANCE_TEMPORAL_KEYS = (
    "candidate.current.v11.p_distance_bad_0p5",
    "candidate.current.v11.distance_trusted",
    "candidate.next.v11.p_distance_bad_0p5",
    "candidate.next.v11.distance_trusted",
    "candidate_agg.p_distance_bad_0p5.mean",
    "candidate_agg.distance_trusted_fraction",
)


class TerminalV2FeatureState:
    def __init__(self) -> None:
        self._base = CausalFeatureState()
        self._distance_history = {
            key: collections.deque(maxlen=MAX_HISTORY)
            for key in DISTANCE_TEMPORAL_KEYS
        }

    def transform(self, row: dict[str, Any]) -> dict[str, float]:
        features = self._base.transform(row)
        summary = row["inputs"].get("anchor_state_summary") or {}
        candidates = summary.get("candidates") or []
        probabilities = [
            value
            for candidate in candidates
            if (
                value := _finite_number(
                    (candidate.get("v11") or {}).get("p_distance_bad_0p5")
                )
            ) is not None
        ]
        if probabilities:
            features["candidate_agg.p_distance_bad_0p5.min"] = min(probabilities)
            features["candidate_agg.p_distance_bad_0p5.max"] = max(probabilities)
            features["candidate_agg.p_distance_bad_0p5.mean"] = (
                sum(probabilities) / len(probabilities)
            )
        trusted = [
            bool((candidate.get("v11") or {}).get("distance_trusted"))
            for candidate in candidates
            if (candidate.get("v11") or {}).get("distance_trusted") is not None
        ]
        if trusted:
            features["candidate_agg.distance_trusted_fraction"] = (
                sum(trusted) / len(trusted)
            )
        for key, history in self._distance_history.items():
            current = _finite_number(features.get(key))
            if current is not None and history:
                features[f"temporal.{key}.delta_previous"] = current - history[-1]
            for window in (4, 16):
                values = list(history)[-window:]
                prefix = f"temporal.{key}.w{window}"
                if not values:
                    features[f"{prefix}.__missing"] = 1.0
                    continue
                mean = sum(values) / len(values)
                variance = sum((value - mean) ** 2 for value in values) / len(values)
                features[f"{prefix}.mean"] = mean
                features[f"{prefix}.std"] = math.sqrt(variance)
                features[f"{prefix}.min"] = min(values)
                features[f"{prefix}.max"] = max(values)
                features[f"{prefix}.count"] = float(len(values))
            if current is not None:
                history.append(current)
        reduced = {
            key: value
            for key, value in features.items()
            if not any(token in key for token in ABSOLUTE_INDEX_TOKENS)
        }
        assert_runtime_only(reduced)
        return reduced
