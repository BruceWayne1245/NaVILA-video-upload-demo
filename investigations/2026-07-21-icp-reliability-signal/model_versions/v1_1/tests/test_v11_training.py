import numpy as np

from reliability.v11_training import (
    conservative_cluster_threshold,
    feature_indices,
    physical_episode_balanced_weights,
)


def test_physical_episode_weights_equalize_repeated_runs():
    groups = np.asarray([1, 1, 1, 2])
    weight = physical_episode_balanced_weights(groups)
    assert np.isclose(weight[groups == 1].sum(), weight[groups == 2].sum())


def test_feature_sets_never_add_nonfeature_metadata():
    names = np.asarray([
        "confidence", "basin_1_score", "pair_confidence_abs_diff",
        "temporal_confidence_w4_mean", "match_class__clean_full_pose",
    ])
    assert feature_indices(names, "v1").tolist() == [0, 4]
    assert feature_indices(names, "basin").tolist() == [0, 1, 4]
    assert feature_indices(names, "basin_pair").tolist() == [0, 1, 2, 4]
    assert feature_indices(names, "full").tolist() == [0, 1, 2, 3, 4]


def test_conservative_threshold_can_abstain_when_upper_bound_fails():
    probability = np.asarray([0.1, 0.2, 0.3, 0.4])
    target = np.asarray([1, 1, 1, 1])
    weight = np.ones(4)
    groups = np.asarray([1, 2, 3, 4])
    result = conservative_cluster_threshold(
        probability, target, weight, groups, maximum_bad_rate=0.05,
        bootstrap_samples=100, seed=0,
    )
    assert result["selected"]["target_met"] is False
    assert result["selected"]["coverage"] == 0.0
