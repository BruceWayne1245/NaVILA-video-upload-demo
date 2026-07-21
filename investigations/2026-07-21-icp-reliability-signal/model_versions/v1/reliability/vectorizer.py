"""Small deterministic dense vectorizer that is easy to serialize and audit."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import numpy as np

from .schema import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass
class FeatureVectorizer:
    medians: dict[str, float] = field(default_factory=dict)
    means: dict[str, float] = field(default_factory=dict)
    scales: dict[str, float] = field(default_factory=dict)
    categories: dict[str, list[str]] = field(default_factory=dict)
    lower_bounds: dict[str, float] = field(default_factory=dict)
    upper_bounds: dict[str, float] = field(default_factory=dict)

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "FeatureVectorizer":
        materialized = list(rows)
        for name in NUMERIC_FEATURES:
            values = np.asarray([v for v in (_number(row.get(name)) for row in materialized) if v is not None])
            if values.size:
                median = float(np.median(values))
                mean = float(np.mean(values))
                scale = float(np.std(values))
                q_low, q_high = np.quantile(values, [0.001, 0.999])
                spread = max(float(q_high - q_low), scale, 1e-6)
                self.lower_bounds[name] = float(q_low - 0.1 * spread)
                self.upper_bounds[name] = float(q_high + 0.1 * spread)
            else:
                median, mean, scale = 0.0, 0.0, 1.0
                self.lower_bounds[name], self.upper_bounds[name] = -float("inf"), float("inf")
            self.medians[name] = median
            self.means[name] = mean
            self.scales[name] = scale if scale > 1e-9 else 1.0
        for name in CATEGORICAL_FEATURES:
            values = {str(row.get(name) or "__missing__") for row in materialized}
            values.add("__unknown__")
            self.categories[name] = sorted(values)
        return self

    @property
    def feature_names(self) -> list[str]:
        names = []
        for name in NUMERIC_FEATURES:
            names.extend((name, f"{name}__missing"))
        for name in CATEGORICAL_FEATURES:
            names.extend(f"{name}=={category}" for category in self.categories[name])
        return names

    def transform(self, rows: Iterable[Mapping[str, Any]]) -> np.ndarray:
        vectors = []
        for row in rows:
            vector = []
            for name in NUMERIC_FEATURES:
                value = _number(row.get(name))
                missing = value is None
                if missing:
                    value = self.medians[name]
                vector.extend(((float(value) - self.means[name]) / self.scales[name], float(missing)))
            for name in CATEGORICAL_FEATURES:
                value = str(row.get(name) or "__missing__")
                known = self.categories[name]
                if value not in known:
                    value = "__unknown__"
                vector.extend(float(value == category) for category in known)
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float64)

    def ood_summary(self, row: Mapping[str, Any]) -> tuple[float, float]:
        missing = 0
        outside = 0
        present = 0
        for name in NUMERIC_FEATURES:
            value = _number(row.get(name))
            if value is None:
                missing += 1
                continue
            present += 1
            if value < self.lower_bounds[name] or value > self.upper_bounds[name]:
                outside += 1
        return missing / max(1, len(NUMERIC_FEATURES)), outside / max(1, present)
