import math
import unittest

from path_following_geometry import DeterministicPathFollower, PathFollowingConfig


class TestDeterministicPathFollower(unittest.TestCase):
    def setUp(self):
        self.controller = DeterministicPathFollower(PathFollowingConfig(lookahead_m=0.5))

    def test_follows_l_corner_without_cutting_to_start(self):
        path = [(0, 0), (2, 0), (2, 2)]
        decision = self.controller.decide(path, (2, 1.8, -math.pi / 2), 2.7)
        self.assertEqual(decision.kind, "forward")
        self.assertAlmostEqual(decision.target_s_m, 3.3, places=5)

    def test_turns_toward_reverse_path(self):
        path = [(0, 0), (2, 0), (2, 2)]
        decision = self.controller.decide(path, (2, 1.8, 0.0), 2.7)
        self.assertEqual(decision.kind, "turn_right")
        self.assertLess(decision.command[2], 0.0)

    def test_stops_only_at_start_end_of_polyline(self):
        decision = self.controller.decide([(0, 0), (1, 0)], (0.1, 0.0, math.pi), 0.1)
        self.assertEqual(decision.kind, "stop")
        self.assertEqual(decision.duration_seconds, 0.0)

    def test_external_stop_gate_can_own_termination(self):
        controller = DeterministicPathFollower(
            PathFollowingConfig(lookahead_m=0.5, allow_stop=False)
        )
        decision = controller.decide([(0, 0), (1, 0)], (0.1, 0.0, math.pi), 0.1)
        self.assertNotEqual(decision.kind, "stop")
        self.assertGreater(decision.duration_seconds, 0.0)

    def test_turn_hysteresis(self):
        path = [(0, 0), (2, 0)]
        first = self.controller.decide(path, (1.5, 0.0, math.pi - math.radians(35)), 1.5)
        second = self.controller.decide(path, (1.5, 0.0, math.pi - math.radians(18)), 1.5)
        third = self.controller.decide(path, (1.5, 0.0, math.pi - math.radians(8)), 1.5)
        self.assertTrue(first.kind.startswith("turn_"))
        self.assertTrue(second.kind.startswith("turn_"))
        self.assertEqual(third.kind, "forward")


if __name__ == "__main__":
    unittest.main()
