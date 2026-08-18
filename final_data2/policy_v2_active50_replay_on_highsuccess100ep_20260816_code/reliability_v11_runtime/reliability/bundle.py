"""Serializable three-head reliability model bundle."""

from __future__ import annotations

import pickle
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .calibration import PlattCalibrator
from .schema import SCHEMA_VERSION, feature_mapping_from_object
from .vectorizer import FeatureVectorizer


@dataclass(frozen=True)
class ReliabilityResult:
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


@dataclass
class ReliabilityBundle:
    vectorizer: FeatureVectorizer
    models: dict[str, Any]
    calibrators: dict[str, PlattCalibrator]
    trusted_thresholds: dict[str, float]
    model_version: str
    schema_version: str = SCHEMA_VERSION
    maximum_missing_fraction: float = 0.35
    maximum_ood_fraction: float = 0.15

    def _probability(self, head: str, matrix: np.ndarray) -> np.ndarray:
        raw = self.models[head].predict_proba(matrix)[:, 1]
        return self.calibrators[head].predict(raw)

    def predict_features(self, features: Mapping[str, Any]) -> ReliabilityResult:
        return self.predict_features_many([features])[0]

    def predict_features_many(self, features: list[Mapping[str, Any]]) -> list[ReliabilityResult]:
        """Vectorized batch inference for replay and report generation."""
        if not features:
            return []
        matrix = self.vectorizer.transform(features)
        probabilities = {head: self._probability(head, matrix) for head in self.models}
        output = []
        for index, row in enumerate(features):
            missing_fraction, ood_fraction = self.vectorizer.ood_summary(row)
            status = "trusted"
            if missing_fraction > self.maximum_missing_fraction:
                status = "invalid"
            elif ood_fraction > self.maximum_ood_fraction:
                status = "abstain"
            eligible = status == "trusted"
            bearing = float(probabilities["bearing"][index])
            distance = float(probabilities["distance"][index])
            pose = float(probabilities["pose"][index])
            output.append(ReliabilityResult(
                p_bearing_bad_30=bearing,
                p_distance_bad_0p5=distance,
                p_pose_bad=pose,
                bearing_trusted=eligible and bearing <= self.trusted_thresholds["bearing"],
                distance_trusted=eligible and distance <= self.trusted_thresholds["distance"],
                pose_trusted=eligible and pose <= self.trusted_thresholds["pose"],
                status=status,
                missing_fraction=missing_fraction,
                ood_fraction=ood_fraction,
                model_version=self.model_version,
            ))
        return output

    def predict_reading(self, reading: object) -> ReliabilityResult:
        return self.predict_features(feature_mapping_from_object(reading))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            pickle.dump(self, handle, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str | Path) -> "ReliabilityBundle":
        with open(path, "rb") as handle:
            bundle = pickle.load(handle)
        if not isinstance(bundle, cls):
            raise TypeError(f"artifact is {type(bundle)!r}, expected ReliabilityBundle")
        if bundle.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema mismatch: artifact={bundle.schema_version}, runtime={SCHEMA_VERSION}")
        return bundle
