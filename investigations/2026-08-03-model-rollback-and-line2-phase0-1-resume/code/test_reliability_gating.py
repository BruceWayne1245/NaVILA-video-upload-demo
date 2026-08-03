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


class EvictUnreliableCurrentTest(unittest.TestCase):
    """2026-08-03 (line-2 Phase 0.2, mechanism B parts (ii)/(iii) --
    investigations/2026-07-28-downgrade-batch-mechanism-failure-classification/
    MODIFICATION_PLAN.md, planned as Injection B (ii)/(iii) on 2026-07-21,
    never implemented until now).

    All promotion-path scenarios below deliberately keep `next` FAR
    (dy=3.0, >> promotion_close_radius_m=0.75) with a CONSTANT distance
    every attempt (so _promotion_trend_improving never reports improving
    either) -- this makes candidate_promote False via the ordinary
    close_enough/trend_ok gate regardless of quality_ok's own
    current_unreliable bypass (already-shipped Injection B behaviour,
    covered by DemoteCurrentTest above), isolating eviction as the ONLY
    mechanism that can move _target_anchor_index in these tests.
    """

    def _agent(self, stall=5, **kw):
        a = _pair_agent(
            sequential_pair_reliability_demote_current=True,
            sequential_pair_evict_unreliable_current=True,
            current_evict_stall_attempts=stall,
            **kw,
        )
        a._target_anchor_index = 2  # current; next == 1
        return a

    # --- part (ii): eviction itself ---

    def test_evicts_to_next_after_stall_streak(self):
        agent = self._agent(stall=5)
        agent._current_reliability_history[2] = [6.0] * 6  # current already persistently unreliable
        for _ in range(4):  # attempts 1-4: streak building, not evicted yet
            agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
            self.assertEqual(agent._target_anchor_index, 2)
        # 5th consecutive attempt: streak reaches current_evict_stall_attempts -> evict
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 1, "should have force-advanced to next")

    def test_does_not_evict_before_stall_reached(self):
        agent = self._agent(stall=30)
        agent._current_reliability_history[2] = [6.0] * 6
        for _ in range(10):
            agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2)

    def test_off_by_default_never_evicts(self):
        agent = _pair_agent(sequential_pair_reliability_demote_current=True)  # evict flag off
        agent._target_anchor_index = 2
        agent._current_reliability_history[2] = [6.0] * 6
        for _ in range(60):
            agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2)

    def test_does_not_evict_to_a_next_that_is_worse_than_current(self):
        # current is moderately unreliable (per the forced history below), but
        # next's OWN this-attempt reading is even worse -- don't jump to it.
        agent = self._agent(stall=1)
        agent._current_reliability_history[2] = [6.0] * 6
        moderate_current = reading(2, conf=0.5, inlier=200, b2s=0.7, nt=1)
        worse_next = reading(1, dy=3.0, conf=0.2, inlier=50, b2s=0.99, nt=5)
        agent._select_sequential_pair_relocalization([moderate_current, worse_next])
        self.assertEqual(agent._target_anchor_index, 2, "must not evict into a worse next")

    def test_streak_resets_when_current_becomes_reliable(self):
        agent = self._agent(stall=3)
        agent._current_reliability_history[2] = [6.0] * 6
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._current_evict_streak_count, 2)
        # current reads clean this attempt -> _current_persistently_unreliable
        # recomputes off the (now-appended) history and the streak resets.
        agent._current_reliability_history[2] = [1.0] * 10
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._current_evict_streak_count, 0)

    def test_streak_resets_after_promotion_escapes_naturally(self):
        # a normal (non-eviction) promotion already changes current_idx, so the
        # streak for the OLD current_idx should not silently keep counting
        # against the new one.
        agent = self._agent(stall=100)
        agent._current_reliability_history[2] = [6.0] * 6
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._current_evict_streak_anchor, 2)
        agent._target_anchor_index = 1  # simulate an unrelated promotion happening
        agent._select_sequential_pair_relocalization([good_reading(1, dy=3.0), good_reading(0, dy=3.0)])
        # anchor1 has no reliability history of its own -> not persistently
        # unreliable -> streak resets rather than silently carrying anchor2's count.
        self.assertIsNone(agent._current_evict_streak_anchor)
        self.assertEqual(agent._current_evict_streak_count, 0)

    # --- part (iii): trend-quarantine bypass ---

    def test_trend_quarantine_skipped_when_current_unreliable(self):
        agent = self._agent(stall=100)  # high stall so eviction itself never fires here
        agent._current_reliability_history[2] = [6.0] * 6
        for _ in range(8):
            agent._record_next_anchor_trend([
                bad_reading(2, dx=-0.02, dy=0.0),
                bad_reading(1, dx=-0.02, dy=3.0),
            ])
        self.assertNotIn(1, agent._quarantined_anchor_indices,
                          "must not quarantine next off a disagreement with an unreliable current")

    def test_trend_quarantine_still_fires_when_current_reliable(self):
        agent = self._agent(stall=100)
        # current is clean -- no bypass; ep-independent disagreement should quarantine as before.
        for _ in range(8):
            agent._record_next_anchor_trend([
                good_reading(2, dx=-0.02, dy=0.0),
                bad_reading(1, dx=-0.02, dy=3.0),
            ])
        self.assertIn(1, agent._quarantined_anchor_indices)

    def test_trend_bypass_off_by_default_even_with_demote_current_on(self):
        # demote_current alone (without evict_unreliable_current) must not
        # change _record_next_anchor_trend's behaviour -- byte-identical to
        # before this session.
        agent = _pair_agent(sequential_pair_reliability_demote_current=True)
        agent._target_anchor_index = 2
        agent._current_reliability_history[2] = [6.0] * 6
        for _ in range(8):
            agent._record_next_anchor_trend([
                bad_reading(2, dx=-0.02, dy=0.0),
                bad_reading(1, dx=-0.02, dy=3.0),
            ])
        self.assertIn(1, agent._quarantined_anchor_indices,
                       "demote_current alone must not gain the trend bypass")


class PromotionAmbiguityGateTest(unittest.TestCase):
    """2026-08-03 (line-2 Phase 1.1, mechanism A -- investigations/2026-07-28-
    downgrade-batch-mechanism-failure-classification/MODIFICATION_PLAN.md).
    All scenarios omit a `current` reading entirely (gate_current_est=None),
    so quality_ok is True via its own `gate_current_est is None` branch and
    close_enough is True via a small dy -- isolating the new ambiguity/
    min-confidence gate as the only thing that can still veto candidate_promote.
    """

    def _agent(self, **kw):
        a = _pair_agent(
            sequential_pair_promotion_ambiguity_gate=True,
            current_confidence_ambiguity_gate_threshold=0.75,
            sequential_pair_promotion_min_confidence=0.35,
            **kw,
        )
        a._target_anchor_index = 2  # current has no estimate this attempt; next == 1
        return a

    def test_ambiguous_ratio_blocks_promotion(self):
        agent = self._agent()
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.98, nt=0)  # ambiguous (near-tied) but confident
        _, _, reason = agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 2, "ambiguous ratio must not promote")

    def test_low_confidence_blocks_promotion(self):
        agent = self._agent()
        next_est = reading(1, conf=0.2, inlier=400, b2s=0.3, nt=0)  # decisive ratio but low absolute confidence
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 2, "low absolute confidence must not promote")

    def test_clean_confident_reading_still_promotes(self):
        agent = self._agent()
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)  # neither ambiguous nor low-confidence
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 1, "a clean, confident reading must still promote")

    def test_off_by_default_promotes_despite_ambiguity(self):
        agent = _pair_agent()  # gate off
        agent._target_anchor_index = 2
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.98, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 1, "gate off -> byte-identical prior behaviour")


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


class SharedTrendBudgetTest(unittest.TestCase):
    """2026-07-22 trend-cascade fix: the position-trend quarantine draws from the
    same anti-cascade budget as Injection A when the flag is on, so A + trend
    together cannot blacklist more than reliability_quarantine_max_chain anchors
    between two promotions (trend previously had no cap of its own and could seal
    a pin by quarantining an entire self-similar downstream, e.g. ep134)."""

    def _agent(self, **kw):
        a = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0,
            sequential_pair_quarantine_enabled=True,
            sequential_pair_quarantine_mode="trend",
            **kw,
        )
        for _ in range(4):
            a.update_outbound_motion([1.0, 0.0, 0.0])
        a.finalize_outbound()   # anchors 0..4, return start current=4
        a._target_anchor_index = 4
        return a

    def _drive_trend_ban(self, agent, next_idx, n=8):
        # current (anchor4) reads clean; next reads a large, non-shrinking lateral
        # disagreement -> trend quarantines it.
        for _ in range(n):
            agent._record_next_anchor_trend([
                good_reading(4, dx=-0.02, dy=0.0),
                bad_reading(next_idx, dx=-0.02, dy=3.0),
            ])

    def test_uncapped_trend_bans_a_whole_chain(self):
        # baseline (shared-budget flag off): trend bans every disagreeing next,
        # unbounded -- reproduces the cascade the fix targets.
        agent = self._agent()
        self._drive_trend_ban(agent, 3)
        self._drive_trend_ban(agent, 2)
        self.assertEqual({2, 3}, agent._quarantined_anchor_indices & {2, 3})
        self.assertEqual(agent._reliability_quarantines_since_promotion, 0)  # trend never touched the counter

    def test_shared_budget_caps_trend_at_max_chain(self):
        agent = self._agent(
            sequential_pair_reliability_quarantine_enabled=True,
            reliability_quarantine_shared_trend_budget=True,
            reliability_quarantine_max_chain=1,
        )
        self._drive_trend_ban(agent, 3)
        self._drive_trend_ban(agent, 2)
        # only the first ban fits in the budget of 1; the second is refused.
        self.assertIn(3, agent._quarantined_anchor_indices)
        self.assertNotIn(2, agent._quarantined_anchor_indices)
        self.assertEqual(agent._reliability_quarantines_since_promotion, 1)

    def test_shared_budget_off_by_default_even_with_reliability_on(self):
        # reliability quarantine enabled but the shared-trend-budget flag off:
        # trend stays uncapped (byte-identical to prior behaviour).
        agent = self._agent(
            sequential_pair_reliability_quarantine_enabled=True,
            reliability_quarantine_max_chain=1,
        )
        self._drive_trend_ban(agent, 3)
        self._drive_trend_ban(agent, 2)
        self.assertEqual({2, 3}, agent._quarantined_anchor_indices & {2, 3})

    def test_shared_budget_noop_when_reliability_quarantine_disabled(self):
        # shared flag on but reliability machinery off -> gate is inert, trend uncapped.
        agent = self._agent(
            reliability_quarantine_shared_trend_budget=True,
            reliability_quarantine_max_chain=1,
        )
        self._drive_trend_ban(agent, 3)
        self._drive_trend_ban(agent, 2)
        self.assertEqual({2, 3}, agent._quarantined_anchor_indices & {2, 3})


if __name__ == "__main__":
    unittest.main(verbosity=2)
