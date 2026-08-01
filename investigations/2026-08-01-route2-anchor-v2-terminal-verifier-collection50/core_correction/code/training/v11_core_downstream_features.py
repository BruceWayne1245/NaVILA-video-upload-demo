"""Feature firewall for Route 2 models downstream of Reliability V1.1.

Downstream models receive task geometry and context plus V1.1 outputs.  They
must not reconstruct a competing reliability classifier from raw ICP quality
diagnostics or the legacy hand-written reliability score.
"""

from __future__ import annotations

from typing import Mapping


RAW_CANDIDATE_QUALITY_TOKENS = (
    ".confidence",
    ".inlier_count",
    ".overlap_ratio",
    ".mean_residual_m",
    ".median_residual_m",
    ".corridor_degeneracy_ratio",
    ".icp_ambiguity",
    ".icp_basin_count",
    ".icp_near_tie_basin_count",
    ".icp_best_to_second_",
    ".match_class",
    ".localizability.",
    ".scan_context.",
    ".yaw_curve.",
)
RAW_AGGREGATE_PREFIXES = (
    "candidate_agg.confidence.",
    "candidate_agg.icp_best_to_second_score_ratio.",
    "candidate_agg.inlier_count.",
    "candidate_agg.median_residual_m.",
    "candidate_agg.overlap_ratio.",
)
RAW_AGGREGATE_TOKENS = (
    "confidence",
    "inlier",
    "residual",
    "overlap",
    "icp_",
    "corridor",
    "scan_context",
    "yaw_curve",
    "localizability",
)
LEGACY_AUTHORITY_TOKENS = (
    "route_memory.relocalization_confidence",
    "route_memory.estimate_source_confidence",
    "route_memory.estimate_target_raw_confidence",
    "proposal.relocalization_confidence",
    "legacy_u",
    "unreliability_score",
)


def is_v11_feature(name: str) -> bool:
    return (
        ".v11." in name
        or any(
            token in name
            for token in (
                "candidate_agg.p_bearing_bad_30",
                "candidate_agg.bearing_trusted_fraction",
                "candidate_agg.p_distance_bad_0p5",
                "candidate_agg.distance_trusted_fraction",
                "candidate_agg.p_pose_bad",
                "candidate_agg.pose_trusted_fraction",
            )
        )
    )


V11_HEAD_TOKENS = {
    "bearing": ("p_bearing_bad_30", "bearing_trusted"),
    "distance": ("p_distance_bad_0p5", "distance_trusted"),
    "pose": ("p_pose_bad", "pose_trusted"),
}


def is_v11_feature_for_head(name: str, required_head: str) -> bool:
    if required_head not in V11_HEAD_TOKENS:
        raise ValueError(f"unsupported downstream V1.1 head: {required_head}")
    if not is_v11_feature(name):
        return False
    if "anchor_role" in name:
        return True
    return any(token in name for token in V11_HEAD_TOKENS[required_head])


def is_forbidden_raw_quality_feature(name: str) -> bool:
    if is_v11_feature(name):
        return False
    if name.startswith(("candidate.current.", "candidate.next.")):
        return any(token in name for token in RAW_CANDIDATE_QUALITY_TOKENS)
    if name.startswith("temporal.candidate."):
        return any(token in name for token in RAW_CANDIDATE_QUALITY_TOKENS)
    if name.startswith(RAW_AGGREGATE_PREFIXES):
        return True
    if name.startswith("candidate_agg.") and any(
        token in name for token in RAW_AGGREGATE_TOKENS
    ):
        return True
    if any(token in name for token in LEGACY_AUTHORITY_TOKENS):
        return True
    return False


def filter_core_features(
    features: Mapping[str, float], *, required_head: str | None = None
) -> dict[str, float]:
    filtered = {
        str(name): float(value)
        for name, value in features.items()
        if (
            not is_forbidden_raw_quality_feature(str(name))
            and (
                required_head is None
                or not is_v11_feature(str(name))
                or is_v11_feature_for_head(str(name), required_head)
            )
        )
    }
    assert_core_compliant(filtered, required_head=required_head)
    return filtered


def assert_core_compliant(
    features: Mapping[str, float], *, required_head: str | None = None
) -> None:
    forbidden = [
        name for name in features if is_forbidden_raw_quality_feature(str(name))
    ]
    if forbidden:
        raise RuntimeError(
            "downstream feature set bypasses Reliability V1.1: "
            + ", ".join(sorted(map(str, forbidden))[:10])
        )
    if required_head is not None:
        wrong_head = [
            str(name)
            for name in features
            if is_v11_feature(str(name))
            and not is_v11_feature_for_head(str(name), required_head)
        ]
        if wrong_head:
            raise RuntimeError(
                f"downstream feature set bypasses {required_head} head ownership: "
                + ", ".join(sorted(wrong_head)[:10])
            )
