import numpy as np

from reliability.v11_dataset import (
    add_causal_temporal_features,
    add_pair_features,
    base_features,
)


def _source(role="current"):
    return {
        "anchor_role": role,
        "confidence": 0.8,
        "overlap_ratio": 0.7,
        "median_residual_m": 0.1,
        "corridor_degeneracy_ratio": 0.3,
        "icp_best_to_second_score_ratio": 1.2,
        "icp_near_tie_basin_count": 2,
        "estimated_distance_to_anchor_m": 1.0,
        **{name: 0.0 for name in (
            "icp_basin_count", "icp_best_to_second_rotation_delta_deg",
            "icp_best_to_second_translation_delta_m", "inlier_count", "mean_residual_m",
            "anchor_points", "current_points", "anchor_z_span_m", "current_z_span_m",
            "localizability_min_eigenvalue", "localizability_min_normalized_eigenvalue",
            "localizability_condition_number",
        )},
    }


def _record(confidence=0.8):
    return {
        "confidence": confidence,
        "estimated_bearing_to_anchor_deg": 10.0,
        "estimated_distance_to_anchor_m": 1.0,
        "estimated_anchor_dx_m": 1.0,
        "estimated_anchor_dy_m": 0.0,
        "estimated_anchor_dtheta_deg": 5.0,
        "route_remaining_to_start_m": 2.0,
        "anchor_distance_from_start_m": 2.0,
        "icp_top_basins": [
            {"score": 5.0, "seed_count": 2, "overlap_ratio": 0.7,
             "median_residual_m": 0.1, "inlier_count": 100,
             "estimated_anchor_dx_m": 1.0, "estimated_anchor_dy_m": 0.0,
             "estimated_anchor_dtheta_deg": 5.0},
            {"score": 4.0, "seed_count": 1, "overlap_ratio": 0.6,
             "median_residual_m": 0.2, "inlier_count": 80,
             "estimated_anchor_dx_m": 0.5, "estimated_anchor_dy_m": 0.5,
             "estimated_anchor_dtheta_deg": 95.0},
        ],
        "yaw_curve": {"available": True, "yaw_score_normalized_entropy": 0.9},
        "scan_context_yaw_check": {
            "available": True,
            "scan_context_similarity": 0.6,
            "icp_scan_context_yaw_agreement_deg": 4.0,
        },
    }


def test_full_basin_features_are_extracted():
    features = base_features(_record(), _source())
    assert features["basin_1_score"] == 5.0
    assert features["basin_2_estimated_anchor_dtheta_deg"] == 95.0
    assert features["basin_score_gap_1_2"] == 1.0
    assert features["basin_top4_present"] == 2.0
    assert features["scan_context_yaw_agreement_deg"] == 4.0
    assert features["match_class____missing__"] == 1.0


def test_pair_features_use_same_attempt_only():
    rows = []
    for anchor, role, confidence in ((2, "current", 0.8), (1, "next", 0.5)):
        source = _source(role)
        source["confidence"] = confidence
        rows.append({
            "episode_key": "ep", "attempt": 1, "anchor_index": anchor,
            "anchor_role": role, "features": base_features(_record(confidence), source),
        })
    add_pair_features(rows)
    assert np.isclose(rows[0]["features"]["pair_confidence_signed_diff"], 0.3)
    assert rows[0]["features"]["pair_available"] == 1.0
    assert "route_remaining_to_start_m" not in rows[0]["features"]
    assert "estimated_bearing_to_anchor_deg" not in rows[0]["features"]


def test_temporal_windows_are_causal_and_anchor_local():
    rows = []
    for attempt, confidence in ((1, 0.2), (2, 0.4), (3, 0.8)):
        source = _source()
        source["confidence"] = confidence
        rows.append({
            "episode_key": "ep", "attempt": attempt, "anchor_index": 2,
            "anchor_role": "current", "features": base_features(_record(confidence), source),
        })
    add_causal_temporal_features(rows)
    assert rows[0]["features"]["temporal_confidence_w4_mean"] == 0.2
    assert np.isclose(rows[1]["features"]["temporal_confidence_w4_mean"], 0.3)
    assert np.isclose(rows[2]["features"]["temporal_confidence_delta_1"], 0.4)
    assert rows[0]["features"]["temporal_history_count_including_current"] == 1.0
