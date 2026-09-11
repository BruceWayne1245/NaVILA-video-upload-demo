"""Integrity and inference checks for the development-only V1.1 artifact."""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from .v11_training import HEADS, load_v11_npz


FORBIDDEN_FEATURE_TOKENS = (
    "batch",
    "episode_id",
    "episode_key",
    "scene_id",
    "label_",
    "true_",
    "bearing_error",
    "distance_error",
    "return_success",
    "outbound_success",
    "robot_world",
    "anchor_index",
    "anchor_distance_from_start",
    "route_remaining_to_start",
    "estimated_remaining_to_start",
)


def validate_development_artifact(
    dataset_path: str | Path,
    artifact_path: str | Path,
    sample_rows: int = 1024,
) -> dict[str, Any]:
    data = load_v11_npz(dataset_path)
    with open(artifact_path, "rb") as handle:
        bundle = pickle.load(handle)
    feature_names = [str(name) for name in data["feature_names"]]
    forbidden = [
        name for name in feature_names
        if any(token in name for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    checks = {
        "development_only": bundle.get("development_only") is True,
        "prospective_validation_locked": bundle.get("prospective_validation_passed") is False,
        "schema_match": str(data["schema_version"]) == str(bundle.get("schema_version")),
        "feature_names_match": feature_names == list(bundle.get("feature_names") or []),
        "forbidden_features_absent": not forbidden,
        "all_heads_present": set(bundle.get("heads") or {}) == set(HEADS),
    }
    indices = np.linspace(0, len(data["features"]) - 1, min(sample_rows, len(data["features"])), dtype=int)
    inference = {}
    for head in HEADS:
        values = bundle["heads"][head]
        selected = np.asarray(values["feature_indices"], dtype=int)
        raw = values["model"].predict_proba(data["features"][indices][:, selected])[:, 1]
        probability = values["calibrator"].predict(raw)
        threshold = float(values["trusted_threshold"])
        inference[head] = {
            "candidate": values["candidate"],
            "features": len(selected),
            "probability_min": float(np.min(probability)),
            "probability_max": float(np.max(probability)),
            "probability_finite": bool(np.isfinite(probability).all()),
            "trusted_threshold": threshold,
            "trusted_count": int(np.sum(probability <= threshold)),
            "sample_rows": len(indices),
        }
        checks[f"{head}_probability_valid"] = bool(
            np.isfinite(probability).all() and np.all((probability >= 0) & (probability <= 1))
        )
        checks[f"{head}_threshold_locked"] = 0.0 <= threshold <= 1.0
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "forbidden_feature_names": forbidden,
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
        "artifact": str(artifact_path),
        "artifact_sha256": hashlib.sha256(Path(artifact_path).read_bytes()).hexdigest(),
        "sampled_inference": inference,
    }
