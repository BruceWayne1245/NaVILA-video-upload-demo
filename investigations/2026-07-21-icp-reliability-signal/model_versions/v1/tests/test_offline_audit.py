import numpy as np

from reliability.audit import grouped_macro_metrics, risk_coverage_curve


def test_risk_coverage_uses_lowest_risk_prefixes():
    target = np.asarray([0, 0, 1, 1])
    score = np.asarray([0.1, 0.2, 0.8, 0.9])
    weight = np.ones(4)
    curve = risk_coverage_curve(target, score, weight, [0.5, 1.0])
    assert curve[0]["coverage"] == 0.5
    assert curve[0]["bad_rate"] == 0.0
    assert curve[1]["coverage"] == 1.0
    assert curve[1]["bad_rate"] == 0.5


def test_grouped_macro_does_not_let_long_episode_dominate():
    rows = [
        {"episode_key": "short"},
        {"episode_key": "long"},
        {"episode_key": "long"},
        {"episode_key": "long"},
    ]
    target = np.asarray([1, 0, 0, 0])
    score = np.asarray([0.9, 0.1, 0.1, 0.1])
    metrics = grouped_macro_metrics(rows, target, score, 0.5, "episode_key")
    assert metrics["groups"] == 2
    assert metrics["positive_rate"] == 0.5
    assert metrics["trusted_coverage"] == 0.5
