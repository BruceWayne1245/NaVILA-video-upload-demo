"""Sklearn-free, shadow-only inference for a frozen Reliability V1.1 artifact."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


FORMAT = "navila-reliability-portable-v1.1"


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        exponential = math.exp(-value)
        return 1.0 / (1.0 + exponential)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _float32(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(numeric):
        return float("nan")
    return struct.unpack("<f", struct.pack("<f", numeric))[0]


@dataclass(frozen=True)
class PortableV11Result:
    p_bearing_bad_30: float
    p_distance_bad_0p5: float
    p_pose_bad: float
    bearing_trusted: bool
    distance_trusted: bool
    pose_trusted: bool
    jointly_trusted: bool
    status: str
    model_format: str = FORMAT

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortableV11Bundle:
    """Pure-Python tree traversal; all enforcement is structurally disabled."""

    def __init__(self, payload: Mapping[str, Any], *, mode: str = "shadow"):
        if mode != "shadow":
            raise RuntimeError("Reliability V1.1 enforcement is intentionally locked")
        if payload.get("format") != FORMAT:
            raise ValueError(f"unsupported artifact format: {payload.get('format')}")
        if payload.get("mode") != "shadow" or payload.get("enforcement_approved") is not False:
            raise ValueError("portable V1.1 artifact is not locked to shadow mode")
        self.payload = dict(payload)
        self.feature_names = [str(name) for name in payload["feature_names"]]
        self._feature_index = {
            name: index for index, name in enumerate(self.feature_names)
        }

    @classmethod
    def load(cls, path: str, *, mode: str = "shadow") -> "PortableV11Bundle":
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle), mode=mode)

    def vector_from_mapping(self, features: Mapping[str, Any]) -> list[float]:
        return [_float32(features.get(name)) for name in self.feature_names]

    @staticmethod
    def _tree_value(nodes: Sequence[Mapping[str, Any]], vector: Sequence[float]) -> float:
        node_index = 0
        while True:
            node = nodes[node_index]
            if bool(node["is_leaf"]):
                return float(node["value"])
            value = float(vector[int(node["feature_idx"])])
            if math.isnan(value):
                go_left = bool(node["missing_go_to_left"])
            else:
                go_left = value <= float(node["threshold"])
            node_index = int(node["left"] if go_left else node["right"])

    def _head_probability(self, head: str, full_vector: Sequence[float]) -> float:
        values = self.payload["heads"][head]
        selected = [full_vector[int(index)] for index in values["feature_indices"]]
        model = values["model"]
        if model.get("type") != "hist_gradient_boosting_binary":
            raise ValueError(f"unsupported portable estimator: {model.get('type')}")
        raw_score = float(model["baseline"])
        for tree in model["trees"]:
            raw_score += self._tree_value(tree, selected)
        raw_probability = min(max(_sigmoid(raw_score), 1e-6), 1.0 - 1e-6)
        raw_logit = math.log(raw_probability / (1.0 - raw_probability))
        calibrator = values["calibrator"]
        return _sigmoid(
            float(calibrator["slope"]) * raw_logit
            + float(calibrator["intercept"])
        )

    def predict_vector(self, vector: Sequence[float]) -> PortableV11Result:
        if len(vector) != len(self.feature_names):
            raise ValueError(
                f"feature width mismatch: got {len(vector)}, expected {len(self.feature_names)}"
            )
        probabilities = {
            head: self._head_probability(head, vector)
            for head in ("bearing", "distance", "pose")
        }
        trusted = {
            head: probabilities[head]
            <= float(self.payload["heads"][head]["trusted_threshold"])
            for head in probabilities
        }
        return PortableV11Result(
            p_bearing_bad_30=probabilities["bearing"],
            p_distance_bad_0p5=probabilities["distance"],
            p_pose_bad=probabilities["pose"],
            bearing_trusted=trusted["bearing"],
            distance_trusted=trusted["distance"],
            pose_trusted=trusted["pose"],
            jointly_trusted=all(trusted.values()),
            status="shadow",
        )

    def predict_features(self, features: Mapping[str, Any]) -> PortableV11Result:
        return self.predict_vector(self.vector_from_mapping(features))
