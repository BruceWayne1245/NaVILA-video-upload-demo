import math
import unittest

from stop_gate import GateDecision, ReturnStopGate


# ---------------------------------------------------------------------------
# Minimal stub for RelativeStartProgress
# ---------------------------------------------------------------------------

class _Progress:
    """Duck-typed stub matching the fields ReturnStopGate reads."""

    def __init__(
        self,
        d: float,
        conf: float = None,
        std: float = None,
        bearing: float = 0.0,
        source: str = "arc_length_particle_filter",
        anchor_route_remaining_m: float = None,
    ):
        self.distance_to_start_m = d
        self.relocalization_confidence = conf
        self.filter_std_m = std
        self.bearing_to_start_deg = bearing
        self.source = source
        self.anchor_route_remaining_m = anchor_route_remaining_m


def _oracle(d, bearing=0.0):
    return _Progress(d, conf=1.0, source="direct_oracle_start", bearing=bearing)


def _low_conf(d, bearing=0.0, anchor_route_remaining_m=None):
    return _Progress(
        d, conf=0.1, source="arc_length_particle_filter", bearing=bearing,
        anchor_route_remaining_m=anchor_route_remaining_m,
    )


def _high_conf(d, bearing=0.0):
    return _Progress(d, conf=0.9, source="arc_length_particle_filter", bearing=bearing)


# ---------------------------------------------------------------------------
# Branch 1 — High confidence, d > r_out: VETO + inject forward command
# ---------------------------------------------------------------------------

class TestVeto(unittest.TestCase):

    def _gate(self):
        return ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)

    def test_veto_decision_when_far(self):
        gate = self._gate()
        dec = gate.check(_oracle(5.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")

    def test_veto_injects_nonzero_command(self):
        gate = self._gate()
        dec = gate.check(_oracle(5.0, bearing=0.0), vlm_issued_stop=True)
        self.assertIsNotNone(dec.suggested_command)
        total = sum(abs(c) for c in dec.suggested_command)
        self.assertGreater(total, 0.0, "vetoed command must be non-zero so robot keeps moving")

    def test_veto_positive_bearing_gives_positive_vyaw(self):
        gate = self._gate()
        # bearing = 45° to the left → turn left → vyaw > 0
        dec = gate.check(_oracle(5.0, bearing=45.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")
        self.assertGreater(dec.suggested_command[2], 0.0)

    def test_veto_negative_bearing_gives_negative_vyaw(self):
        gate = self._gate()
        dec = gate.check(_oracle(5.0, bearing=-45.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")
        self.assertLess(dec.suggested_command[2], 0.0)

    def test_veto_suggested_steps_positive(self):
        gate = self._gate()
        dec = gate.check(_oracle(4.0), vlm_issued_stop=True)
        self.assertGreater(dec.suggested_steps, 0)

    def test_veto_just_above_r_out(self):
        gate = self._gate()
        dec = gate.check(_oracle(3.01), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")


# ---------------------------------------------------------------------------
# Branch 2 — High confidence, d ≤ r_in: ACCEPT
# ---------------------------------------------------------------------------

class TestAccept(unittest.TestCase):

    def _gate(self):
        return ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)

    def test_accept_well_inside_r_in(self):
        gate = self._gate()
        dec = gate.check(_oracle(1.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")

    def test_accept_exactly_at_r_in(self):
        gate = self._gate()
        dec = gate.check(_oracle(2.5), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")

    def test_accept_records_authority_distance(self):
        gate = self._gate()
        dec = gate.check(_oracle(1.234), vlm_issued_stop=True)
        self.assertAlmostEqual(dec.authority_d, 1.234, places=4)


# ---------------------------------------------------------------------------
# Branch 3 — Low confidence: DEFERRED (don't exercise veto authority)
# ---------------------------------------------------------------------------

class TestDeferred(unittest.TestCase):

    def _gate(self):
        return ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)

    def test_deferred_low_conf_far(self):
        gate = self._gate()
        dec = gate.check(_low_conf(8.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_deferred_low_conf_near(self):
        gate = self._gate()
        dec = gate.check(_low_conf(0.5), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_deferred_hysteresis_zone(self):
        gate = self._gate()
        # r_in < 2.8 ≤ r_out → hysteresis zone
        dec = gate.check(_oracle(2.8), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_deferred_just_outside_r_in(self):
        gate = self._gate()
        dec = gate.check(_oracle(2.51), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")


# ---------------------------------------------------------------------------
# Branch 4 — Forced stop: VLM never stops but confirm_steps reached
# ---------------------------------------------------------------------------

class TestForcedStop(unittest.TestCase):

    def _gate(self, confirm_steps=3):
        return ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=confirm_steps,
                              min_confidence=0.5)

    def test_forced_after_confirm_steps(self):
        gate = self._gate(confirm_steps=3)
        p = _oracle(1.5)
        gate.check(p, vlm_issued_stop=False)
        gate.check(p, vlm_issued_stop=False)
        dec = gate.check(p, vlm_issued_stop=False)
        self.assertEqual(dec.decision, "forced")

    def test_not_forced_before_confirm_steps(self):
        gate = self._gate(confirm_steps=3)
        p = _oracle(1.5)
        gate.check(p, vlm_issued_stop=False)
        dec = gate.check(p, vlm_issued_stop=False)
        self.assertNotEqual(dec.decision, "forced")

    def test_confirm_counter_resets_when_robot_moves_away(self):
        gate = self._gate(confirm_steps=3)
        p_near = _oracle(1.0)
        p_far = _oracle(5.0)
        gate.check(p_near, vlm_issued_stop=False)
        gate.check(p_near, vlm_issued_stop=False)
        gate.check(p_far, vlm_issued_stop=False)    # resets counter
        dec = gate.check(p_near, vlm_issued_stop=False)   # only 1 step
        self.assertNotEqual(dec.decision, "forced")

    def test_confirm_counter_resets_on_low_conf(self):
        gate = self._gate(confirm_steps=3)
        p_near_hi = _oracle(1.0)
        p_near_lo = _low_conf(1.0)
        gate.check(p_near_hi, vlm_issued_stop=False)
        gate.check(p_near_hi, vlm_issued_stop=False)
        gate.check(p_near_lo, vlm_issued_stop=False)   # low conf resets
        dec = gate.check(p_near_hi, vlm_issued_stop=False)
        self.assertNotEqual(dec.decision, "forced")

    def test_accept_takes_priority_over_forced_counter(self):
        gate = self._gate(confirm_steps=3)
        p = _oracle(1.0)
        gate.check(p, vlm_issued_stop=False)
        gate.check(p, vlm_issued_stop=False)
        gate.check(p, vlm_issued_stop=False)
        # VLM stops too — accepted (not forced, accept semantics identical outcome)
        dec = gate.check(p, vlm_issued_stop=True)
        self.assertIn(dec.decision, ("accepted", "forced"))


# ---------------------------------------------------------------------------
# Teleport frame filter
# ---------------------------------------------------------------------------

class TestTeleportFilter(unittest.TestCase):

    def test_teleport_step_returns_pass(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        gate.notify_sim_step([0.0, 0.0, 0.0])
        gate.notify_sim_step([10.0, 0.0, 0.0])   # 10 m jump
        dec = gate.check(_oracle(0.5), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "pass")
        self.assertTrue(dec.is_teleport_frame)

    def test_teleport_resets_confirm_counter(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        p = _oracle(1.0)
        gate.check(p, vlm_issued_stop=False)
        gate.check(p, vlm_issued_stop=False)
        # Teleport
        gate.notify_sim_step([0.0, 0.0, 0.0])
        gate.notify_sim_step([10.0, 0.0, 0.0])
        gate.check(p, vlm_issued_stop=False)   # teleport → pass, counter reset
        gate.check(p, vlm_issued_stop=False)   # 1 step since reset
        dec = gate.check(p, vlm_issued_stop=False)   # 2 steps — not forced
        self.assertNotEqual(dec.decision, "forced")

    def test_no_teleport_on_small_jump(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        gate.notify_sim_step([0.0, 0.0, 0.0])
        gate.notify_sim_step([0.3, 0.0, 0.0])   # 0.3 m — normal motion
        dec = gate.check(_oracle(5.0), vlm_issued_stop=True)
        self.assertFalse(dec.is_teleport_frame)
        self.assertEqual(dec.decision, "vetoed")

    def test_flag_clears_after_first_check(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        gate.notify_sim_step([0.0, 0.0, 0.0])
        gate.notify_sim_step([10.0, 0.0, 0.0])
        gate.check(_oracle(0.5), vlm_issued_stop=True)   # consumes teleport flag
        dec = gate.check(_oracle(0.5), vlm_issued_stop=True)
        self.assertFalse(dec.is_teleport_frame)


# ---------------------------------------------------------------------------
# Hysteresis — no oscillation around boundary
# ---------------------------------------------------------------------------

class TestHysteresis(unittest.TestCase):

    def test_veto_only_strictly_above_r_out(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        # 3.0 m = r_out exactly → NOT vetoed (hysteresis zone)
        dec = gate.check(_oracle(3.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_veto_one_cm_above_r_out(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        dec = gate.check(_oracle(3.01), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")

    def test_accept_at_r_in(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        dec = gate.check(_oracle(2.5), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")

    def test_deferred_one_cm_above_r_in(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        dec = gate.check(_oracle(2.51), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_pass_when_no_progress(self):
        gate = ReturnStopGate()
        dec = gate.check(None, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "pass")
        self.assertIsNone(dec.authority_d)

    def test_pass_when_no_stop_no_progress(self):
        gate = ReturnStopGate()
        dec = gate.check(None, vlm_issued_stop=False)
        self.assertEqual(dec.decision, "pass")

    def test_log_dict_keys(self):
        gate = ReturnStopGate()
        dec = gate.check(_oracle(5.0), vlm_issued_stop=True)
        d = dec.as_log_dict()
        self.assertIn("gate_decision", d)
        self.assertIn("gate_authority_d", d)
        self.assertIn("gate_conf", d)
        self.assertIn("gate_teleport_filtered", d)

    def test_r_in_equals_r_out(self):
        gate = ReturnStopGate(r_in=2.5, r_out=2.5)
        dec = gate.check(_oracle(2.5), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")

    def test_confidence_from_filter_std(self):
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, min_confidence=0.5)
        # std = 1.0 → conf = 1 - 1/5 = 0.8 (≥ 0.5) → high conf
        p = _Progress(1.0, conf=None, std=1.0, source="arc_length_particle_filter")
        dec = gate.check(p, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")
        # std = 4.0 → conf = 1 - 4/5 = 0.2 (< 0.5) → low conf
        p_lo = _Progress(1.0, conf=None, std=4.0, source="arc_length_particle_filter")
        dec_lo = gate.check(p_lo, vlm_issued_stop=True)
        self.assertEqual(dec_lo.decision, "deferred")


# ---------------------------------------------------------------------------
# Anchor corroboration (2026-07-19, opt-in) — see stop_gate.py's module
# docstring. Confirmed against 4 real canonical_report_next_50ep_20260719
# episodes (ep187, ep498, ep589, ep678): anchor_route_remaining_m ranged
# 3.0-12.1m at the exact moment a premature stop was accepted at low
# confidence.
# ---------------------------------------------------------------------------

class TestAnchorCorroborationVeto(unittest.TestCase):

    def _gate(self, enabled=True):
        return ReturnStopGate(
            r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5,
            anchor_corroboration_enabled=enabled,
        )

    def test_off_by_default_stays_deferred(self):
        # Default constructor (anchor_corroboration_enabled=False) must not
        # change any existing behavior.
        gate = ReturnStopGate(r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5)
        dec = gate.check(_low_conf(13.4, anchor_route_remaining_m=11.09), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_disabled_flag_stays_deferred_even_with_far_anchor(self):
        gate = self._gate(enabled=False)
        dec = gate.check(_low_conf(13.4, anchor_route_remaining_m=11.09), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_vetoes_when_anchor_and_reading_both_far_ep187_like(self):
        gate = self._gate(enabled=True)
        dec = gate.check(_low_conf(13.4, anchor_route_remaining_m=11.09), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")
        self.assertIsNotNone(dec.suggested_command)

    def test_vetoes_borderline_anchor_ep498_like(self):
        # anchor_route_remaining_m just above r_in, combined reading well
        # past r_out -- the exact ep498 shape (anchor=3.01, d=4.79 in the
        # live r_in=r_out=3.0 config; scaled here to this file's r_in=2.5).
        gate = self._gate(enabled=True)
        dec = gate.check(_low_conf(4.79, anchor_route_remaining_m=2.51), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")

    def test_no_veto_when_anchor_says_close_contradicts_reading(self):
        # Anchor itself is a "close" one but this attempt's reading claims
        # far -- contradiction, not corroboration. Must not guess; stay
        # deferred.
        gate = self._gate(enabled=True)
        dec = gate.check(_low_conf(5.0, anchor_route_remaining_m=1.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_no_veto_when_reading_not_past_r_out(self):
        gate = self._gate(enabled=True)
        dec = gate.check(_low_conf(2.8, anchor_route_remaining_m=11.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_no_veto_when_anchor_missing(self):
        gate = self._gate(enabled=True)
        dec = gate.check(_low_conf(13.4, anchor_route_remaining_m=None), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_high_confidence_path_unaffected(self):
        # High-confidence veto must go through the pre-existing branch
        # regardless of anchor corroboration being enabled.
        gate = self._gate(enabled=True)
        dec = gate.check(_oracle(5.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")


class TestAnchorCorroborationForcedStop(unittest.TestCase):

    def _gate(self, enabled=True, anchor_confirm_steps=2):
        return ReturnStopGate(
            r_in=2.5, r_out=3.0, confirm_steps=3, min_confidence=0.5,
            anchor_corroboration_enabled=enabled,
            forced_stop_anchor_confirm_steps=anchor_confirm_steps,
        )

    def test_forced_after_anchor_streak(self):
        gate = self._gate(enabled=True, anchor_confirm_steps=2)
        p = _low_conf(1.0, anchor_route_remaining_m=1.0)
        gate.check(p, vlm_issued_stop=False)
        dec = gate.check(p, vlm_issued_stop=False)
        self.assertEqual(dec.decision, "forced")

    def test_not_forced_before_anchor_streak_reached(self):
        gate = self._gate(enabled=True, anchor_confirm_steps=2)
        p = _low_conf(1.0, anchor_route_remaining_m=1.0)
        dec = gate.check(p, vlm_issued_stop=False)
        self.assertNotEqual(dec.decision, "forced")

    def test_disabled_flag_never_forces_from_anchor_streak(self):
        gate = self._gate(enabled=False, anchor_confirm_steps=2)
        p = _low_conf(1.0, anchor_route_remaining_m=1.0)
        gate.check(p, vlm_issued_stop=False)
        gate.check(p, vlm_issued_stop=False)
        dec = gate.check(p, vlm_issued_stop=False)
        self.assertNotEqual(dec.decision, "forced")

    def test_streak_resets_on_anchor_reading_disagreement_ep319_like(self):
        # Guards the exact risk flagged for ep319 in
        # [[project_navila_isaac]]: a "close" anchor identity surviving
        # after the robot has since drifted away from it. One attempt where
        # the anchor and the current reading disagree must reset the streak.
        gate = self._gate(enabled=True, anchor_confirm_steps=2)
        close = _low_conf(1.0, anchor_route_remaining_m=1.0)
        drifted = _low_conf(5.0, anchor_route_remaining_m=1.0)  # anchor stale, reading disagrees
        gate.check(close, vlm_issued_stop=False)
        gate.check(drifted, vlm_issued_stop=False)   # resets streak
        dec = gate.check(close, vlm_issued_stop=False)   # only 1 step since reset
        self.assertNotEqual(dec.decision, "forced")

    def test_streak_resets_when_anchor_itself_not_close(self):
        gate = self._gate(enabled=True, anchor_confirm_steps=2)
        close = _low_conf(1.0, anchor_route_remaining_m=1.0)
        far_anchor = _low_conf(1.0, anchor_route_remaining_m=8.0)
        gate.check(close, vlm_issued_stop=False)
        gate.check(far_anchor, vlm_issued_stop=False)   # resets streak
        dec = gate.check(close, vlm_issued_stop=False)
        self.assertNotEqual(dec.decision, "forced")

    def test_teleport_resets_anchor_streak(self):
        gate = self._gate(enabled=True, anchor_confirm_steps=2)
        p = _low_conf(1.0, anchor_route_remaining_m=1.0)
        gate.check(p, vlm_issued_stop=False)
        gate.notify_sim_step([0.0, 0.0, 0.0])
        gate.notify_sim_step([10.0, 0.0, 0.0])   # teleport
        gate.check(p, vlm_issued_stop=False)     # teleport frame -> pass, streak reset
        dec = gate.check(p, vlm_issued_stop=False)   # only 1 step since reset
        self.assertNotEqual(dec.decision, "forced")

    def test_existing_high_confidence_forced_path_unaffected(self):
        gate = self._gate(enabled=True, anchor_confirm_steps=2)
        p = _oracle(1.5)
        gate.check(p, vlm_issued_stop=False)
        gate.check(p, vlm_issued_stop=False)
        dec = gate.check(p, vlm_issued_stop=False)
        self.assertEqual(dec.decision, "forced")


if __name__ == "__main__":
    unittest.main()
