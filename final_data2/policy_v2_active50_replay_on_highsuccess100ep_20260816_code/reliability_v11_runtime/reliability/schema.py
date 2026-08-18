"""Versioned feature and label schema shared by training and live inference."""

from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = "reliability-v1.0"

# These fields are absolute diagnostics of one ICP reading. Identity, batch,
# ground truth, current-vs-next disagreement, and downstream outcomes are
# deliberately excluded.
NUMERIC_FEATURES = (
    "overlap_ratio",
    "corridor_degeneracy_ratio",
    "icp_near_tie_basin_count",
    "icp_basin_count",
    "icp_best_to_second_score_ratio",
    "icp_best_to_second_rotation_delta_deg",
    "icp_best_to_second_translation_delta_m",
    "confidence",
    "inlier_count",
    "mean_residual_m",
    "median_residual_m",
    "anchor_points",
    "current_points",
    "anchor_z_span_m",
    "current_z_span_m",
    "estimated_distance_to_anchor_m",
    "localizability_min_eigenvalue",
    "localizability_min_normalized_eigenvalue",
    "localizability_condition_number",
)

CATEGORICAL_FEATURES = (
    "match_class",
    "icp_ambiguity",
)

LABEL_COLUMNS = (
    "label_bearing_bad",
    "label_distance_bad",
    "label_pose_bad",
)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def features_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one covisibility record or AnchorRelocalization-like mapping."""
    result: dict[str, Any] = {}
    for name in NUMERIC_FEATURES:
        if name.startswith("localizability_"):
            continue
        result[name] = _finite_float(record.get(name))

    localizability = record.get("localizability")
    if not isinstance(localizability, Mapping):
        localizability = {}
    eigenvalues = localizability.get("eigenvalues")
    eigenvalues = [
        value for value in (_finite_float(v) for v in (eigenvalues or []))
        if value is not None
    ]
    result["localizability_min_eigenvalue"] = min(eigenvalues) if eigenvalues else _finite_float(
        record.get("localizability_min_eigenvalue")
    )
    result["localizability_min_normalized_eigenvalue"] = _finite_float(
        localizability.get(
            "min_normalized_eigenvalue",
            record.get("localizability_min_normalized_eigenvalue"),
        )
    )
    # This is intentionally max/min, sourced from the runtime diagnostic. The
    # old feasibility extractor accidentally stored min/max under loc_cond.
    result["localizability_condition_number"] = _finite_float(
        localizability.get("condition_number", record.get("localizability_condition_number"))
    )
    for name in CATEGORICAL_FEATURES:
        value = record.get(name)
        result[name] = str(value) if value not in (None, "") else "__missing__"
    return result


def feature_mapping_from_object(reading: object) -> dict[str, Any]:
    """Extract the same schema from a dataclass/object during live inference."""
    if isinstance(reading, Mapping):
        return features_from_record(reading)
    raw = {name: getattr(reading, name, None) for name in NUMERIC_FEATURES + CATEGORICAL_FEATURES}
    # RouteMemoryAgent historically calls this field degeneracy_ratio.
    if raw.get("corridor_degeneracy_ratio") is None:
        raw["corridor_degeneracy_ratio"] = getattr(reading, "degeneracy_ratio", None)
    if raw.get("icp_near_tie_basin_count") is None:
        raw["icp_near_tie_basin_count"] = getattr(reading, "near_tie_basin_count", None)
    if raw.get("icp_best_to_second_score_ratio") is None:
        raw["icp_best_to_second_score_ratio"] = getattr(reading, "best_to_second_score_ratio", None)
    return features_from_record(raw)
