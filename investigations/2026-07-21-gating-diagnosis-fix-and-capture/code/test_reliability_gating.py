"""Unit tests for the 2026-07-21 reliability gating (Injection A/B/C).

Run from the candidate/ dir:  python3 -m unittest test_reliability_gating -v
Covers the absolute reliability quarantine of `next` (A), demote-bad-current
promotion relaxation (B), downstream confidence/stop-gate distrust (C), and the
off-by-default invariant for all three.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from route_memory_agent import AnchorRelocalization, RouteMemoryAgent  # noqa: E402
from stop_gate import ReturnStopGate  # noqa: E402


def reading(idx, *, dx=-0.05, dy=0.0, dtheta=0.0, conf, inlier, b2s, nt):
    """AnchorRelocalization with the four fields _reading_unreliability reads
    set explicitly, so U is fully controlled."""
    return AnchorRelocalization(
        anchor_index=idx, anchor_dx_m=dx, anchor_dy_m=dy, anchor_dtheta_rad=dtheta,
        confidence=conf, backend="sequential_pair", inlier_count=inlier,
        best_to_second_score_ratio=b2s, near_tie_basin_count=nt,
    )


# High U (degenerate): low inliers, high runner-up ratio, near-ties, low conf.
def bad_reading(idx, **kw):
    return reading(idx, conf=0.30, inlier=100, b2s=0.95, nt=3, **kw)


# Low U (clean): many inliers, decisive winner, no near-ties, high conf.
def good_reading(idx, **kw):
    return reading(idx, conf=1.00, inlier=450, b2s=0.35, nt=0, **kw)


# High U but high CONFIDENCE ("confidently wrong"): tests that the C cap keys
# off U, not the raw confidence value.
def confidently_wrong_reading(idx, **kw):
    return reading(idx, conf=0.90, inlier=100, b2s=0.95, nt=3, **kw)


def _pair_agent(**flags):
    agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, **flags)
    for _ in range(2):
        agent.update_outbound_motion([1.0, 0.0, 0.0])
    agent.finalize_outbound()   # anchors 0 @0m, 1 @1m, 2 @2m (return start)
    return agent


class ReadingUnreliabilityTest(unittest.TestCase):
    def test_bad_reading_scores_above_threshold_clean_below(self):
        agent = RouteMemoryAgent(enabled=True)
        u_bad = agent._reading_unreliability(bad_reading(1))
        u_good = agent._reading_unreliability(good_reading(1))
        self.assertGreater(u_bad, 2.5)
        self.assertLess(u_good, 2.5)
        self.assertGreater(u_bad, u_good)

    def test_missing_field_returns_none(self):
        agent = RouteMemoryAgent(enabled=True)
        est = AnchorRelocalization(anchor_index=1, anchor_dx_m=0.0, anchor_dy_m=0.0,
                                   anchor_dtheta_rad=0.0, confidence=0.5, backend="sequential_pair",
                                   inlier_count=None, best_to_second_score_ratio=None,
                                   near_tie_basin_count=None)
        self.assertIsNone(agent._reading_unreliability(est))


class ReliabilityQuarantineTest(unittest.TestCase):
    """Injection A."""

    def _agent(self, **kw):
        a = _pair_agent(sequential_pair_reliability_quarantine_enabled=True, **kw)
        a._target_anchor_index = 2  # current
        return a

    def test_persistently_bad_next_is_quarantined(self):
        agent = self._agent()
        for _ in range(6):  # == reliability_quarantine_min_history
            agent._record_next_anchor_reliability([bad_reading(1)])
        self.assertIn(1, agent._quarantined_anchor_indices)

    def test_clean_next_is_not_quarantined(self):
        agent = self._agent()
        for _ in range(20):
            agent._record_next_anchor_reliability([good_reading(1)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_off_by_default_never_quarantines(self):
        agent = _pair_agent()  # flag off
        agent._target_anchor_index = 2
        for _ in range(20):
            agent._record_next_anchor_reliability([bad_reading(1)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_current_is_never_quarantined_by_next_recorder(self):
        agent = self._agent()
        for _ in range(20):
            agent._record_next_anchor_reliability([bad_reading(2)])  # 2 == current
        self.assertNotIn(2, agent._quarantined_anchor_indices)

    def test_max_chain_caps_quarantines_without_promotion(self):
        agent = self._agent()
        agent._reliability_quarantines_since_promotion = agent.reliability_quarantine_max_chain
        for _ in range(6):
            agent._record_next_anchor_reliability([bad_reading(1)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)  # budget exhausted → no new ban

    def test_stall_attempts_caps_history_growth(self):
        agent = self._agent(reliability_quarantine_stall_attempts=3)
        for _ in range(10):
            agent._record_next_anchor_reliability([bad_reading(1)])
        self.assertLessEqual(len(agent._next_anchor_reliability_history.get(1, [])), 3)

    def test_next_candidate_index_skips_reliability_quarantined(self):
        agent = self._agent()
        agent._quarantined_anchor_indices.add(1)
        self.assertEqual(agent._next_candidate_index(2), 0)


class DemoteCurrentTest(unittest.TestCase):
    """Injection B."""

    def test_current_persistently_unreliable_true_when_bad(self):
        agent = _pair_agent(sequential_pair_reliability_demote_current=True)
        agent._target_anchor_index = 2
        for _ in range(6):
            agent._record_current_anchor_reliability([bad_reading(2)])
        self.assertTrue(agent._current_persistently_unreliable(2))

    def test_current_persistently_unreliable_false_when_clean(self):
        agent = _pair_agent(sequential_pair_reliability_demote_current=True)
        agent._target_anchor_index = 2
        for _ in range(10):
            agent._record_current_anchor_reliability([good_reading(2)])
        self.assertFalse(agent._current_persistently_unreliable(2))

    def test_off_by_default_returns_false_and_records_nothing(self):
        agent = _pair_agent()  # flag off
        agent._target_anchor_index = 2
        for _ in range(10):
            agent._record_current_anchor_reliability([bad_reading(2)])
        self.assertEqual(agent._current_reliability_history, {})
        self.assertFalse(agent._current_persistently_unreliable(2))

    def _mismatch_pair(self):
        # current @ anchor2 and next @ anchor1 both claim the robot sits ~5cm
        # from THEIR anchor -- impossible simultaneously (the anchors are ~1m
        # apart), so closure reprojection disagrees by ~1m; equal quality means
        # neither side dominates -> reject_reason="sequential_pair_closure_mismatch".
        current = reading(2, dx=-0.05, dy=0.0, conf=0.6, inlier=200, b2s=0.6, nt=0)
        nxt = reading(1, dx=-0.05, dy=0.0, conf=0.6, inlier=200, b2s=0.6, nt=0)
        return current, nxt

    def test_mismatch_blocks_promotion_when_current_reliable(self):
        agent = _pair_agent(
            sequential_pair_closure_check_enabled=True,
            sequential_pair_promotion_mode="immediate",
            sequential_pair_reliability_demote_current=True,
        )
        agent._target_anchor_index = 2
        current, nxt = self._mismatch_pair()
        # sanity: this really is a closure mismatch
        _, reason = agent._sequential_pair_closure_precheck([current, nxt])
        self.assertEqual(reason, "sequential_pair_closure_mismatch")
        agent.update_relocalization(relocalization=[current, nxt])
        self.assertEqual(agent._target_anchor_index, 2, "reliable-current mismatch must veto promotion")

    def test_mismatch_allows_promotion_when_current_unreliable(self):
        agent = _pair_agent(
            sequential_pair_closure_check_enabled=True,
            sequential_pair_promotion_mode="immediate",
            sequential_pair_reliability_demote_current=True,
        )
        agent._target_anchor_index = 2
        # mark current (anchor 2) persistently unreliable
        agent._current_reliability_history[2] = [6.0] * 6
        self.assertTrue(agent._current_persistently_unreliable(2))
        current, nxt = self._mismatch_pair()
        agent.update_relocalization(relocalization=[current, nxt])
        self.assertEqual(agent._target_anchor_index, 1,
                         "unreliable-current must not veto a promotable next")


class DistrustDownstreamTest(unittest.TestCase):
    """Injection C -- route_memory side."""

    def test_reported_confidence_capped_on_low_reliability(self):
        agent = _pair_agent(sequential_pair_reliability_distrust_downstream=True)
        capped = agent._current_reported_confidence(confidently_wrong_reading(1))
        self.assertLessEqual(capped, agent.reliability_low_confidence_floor)

    def test_reported_confidence_unchanged_for_clean_reading(self):
        agent = _pair_agent(sequential_pair_reliability_distrust_downstream=True)
        est = good_reading(1)
        self.assertAlmostEqual(agent._current_reported_confidence(est), float(est.confidence))

    def test_off_by_default_does_not_cap(self):
        agent = _pair_agent()  # flag off
        est = confidently_wrong_reading(1)
        self.assertAlmostEqual(agent._current_reported_confidence(est), float(est.confidence))

    def test_anchor_progress_flags_low_reliability(self):
        agent = _pair_agent(sequential_pair_reliability_distrust_downstream=True)
        prog_bad = agent._anchor_progress_from_estimate(bad_reading(1))
        prog_good = agent._anchor_progress_from_estimate(good_reading(1))
        self.assertTrue(prog_bad.distance_authority_low_reliability)
        self.assertFalse(prog_good.distance_authority_low_reliability)

    def test_anchor_progress_flag_none_when_off(self):
        agent = _pair_agent()  # flag off
        prog = agent._anchor_progress_from_estimate(bad_reading(1))
        self.assertIsNone(prog.distance_authority_low_reliability)


class _Progress:
    """Duck-typed stop_gate progress stub with the Injection-C field."""
    def __init__(self, d, conf, bearing=0.0, anchor_route_remaining_m=None,
                 low_reliability=None):
        self.distance_to_start_m = d
        self.relocalization_confidence = conf
        self.filter_std_m = None
        self.bearing_to_start_deg = bearing
        self.source = "sequential_pair"
        self.anchor_route_remaining_m = anchor_route_remaining_m
        self.distance_authority_low_reliability = low_reliability


class StopGateLowReliabilityTest(unittest.TestCase):
    """Injection C -- stop_gate side."""

    def _gate(self):
        return ReturnStopGate(r_in=3.0, r_out=3.0, confirm_steps=3, min_confidence=0.5)

    def test_vetoes_far_high_conf_stop_normally(self):
        gate = self._gate()
        dec = gate.check(_Progress(8.0, conf=0.9), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")

    def test_defers_far_high_conf_stop_when_low_reliability(self):
        gate = self._gate()
        dec = gate.check(_Progress(8.0, conf=0.9, low_reliability=True), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_flag_absent_progress_still_vetoes(self):
        # a progress object without the field at all (getattr default False)
        class _Bare:
            distance_to_start_m = 8.0
            relocalization_confidence = 0.9
            filter_std_m = None
            bearing_to_start_deg = 0.0
            source = "sequential_pair"
            anchor_route_remaining_m = None
        dec = self._gate().check(_Bare(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
