"""Export the frozen V1.1 HGB artifact to a sklearn-free shadow format."""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, Mapping

import numpy as np


FORMAT = "navila-reliability-portable-v1.1"


def _tree_nodes(predictor: Any) -> list[dict[str, Any]]:
    nodes = []
    for node in predictor.nodes:
        if bool(node["is_categorical"]):
            raise ValueError("V1.1 portable runtime does not support categorical HGB splits")
        nodes.append({
            "value": float(node["value"]),
            "feature_idx": int(node["feature_idx"]),
            "threshold": float(node["num_threshold"]),
            "missing_go_to_left": bool(node["missing_go_to_left"]),
            "left": int(node["left"]),
            "right": int(node["right"]),
            "is_leaf": bool(node["is_leaf"]),
        })
    return nodes


def _model_payload(model: Any) -> dict[str, Any]:
    if type(model).__name__ != "HistGradientBoostingClassifier":
        raise TypeError(f"unsupported V1.1 estimator: {type(model).__name__}")
    if int(model.n_trees_per_iteration_) != 1:
        raise ValueError("only binary one-tree-per-stage HGB is supported")
    return {
        "type": "hist_gradient_boosting_binary",
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": [_tree_nodes(stage[0]) for stage in model._predictors],
    }


def portable_v11_payload(
    artifact: Mapping[str, Any],
    *,
    source_artifact_sha256: str,
) -> dict[str, Any]:
    heads = {}
    for name, values in artifact["heads"].items():
        calibrator = values["calibrator"]
        heads[str(name)] = {
            "candidate": str(values["candidate"]),
            "feature_indices": [int(index) for index in values["feature_indices"]],
            "model": _model_payload(values["model"]),
            "calibrator": {
                "slope": float(calibrator.slope),
                "intercept": float(calibrator.intercept),
            },
            "trusted_threshold": float(values["trusted_threshold"]),
        }
    return {
        "format": FORMAT,
        "schema_version": str(artifact["schema_version"]),
        "feature_names": [str(name) for name in artifact["feature_names"]],
        "source_artifact_sha256": str(source_artifact_sha256),
        "development_only": bool(artifact.get("development_only")),
        "source_prospective_validation_marker": bool(
            artifact.get("prospective_validation_passed")
        ),
        "mode": "shadow",
        "enforcement_approved": False,
        "heads": heads,
    }


def export_v11_portable(
    artifact_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    source = Path(artifact_path)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    with source.open("rb") as handle:
        artifact = pickle.load(handle)
    payload = portable_v11_payload(
        artifact, source_artifact_sha256=source_sha
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return {
        "portable_artifact": str(output),
        "portable_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "portable_size_bytes": output.stat().st_size,
        "source_artifact": str(source),
        "source_artifact_sha256": source_sha,
        "features": len(payload["feature_names"]),
        "heads": sorted(payload["heads"]),
        "mode": "shadow",
        "enforcement_approved": False,
    }
