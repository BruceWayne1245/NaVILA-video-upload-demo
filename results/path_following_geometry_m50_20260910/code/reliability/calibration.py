"""Monotonic weighted Platt calibration without sklearn-version coupling."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


@dataclass
class PlattCalibrator:
    slope: float = 1.0
    intercept: float = 0.0

    def fit(self, probability: np.ndarray, target: np.ndarray, sample_weight: np.ndarray) -> "PlattCalibrator":
        probability = np.clip(np.asarray(probability, dtype=float), 1e-6, 1.0 - 1e-6)
        target = np.asarray(target, dtype=float)
        weight = np.asarray(sample_weight, dtype=float)
        logit = np.log(probability / (1.0 - probability))

        def objective(parameters: np.ndarray) -> float:
            slope, intercept = parameters
            prediction = expit(slope * logit + intercept)
            loss = -(target * np.log(prediction + 1e-12) + (1.0 - target) * np.log(1.0 - prediction + 1e-12))
            return float(np.average(loss, weights=weight) + 1e-6 * slope * slope)

        result = minimize(objective, np.asarray([1.0, 0.0]), method="L-BFGS-B", bounds=((0.0, 20.0), (-20.0, 20.0)))
        if result.success:
            self.slope, self.intercept = (float(result.x[0]), float(result.x[1]))
        return self

    def predict(self, probability: np.ndarray) -> np.ndarray:
        probability = np.clip(np.asarray(probability, dtype=float), 1e-6, 1.0 - 1e-6)
        logit = np.log(probability / (1.0 - probability))
        return expit(self.slope * logit + self.intercept)


def trusted_threshold(
    probability_bad: np.ndarray,
    target: np.ndarray,
    sample_weight: np.ndarray,
    maximum_bad_rate: float,
) -> float:
    """Largest low-risk prefix whose weighted empirical bad rate meets target."""
    order = np.argsort(probability_bad)
    p = np.asarray(probability_bad, dtype=float)[order]
    y = np.asarray(target, dtype=float)[order]
    w = np.asarray(sample_weight, dtype=float)[order]
    cumulative_rate = np.cumsum(w * y) / np.maximum(np.cumsum(w), 1e-12)
    valid = np.flatnonzero(cumulative_rate <= float(maximum_bad_rate))
    return float(p[valid[-1]]) if valid.size else 0.0
