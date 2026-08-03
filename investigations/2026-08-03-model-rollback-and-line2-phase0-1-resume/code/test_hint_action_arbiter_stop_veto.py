"""Unit tests for the 2026-08-03 hint_action_arbiter stop-veto split
(line-2 Phase 1.2, mechanism E -- investigations/2026-07-28-downgrade-batch-
mechanism-failure-classification/FINDINGS.md/MODIFICATION_PLAN.md).

min_relocalization_confidence previously gated both direction-override and
stop-suppression under one bar (default 0.90); below it an erroneous
voluntary stop sailed through unchallenged. stop_veto_enabled adds an
independently-gated suppression path for `stop` specifically, using a lower
confidence bar and the anchor's own static route_remaining (mirrors
stop_gate's own anchor-corroboration veto).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hint_action_arbiter import HintActionArbiter, HintActionArbiterConfig  # noqa: E402


class _Progress:
    def __init__(self, bearing, distance, confidence, anchor_route_remaining_m=None,
                 anchor_dx_m=None, anchor_dy_m=None):
        self.bearing_to_anchor_deg = bearing
        self.distance_to_anchor_m = distance
        self.bearing_to_start_deg = bearing
        self.distance_to_start_m = distance
        self.target_anchor_index = 3
        self.relocalization_confidence = confidence
        self.anchor_route_remaining_m = anchor_route_remaining_m
        self.anchor_dx_m = anchor_dx_m
        self.anchor_dy_m = anchor_dy_m


def _arbiter(**kw):
    cfg = HintActionArbiterConfig(
        min_relocalization_confidence=0.90,
        stop_veto_min_confidence=0.5,
        stop_veto_anchor_remaining_min_m=3.0,
        **kw,
    )
    return HintActionArbiter(cfg)


class StopVetoTest(unittest.TestCase):
    def test_off_by_default_does_not_suppress_low_confidence_stop(self):
        arbiter = _arbiter()  # stop_veto_enabled left at its dataclass default (False)
        progress = _Progress(bearing=10.0, distance=5.0, confidence=0.3, anchor_route_remaining_m=10.0)
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is stop.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "low_relocalization_confidence")

    def test_suppresses_low_confidence_stop_when_anchor_far(self):
        arbiter = _arbiter(stop_veto_enabled=True)
        progress = _Progress(bearing=10.0, distance=5.0, confidence=0.3, anchor_route_remaining_m=10.0)
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is stop.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        self.assertTrue(decision.override)
        self.assertEqual(decision.reason, "stop_veto_anchor_far")
        self.assertIn("forward", decision.replacement_output)

    def test_does_not_suppress_when_anchor_itself_close(self):
        # anchor_route_remaining_m below the threshold -- corroboration
        # disagrees (anchor says close), so do not override.
        arbiter = _arbiter(stop_veto_enabled=True)
        progress = _Progress(bearing=10.0, distance=5.0, confidence=0.3, anchor_route_remaining_m=1.0)
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is stop.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "low_relocalization_confidence")

    def test_does_not_suppress_when_confidence_above_stop_veto_bar(self):
        # confidence clears the (lower) stop-veto bar -- this path shouldn't
        # engage at all; falls through to the normal (also-failing, since
        # confidence is still below the 0.90 direction-override bar) gate.
        arbiter = _arbiter(stop_veto_enabled=True)
        progress = _Progress(bearing=10.0, distance=5.0, confidence=0.7, anchor_route_remaining_m=10.0)
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is stop.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "low_relocalization_confidence")

    def test_does_not_affect_non_stop_actions(self):
        # a non-stop VLM output must go through the ordinary direction-override
        # path untouched (still gated at 0.90, unaffected by stop_veto).
        arbiter = _arbiter(stop_veto_enabled=True)
        progress = _Progress(bearing=90.0, distance=5.0, confidence=0.3, anchor_route_remaining_m=10.0)
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is move forward 75 cm.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "low_relocalization_confidence")

    def test_missing_anchor_route_remaining_does_not_suppress(self):
        arbiter = _arbiter(stop_veto_enabled=True)
        progress = _Progress(bearing=10.0, distance=5.0, confidence=0.3, anchor_route_remaining_m=None)
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is stop.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "low_relocalization_confidence")

    def test_high_confidence_stop_unaffected_by_stop_veto_flag(self):
        # confidence clears the normal 0.90 bar entirely -- ordinary
        # (pre-existing) high-confidence stop-override machinery decides this,
        # not the new low-confidence-specific path. Just confirm stop_veto
        # being on doesn't crash or short-circuit that pre-existing behavior.
        arbiter = _arbiter(stop_veto_enabled=True)
        progress = _Progress(
            bearing=10.0, distance=5.0, confidence=0.95, anchor_route_remaining_m=10.0,
            anchor_dx_m=1.0, anchor_dy_m=0.0,
        )
        decision = arbiter.check(
            progress=progress, vlm_output="The next action is stop.",
            robot_position=[0.0, 0.0, 0.0], robot_yaw_rad=0.0,
        )
        # No local/topdown map supplied -> clear_path unavailable -> falls
        # through to the pre-existing "clear_path_unavailable" no-override
        # branch, exactly as it would without stop_veto at all.
        self.assertFalse(decision.override)
        self.assertEqual(decision.reason, "clear_path_unavailable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
