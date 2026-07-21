"""Dependency-free inference for the exported reliability-v1 JSON artifact."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass(frozen=True)
class PortableReliabilityResult:
    p_bearing_bad_30: float
    p_distance_bad_0p5: float
    p_pose_bad: float
    bearing_trusted: bool
    distance_trusted: bool
    pose_trusted: bool
    status: str
    missing_fraction: float
    ood_fraction: float
    model_version: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortableReliabilityBundle:
    def __init__(self, payload: dict[str, Any]):
        if payload.get("format") != "navila-reliability-portable-v1":
            raise ValueError(f"unsupported reliability artifact format: {payload.get('format')}")
        if payload.get("enforcement_approved") is not False:
            raise ValueError("portable reliability-v1 artifact has an invalid approval marker")
        self.payload = payload
        self.model_version = str(payload["model_version"])
        self.numeric_features = list(payload["numeric_features"])
        self.categorical_features = list(payload["categorical_features"])
        self.vectorizer = payload["vectorizer"]

    @classmethod
    def load(cls, path: str) -> "PortableReliabilityBundle":
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle))

    def _features(self, reading: object) -> dict[str, Any]:
        if isinstance(reading, dict):
            raw = dict(reading)
        else:
            raw = {name: getattr(reading, name, None) for name in self.numeric_features + self.categorical_features}
            if raw.get("corridor_degeneracy_ratio") is None:
                raw["corridor_degeneracy_ratio"] = getattr(reading, "degeneracy_ratio", None)
            if raw.get("icp_near_tie_basin_count") is None:
                raw["icp_near_tie_basin_count"] = getattr(reading, "near_tie_basin_count", None)
            if raw.get("icp_best_to_second_score_ratio") is None:
                raw["icp_best_to_second_score_ratio"] = getattr(reading, "best_to_second_score_ratio", None)
        return raw

    def _vectorize(self, row: dict[str, Any]) -> tuple[list[float], float, float]:
        vector = []
        missing = 0
        outside = 0
        present = 0
        for name in self.numeric_features:
            value = _number(row.get(name))
            is_missing = value is None
            if is_missing:
                missing += 1
                value = float(self.vectorizer["medians"][name])
            else:
                present += 1
                if value < float(self.vectorizer["lower_bounds"][name]) or value > float(self.vectorizer["upper_bounds"][name]):
                    outside += 1
            vector.extend((
                (float(value) - float(self.vectorizer["means"][name])) / float(self.vectorizer["scales"][name]),
                float(is_missing),
            ))
        for name in self.categorical_features:
            value = str(row.get(name) or "__missing__")
            categories = self.vectorizer["categories"][name]
            if value not in categories:
                value = "__unknown__"
            vector.extend(float(value == category) for category in categories)
        return vector, missing / max(1, len(self.numeric_features)), outside / max(1, present)

    @staticmethod
    def _tree_value(nodes: list[dict[str, Any]], vector: list[float]) -> float:
        index = 0
        while True:
            node = nodes[index]
            if node["is_leaf"]:
                return float(node["value"])
            if node["is_categorical"]:
                raise ValueError("portable runtime does not support categorical HGB splits")
            value = vector[int(node["feature_idx"])]
            index = int(node["left"] if value <= float(node["threshold"]) else node["right"])

    def _raw_probability(self, model: dict[str, Any], vector: list[float]) -> float:
        if model["type"] == "logistic_regression":
            score = float(model["intercept"]) + sum(
                float(weight) * value for weight, value in zip(model["coefficient"], vector)
            )
            return _sigmoid(score)
        if model["type"] == "hist_gradient_boosting_binary":
            score = float(model["baseline"])
            for tree in model["trees"]:
                score += self._tree_value(tree, vector)
            return _sigmoid(score)
        raise ValueError(f"unsupported portable model: {model['type']}")

    def predict_reading(self, reading: object) -> PortableReliabilityResult:
        row = self._features(reading)
        vector, missing_fraction, ood_fraction = self._vectorize(row)
        probabilities = {}
        for head, model in self.payload["models"].items():
            raw = min(max(self._raw_probability(model, vector), 1e-6), 1.0 - 1e-6)
            logit = math.log(raw / (1.0 - raw))
            calibration = self.payload["calibrators"][head]
            probabilities[head] = _sigmoid(float(calibration["slope"]) * logit + float(calibration["intercept"]))
        status = "trusted"
        if missing_fraction > float(self.payload["maximum_missing_fraction"]):
            status = "invalid"
        elif ood_fraction > float(self.payload["maximum_ood_fraction"]):
            status = "abstain"
        eligible = status == "trusted"
        thresholds = self.payload["trusted_thresholds"]
        return PortableReliabilityResult(
            p_bearing_bad_30=probabilities["bearing"],
            p_distance_bad_0p5=probabilities["distance"],
            p_pose_bad=probabilities["pose"],
            bearing_trusted=eligible and probabilities["bearing"] <= float(thresholds["bearing"]),
            distance_trusted=eligible and probabilities["distance"] <= float(thresholds["distance"]),
            pose_trusted=eligible and probabilities["pose"] <= float(thresholds["pose"]),
            status=status,
            missing_fraction=missing_fraction,
            ood_fraction=ood_fraction,
            model_version=self.model_version,
        )


@dataclass
class _State:
    observations: int = 0
    consecutive_high_risk: int = 0
    observations_since_low_risk: int = 0


class PortableTemporalController:
    def __init__(self, pose_high_risk_threshold: float, high_risk_consecutive: int, release_after_attempts: int):
        self.pose_high_risk_threshold = float(pose_high_risk_threshold)
        self.high_risk_consecutive = int(high_risk_consecutive)
        self.release_after_attempts = int(release_after_attempts)
        self.states: dict[int, _State] = {}

    def observe(self, anchor_index: int, anchor_role: str, result: PortableReliabilityResult) -> dict[str, Any]:
        state = self.states.setdefault(int(anchor_index), _State())
        state.observations += 1
        high_risk = result.status != "trusted" or result.p_pose_bad >= self.pose_high_risk_threshold
        if high_risk:
            state.consecutive_high_risk += 1
            state.observations_since_low_risk += 1
        else:
            state.consecutive_high_risk = 0
            state.observations_since_low_risk = 0
        persistent = state.consecutive_high_risk >= self.high_risk_consecutive
        release = state.observations_since_low_risk >= self.release_after_attempts
        return {
            "anchor_index": int(anchor_index),
            "anchor_role": str(anchor_role),
            "recommend_block_hint_override": not result.bearing_trusted,
            "recommend_defer_anchor_stop_authority": not result.distance_trusted,
            "recommend_block_promotion": anchor_role == "next" and persistent,
            "recommend_current_eviction": anchor_role == "current" and (persistent or release),
            "enforced_block_hint_override": False,
            "enforced_defer_anchor_stop_authority": False,
            "enforced_block_promotion": False,
            "enforced_current_eviction": False,
            "consecutive_pose_untrusted": state.consecutive_high_risk,
            "reason": "persistent_pose_risk" if persistent else "reading_observed",
            "reliability": result.as_dict(),
        }
