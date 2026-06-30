import unittest
from types import SimpleNamespace

import numpy as np

from hint_action_arbiter import HintActionArbiter, HintActionArbiterConfig


class FakeTopDownMap:
    def __init__(self, image):
        self.image = image
        self.meta = {
            "min_x": -2.0,
            "max_x": 2.0,
            "min_y": -2.0,
            "max_y": 2.0,
            "resolution_m_per_px": 0.05,
        }


def progress(dx, dy, bearing, distance=1.0, anchor=10):
    return SimpleNamespace(
        anchor_dx_m=dx,
        anchor_dy_m=dy,
        distance_to_anchor_m=distance,
        bearing_to_anchor_deg=bearing,
        target_anchor_index=anchor,
    )


def clear_map():
    return FakeTopDownMap(np.full((81, 81, 3), 245, dtype=np.uint8))


class HintActionArbiterTests(unittest.TestCase):
    def make_arbiter(self, **kwargs):
        cfg = HintActionArbiterConfig(
            robot_radius_m=0.10,
            clearance_margin_m=0.05,
            **kwargs,
        )
        return HintActionArbiter(cfg)

    def test_overrides_left_turn_when_hint_is_ahead(self):
        decision = self.make_arbiter().check(
            progress=progress(1.02, -0.17, -9.5),
            vlm_output="The next action is turn left 45 degree.",
            robot_position=[0.0, 0.0, 0.0],
            robot_yaw_rad=0.0,
            topdown_map=clear_map(),
        )
        self.assertTrue(decision.override)
        self.assertEqual(decision.desired_kind, "forward")
        self.assertEqual(decision.replacement_output, "The next action is move forward 75 cm.")

    def test_overrides_forward_when_hint_is_strongly_right(self):
        decision = self.make_arbiter().check(
            progress=progress(0.71, -0.65, -42.4),
            vlm_output="The next action is move forward 75 cm.",
            robot_position=[0.0, 0.0, 0.0],
            robot_yaw_rad=0.0,
            topdown_map=clear_map(),
        )
        self.assertTrue(decision.override)
        self.assertEqual(decision.desired_kind, "right")
        self.assertEqual(decision.replacement_output, "The next action is turn right 45 degree.")

    def test_does_not_override_when_hint_path_is_blocked(self):
        image = np.full((81, 81, 3), 245, dtype=np.uint8)
        image[35:46, 45:56] = 55
        decision = self.make_arbiter().check(
            progress=progress(1.0, 0.0, 0.0),
            vlm_output="The next action is turn left 45 degree.",
            robot_position=[0.0, 0.0, 0.0],
            robot_yaw_rad=0.0,
            topdown_map=FakeTopDownMap(image),
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "occupied_in_hint_path")

    def test_requires_clear_path_unless_explicitly_allowed(self):
        strict = self.make_arbiter()
        decision = strict.check(
            progress=progress(1.0, 0.0, 0.0),
            vlm_output="The next action is turn left 45 degree.",
            robot_position=[0.0, 0.0, 0.0],
            robot_yaw_rad=0.0,
            topdown_map=None,
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "clear_path_unavailable")

        permissive = self.make_arbiter(allow_without_clear_path=True)
        decision = permissive.check(
            progress=progress(1.0, 0.0, 0.0),
            vlm_output="The next action is turn left 45 degree.",
            robot_position=[0.0, 0.0, 0.0],
            robot_yaw_rad=0.0,
            topdown_map=None,
        )
        self.assertTrue(decision.override)


if __name__ == "__main__":
    unittest.main()
