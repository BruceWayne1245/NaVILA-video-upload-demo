import pytest

from reliability.schema import feature_mapping_from_object
from route_memory_agent import AnchorRelocalization
from reliability_integration import ReliabilityShadowRuntime


def test_runtime_rejects_enforcement_before_loading_artifact():
    with pytest.raises(RuntimeError, match="enforcement is intentionally locked"):
        ReliabilityShadowRuntime("does-not-matter.pkl", mode="enforce")


def test_runtime_object_aliases_match_training_schema():
    reading = AnchorRelocalization(
        anchor_index=2,
        anchor_dx_m=1.0,
        anchor_dy_m=0.0,
        degeneracy_ratio=0.4,
        near_tie_basin_count=3,
        best_to_second_score_ratio=0.95,
    )
    features = feature_mapping_from_object(reading)
    assert features["corridor_degeneracy_ratio"] == 0.4
    assert features["icp_near_tie_basin_count"] == 3
    assert features["icp_best_to_second_score_ratio"] == 0.95


def test_frozen_artifact_scores_candidates_in_shadow_mode():
    runtime = ReliabilityShadowRuntime("artifacts/reliability_v1_portable.json")
    current = AnchorRelocalization(
        anchor_index=2,
        anchor_dx_m=1.0,
        anchor_dy_m=0.1,
        confidence=0.9,
        inlier_count=200,
        overlap_ratio=0.7,
        mean_residual_m=0.1,
        median_residual_m=0.1,
        anchor_points=500,
        current_points=500,
        anchor_z_span_m=1.0,
        current_z_span_m=1.0,
        icp_basin_count=2,
        near_tie_basin_count=0,
        best_to_second_score_ratio=0.8,
        match_class="clean_full_pose",
        icp_ambiguity="single_mode",
    )
    diagnostics = {}
    scored = runtime.score_candidates([current], diagnostics)
    assert scored[0].reliability_model_version == "reliability-v1-8f2097ec5028"
    assert 0.0 <= scored[0].reliability_pose_bad_probability <= 1.0
    assert scored[0].reliability_policy["enforced_current_eviction"] is False
    assert len(diagnostics["reliability_records"]) == 1
    assert diagnostics["reliability_runtime"]["calls"] == 1
    assert diagnostics["reliability_runtime"]["candidates"] == 1
    assert diagnostics["reliability_runtime"]["mean_candidate_ms"] >= 0.0
