"""Causal features for the second dedicated hint-action model.

The learned task remains movement-direction preference.  Clear-path evidence
is exposed separately for the deterministic execution gate and is not added
to the model feature dictionary.
"""

from __future__ import annotations

import collections
import math
from typing import Any

from hint_action_features import TEMPORAL_KEYS, base_features
from model_features import _finite_number, assert_runtime_only


MAX_HISTORY = 16
MAX_CONTIGUOUS_GAP_STEPS = 225
HISTORY_KEYS = tuple(
    key
    for key in TEMPORAL_KEYS
    if key
    not in {
        "proposal.desired_bearing_deg",
        "route_memory.target_anchor_index",
    }
)


def circular_delta_deg(current: float, previous: float) -> float:
    return (float(current) - float(previous) + 180.0) % 360.0 - 180.0


def clearance_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Return only causal clearance fields, never old override/reason."""
    source = row["inputs"].get("clearance")
    if source is None:
        source = row.get("historical_policy") or {}
    return {
        "available": bool(source.get("clear_path_available")),
        "clear": (
            bool(source.get("clear_path"))
            if source.get("clear_path") is not None
            else None
        ),
        "source": source.get("clear_path_source"),
        "min_clearance_m": source.get("min_clearance_m"),
    }


def direction_from_yaw(yaw_change_deg: float | None) -> str:
    if yaw_change_deg is None or abs(yaw_change_deg) < 5.0:
        return "forward"
    return "left" if yaw_change_deg > 0.0 else "right"


class HintActionV2FeatureState:
    def __init__(self) -> None:
        self._history = {
            key: collections.deque(maxlen=MAX_HISTORY)
            for key in HISTORY_KEYS
        }
        self._last_step: int | None = None
        self._last_bearing: float | None = None
        self._last_desired_kind: str | None = None
        self._last_vlm_kind: str | None = None
        self._last_target: int | None = None
        self._same_desired_streak = 0
        self._same_target_streak = 0

    def _reset_temporal(self) -> None:
        for history in self._history.values():
            history.clear()
        self._last_bearing = None
        self._last_desired_kind = None
        self._last_vlm_kind = None
        self._last_target = None
        self._same_desired_streak = 0
        self._same_target_streak = 0

    def transform(self, row: dict[str, Any]) -> dict[str, float]:
        features = base_features(row)
        for key in list(features):
            if "anchor_index" in key:
                del features[key]
        step = int(row["time"]["step"])
        gap = None if self._last_step is None else step - self._last_step
        if gap is not None:
            features["temporal.query_gap_steps"] = float(gap)
            features["temporal.query_gap_log1p"] = math.log1p(max(0, gap))
            if gap <= 0 or gap > MAX_CONTIGUOUS_GAP_STEPS:
                features["temporal.gap_reset"] = 1.0
                self._reset_temporal()
        else:
            features["temporal.first_query"] = 1.0

        proposal = row["inputs"].get("arbiter_proposal") or {}
        desired_kind = str(proposal.get("desired_kind") or "unknown")
        vlm_kind = str(row["inputs"].get("vlm_action_kind") or "unknown")
        bearing = _finite_number(proposal.get("desired_bearing_deg"))
        target_value = proposal.get("target_anchor_index")
        target = int(target_value) if target_value is not None else None

        if bearing is not None:
            radians = math.radians(bearing)
            features["proposal.bearing_sin"] = math.sin(radians)
            features["proposal.bearing_cos"] = math.cos(radians)
            features["proposal.behind_fraction"] = max(
                0.0, (abs(bearing) - 90.0) / 90.0
            )
            if self._last_bearing is not None:
                delta = circular_delta_deg(bearing, self._last_bearing)
                features["temporal.proposal.circular_delta_deg"] = delta
                features["temporal.proposal.abs_circular_delta_deg"] = abs(
                    delta
                )
                features["temporal.proposal.circular_agreement"] = math.cos(
                    math.radians(delta)
                )

        same_desired = (
            self._last_desired_kind is not None
            and desired_kind == self._last_desired_kind
        )
        same_target = (
            target is not None
            and self._last_target is not None
            and target == self._last_target
        )
        self._same_desired_streak = (
            self._same_desired_streak + 1 if same_desired else 1
        )
        self._same_target_streak = (
            self._same_target_streak + 1 if same_target else 1
        )
        features["temporal.proposal.same_kind"] = float(same_desired)
        features["temporal.proposal.same_kind_streak"] = float(
            self._same_desired_streak
        )
        features["temporal.proposal.same_target"] = float(same_target)
        features["temporal.proposal.same_target_streak"] = float(
            self._same_target_streak
        )
        if target is not None and self._last_target is not None:
            features["temporal.proposal.target_jump_abs"] = float(
                abs(target - self._last_target)
            )

        movement = row["inputs"].get("movement") or {}
        translation = _finite_number(
            movement.get("translation_since_previous_m")
        )
        yaw_change = _finite_number(
            movement.get("yaw_change_since_previous_deg")
        )
        movement_steps = _finite_number(
            movement.get("steps_since_previous")
        )
        if translation is not None:
            features["response.translation_stalled"] = float(
                translation < 0.10
            )
            if movement_steps is not None and movement_steps > 0.0:
                features["response.translation_per_step"] = (
                    translation / movement_steps
                )
        if yaw_change is not None:
            features["response.abs_yaw_change_deg"] = abs(yaw_change)
            observed_direction = direction_from_yaw(yaw_change)
            if self._last_desired_kind is not None:
                features["response.prior_hint_matches_motion"] = float(
                    observed_direction == self._last_desired_kind
                )
            if self._last_vlm_kind is not None:
                features["response.prior_vlm_matches_motion"] = float(
                    observed_direction == self._last_vlm_kind
                )

        for key in HISTORY_KEYS:
            current = _finite_number(features.get(key))
            history = self._history[key]
            if current is not None and history:
                features[f"temporal.{key}.delta_previous"] = (
                    current - history[-1]
                )
            for window in (4, 16):
                values = list(history)[-window:]
                prefix = f"temporal.{key}.w{window}"
                if not values:
                    features[f"{prefix}.__missing"] = 1.0
                    continue
                mean = sum(values) / len(values)
                variance = sum(
                    (value - mean) ** 2 for value in values
                ) / len(values)
                features[f"{prefix}.mean"] = mean
                features[f"{prefix}.std"] = math.sqrt(variance)
                features[f"{prefix}.min"] = min(values)
                features[f"{prefix}.max"] = max(values)
                features[f"{prefix}.count"] = float(len(values))
            if current is not None:
                history.append(current)

        self._last_step = step
        self._last_bearing = bearing
        self._last_desired_kind = desired_kind
        self._last_vlm_kind = vlm_kind
        self._last_target = target
        assert_runtime_only(features)
        return features
