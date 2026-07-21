from reliability.bundle import ReliabilityResult
from reliability.policy import ReliabilityTemporalController
from reliability.schema import features_from_record


def test_condition_number_uses_runtime_value_not_inverse():
    features = features_from_record({
        "localizability": {
            "eigenvalues": [2.0, 4.0, 20.0],
            "min_normalized_eigenvalue": 0.1,
            "condition_number": 10.0,
        }
    })
    assert features["localizability_min_eigenvalue"] == 2.0
    assert features["localizability_condition_number"] == 10.0


def _result(*, pose_trusted: bool, bearing_trusted: bool = True, distance_trusted: bool = True):
    return ReliabilityResult(
        p_bearing_bad_30=0.1,
        p_distance_bad_0p5=0.1,
        p_pose_bad=0.9 if not pose_trusted else 0.1,
        bearing_trusted=bearing_trusted,
        distance_trusted=distance_trusted,
        pose_trusted=pose_trusted,
        status="trusted",
        missing_fraction=0.0,
        ood_fraction=0.0,
        model_version="test",
    )


def test_shadow_mode_recommends_but_never_enforces():
    controller = ReliabilityTemporalController(mode="shadow", high_risk_consecutive=3, enable_current_eviction=True)
    for _ in range(2):
        decision = controller.observe(6, "current", _result(pose_trusted=False))
        assert not decision.recommend_current_eviction
    decision = controller.observe(6, "current", _result(pose_trusted=False))
    assert decision.recommend_current_eviction
    assert not decision.enforced_current_eviction


def test_enforcement_requires_both_mode_and_consumer_switch():
    controller = ReliabilityTemporalController(mode="enforce", enable_hint_arbiter=True, enable_stop_gate=False)
    decision = controller.observe(
        2,
        "current",
        _result(pose_trusted=True, bearing_trusted=False, distance_trusted=False),
    )
    assert decision.enforced_block_hint_override
    assert not decision.enforced_defer_anchor_stop_authority
