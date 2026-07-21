import numpy as np

from reliability.diagnostics import (
    add_attempt_phase,
    calibration_curve_equal_mass,
    expected_calibration_error,
)


def test_equal_mass_calibration_curve_and_ece():
    target = np.asarray([0, 0, 1, 1])
    probability = np.asarray([0.1, 0.2, 0.8, 0.9])
    weight = np.ones(4)
    curve = calibration_curve_equal_mass(target, probability, weight, bins=2)
    assert len(curve) == 2
    assert curve[0]["observed_bad_rate"] == 0.0
    assert curve[1]["observed_bad_rate"] == 1.0
    assert np.isclose(expected_calibration_error(curve), 0.15)


def test_attempt_phase_is_relative_within_episode():
    rows = [
        {"episode_key": "a", "attempt": 1},
        {"episode_key": "a", "attempt": 4},
        {"episode_key": "b", "attempt": 5},
        {"episode_key": "b", "attempt": 10},
    ]
    add_attempt_phase(rows)
    assert rows[0]["attempt_phase"] == "q1_early"
    assert rows[1]["attempt_phase"] == "q4_late"
    assert rows[2]["attempt_phase"] == "q2_mid_early"
    assert rows[3]["attempt_phase"] == "q4_late"
