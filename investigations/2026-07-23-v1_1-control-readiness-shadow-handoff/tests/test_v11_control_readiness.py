from tools.score_v11_control_readiness import (
    _cluster_risk_ucb,
    _longest_full_defer_streaks,
)


def test_control_readiness_longest_defer_streak_respects_attempt_gaps():
    decisions = [
        {
            "physical_episode_id": 1,
            "attempt": attempt,
            "counterfactual": {
                "would_defer_entire_relocalization_update": deferred
            },
        }
        for attempt, deferred in (
            (1, True),
            (2, True),
            (4, True),
            (5, False),
            (6, True),
        )
    ]
    assert _longest_full_defer_streaks(decisions) == {1: 2}


def test_control_readiness_cluster_ucb_uses_forwarded_rows_only():
    rows = [
        {
            "episode_id": 1,
            "forwarded": True,
            "label_pose_bad": 0,
        },
        {
            "episode_id": 1,
            "forwarded": False,
            "label_pose_bad": 1,
        },
        {
            "episode_id": 2,
            "forwarded": True,
            "label_pose_bad": 0,
        },
    ]
    assert _cluster_risk_ucb(
        rows,
        label="label_pose_bad",
        samples=100,
        seed=1,
    ) == 0.0
