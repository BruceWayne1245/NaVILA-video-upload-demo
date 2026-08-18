"""Export sklearn models to the dependency-free candidate runtime format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .bundle import ReliabilityBundle
from .schema import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def _tree_nodes(predictor: Any) -> list[dict[str, Any]]:
    output = []
    for node in predictor.nodes:
        output.append({
            "value": float(node["value"]),
            "feature_idx": int(node["feature_idx"]),
            "threshold": float(node["num_threshold"]),
            "missing_go_to_left": bool(node["missing_go_to_left"]),
            "left": int(node["left"]),
            "right": int(node["right"]),
            "is_leaf": bool(node["is_leaf"]),
            "is_categorical": bool(node["is_categorical"]),
        })
    return output


def _model_payload(model: Any) -> dict[str, Any]:
    name = type(model).__name__
    if name == "LogisticRegression":
        return {
            "type": "logistic_regression",
            "coefficient": [float(value) for value in np.ravel(model.coef_)],
            "intercept": float(np.ravel(model.intercept_)[0]),
        }
    if name == "HistGradientBoostingClassifier":
        return {
            "type": "hist_gradient_boosting_binary",
            "baseline": float(np.ravel(model._baseline_prediction)[0]),
            "trees": [_tree_nodes(stage[0]) for stage in model._predictors],
        }
    raise TypeError(f"portable export does not support {name}")


def portable_payload(bundle: ReliabilityBundle) -> dict[str, Any]:
    vectorizer = bundle.vectorizer
    return {
        "format": "navila-reliability-portable-v1",
        "schema_version": bundle.schema_version,
        "model_version": bundle.model_version,
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "vectorizer": {
            "medians": vectorizer.medians,
            "means": vectorizer.means,
            "scales": vectorizer.scales,
            "categories": vectorizer.categories,
            "lower_bounds": vectorizer.lower_bounds,
            "upper_bounds": vectorizer.upper_bounds,
        },
        "models": {head: _model_payload(model) for head, model in bundle.models.items()},
        "calibrators": {
            head: {"slope": calibrator.slope, "intercept": calibrator.intercept}
            for head, calibrator in bundle.calibrators.items()
        },
        "trusted_thresholds": bundle.trusted_thresholds,
        "maximum_missing_fraction": bundle.maximum_missing_fraction,
        "maximum_ood_fraction": bundle.maximum_ood_fraction,
        "enforcement_approved": False,
    }


def export_portable(bundle: ReliabilityBundle, path: str | Path) -> None:
    Path(path).write_text(json.dumps(portable_payload(bundle), separators=(",", ":")), encoding="utf-8")
