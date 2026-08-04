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


class EvictUnreliableCurrentWindowModeTest(unittest.TestCase):
    """2026-08-04 follow-up: current_evict_mode="window" replaces the hard
    consecutive streak with a bounded-window vote (mirrors
    sequential_pair_promotion_window/_min_votes's own established pattern).
    Motivated by a real 30ep batch (line2_phase01_30ep_20260803, ep678) where
    evict_streak reached 19/30 then reset to 0 on a single reliable-looking
    reading, so eviction never fired despite current staying persistently
    unreliable (high confidence, "confidently wrong") for the whole
    surrounding window -- see investigations/2026-08-03-model-rollback-and-
    line2-phase0-1-resume/FINDINGS.md sec.12's open concern.
    """

    def _agent(self, window=5, min_votes=3, **kw):
        a = _pair_agent(
            sequential_pair_reliability_demote_current=True,
            sequential_pair_evict_unreliable_current=True,
            current_evict_mode="window",
            current_evict_window=window,
            current_evict_min_votes=min_votes,
            **kw,
        )
        a._target_anchor_index = 2  # current; next == 1
        return a

    def test_evicts_once_min_votes_reached_within_window(self):
        agent = self._agent(window=5, min_votes=3)
        agent._current_reliability_history[2] = [6.0] * 6  # current already persistently unreliable
        for _ in range(2):  # 2 bad votes: not enough yet
            agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
            self.assertEqual(agent._target_anchor_index, 2)
        # 3rd bad vote reaches min_votes -> evict
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 1, "should have force-advanced to next")

    def test_single_good_looking_blip_does_not_erase_prior_progress(self):
        # This is the whole point of window mode: a streak would reset to 0
        # here; a window only drops the vote once it ages out past window size.
        agent = self._agent(window=5, min_votes=3)
        agent._current_reliability_history[2] = [6.0] * 6
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2)
        # one attempt where current reads clean (current_unreliable flips False
        # for this single attempt only)
        agent._current_reliability_history[2] = [1.0] * 10
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2, "one blip alone must not evict")
        # back to unreliable -> this is the 3rd True vote within the window
        # (2 earlier + this one; the blip is a separate False vote, not a reset)
        agent._current_reliability_history[2] = [6.0] * 6
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 1,
                          "3 True votes within the window must evict even with a blip between them")

    def test_vote_ages_out_past_window_size(self):
        # window=3, min_votes=2: a bad vote old enough to have left the
        # 3-slot window must not still count toward min_votes.
        agent = self._agent(window=3, min_votes=2)
        # call 1: bad -> window=[T]
        agent._current_reliability_history[2] = [6.0] * 6
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2)
        # calls 2-3: good, good -> window=[T,F,F] (now full)
        agent._current_reliability_history[2] = [1.0] * 10
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2)
        # call 4: bad -> window would be [T,F,F,T] but trims to last 3 = [F,F,T]
        # -- call 1's bad vote just aged out, so only 1 True is visible, not 2
        agent._current_reliability_history[2] = [6.0] * 6
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2, "aged-out vote must not still count")
        # call 5: bad -> window=[F,T,T] -- 2 True now genuinely within the window -> evict
        agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 1, "2 votes genuinely within the window evicts")

    def test_does_not_evict_before_min_votes_reached(self):
        agent = self._agent(window=40, min_votes=30)
        agent._current_reliability_history[2] = [6.0] * 6
        for _ in range(10):
            agent._select_sequential_pair_relocalization([bad_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._target_anchor_index, 2)

    def test_off_by_default_mode_is_streak(self):
        agent = _pair_agent(
            sequential_pair_reliability_demote_current=True,
            sequential_pair_evict_unreliable_current=True,
        )
        self.assertEqual(agent.current_evict_mode, "streak")

    def test_does_not_evict_to_a_next_that_is_worse_than_current(self):
        agent = self._agent(window=1, min_votes=1)
        agent._current_reliability_history[2] = [6.0] * 6
        moderate_current = reading(2, conf=0.5, inlier=200, b2s=0.7, nt=1)
        worse_next = reading(1, dy=3.0, conf=0.2, inlier=50, b2s=0.99, nt=5)
        agent._select_sequential_pair_relocalization([moderate_current, worse_next])
        self.assertEqual(agent._target_anchor_index, 2, "must not evict into a worse next")


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

    def test_ambiguous_ratio_sets_observable_reason(self):
        # 2026-08-04: previously silent -- this is the whole fix (see the
        # gate's own firing-site comment). Confirms the flip is now visible
        # both on the agent (for a direct call) and inside
        # relocalization_events (what update_relocalization actually logs).
        agent = self._agent()
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.98, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._last_promotion_ambiguity_gate_reason, "ambiguous_ratio")
        agent.update_relocalization(relocalization=[reading(1, conf=0.9, inlier=400, b2s=0.98, nt=0)])
        self.assertEqual(
            agent.relocalization_events[-1]["promotion_ambiguity_gate_blocked"], "ambiguous_ratio"
        )

    def test_low_confidence_sets_observable_reason(self):
        agent = self._agent()
        next_est = reading(1, conf=0.2, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._last_promotion_ambiguity_gate_reason, "low_confidence")

    def test_clean_confident_reading_leaves_reason_none(self):
        agent = self._agent()
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertIsNone(agent._last_promotion_ambiguity_gate_reason)

    def test_reason_resets_between_attempts(self):
        # a blocked attempt must not leak its reason into a later, clean one.
        agent = self._agent()
        agent._select_sequential_pair_relocalization([reading(1, conf=0.9, inlier=400, b2s=0.98, nt=0)])
        self.assertIsNotNone(agent._last_promotion_ambiguity_gate_reason)
        agent._target_anchor_index = 2
        agent._select_sequential_pair_relocalization([reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)])
        self.assertIsNone(agent._last_promotion_ambiguity_gate_reason)

    def test_off_by_default_reason_always_none(self):
        agent = _pair_agent()  # gate off
        agent._target_anchor_index = 2
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.98, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertIsNone(agent._last_promotion_ambiguity_gate_reason)


class PromotionAnomalyGateTest(unittest.TestCase):
    """2026-08-04. The 07-23-proposed but never-built 'cheap, vision-free
    dynamic anomaly detection' (investigations/2026-07-23-confidently-wrong-
    convergence-and-vision-path/FINDINGS.md): flags a single-attempt bearing
    jump or implausible distance collapse against the SAME candidate anchor's
    own previous attempt, independent of ambiguity_gate (which only looks at
    this attempt's own ratio/confidence, not how it changed since last time).
    History is seeded directly on the agent (rather than built up across
    calls) to isolate the anomaly check's own logic from the surrounding
    promotion-vote machinery, same technique DemoteCurrentTest/EvictUnreliable
    CurrentTest already use for their own isolated preconditions.
    """

    def _agent(self, **kw):
        a = _pair_agent(
            sequential_pair_promotion_anomaly_gate=True,
            promotion_anomaly_max_bearing_jump_deg=90.0,
            promotion_anomaly_max_collapse_m=1.5,
            **kw,
        )
        a._target_anchor_index = 2  # current has no estimate this attempt; next == 1
        return a

    def test_bearing_jump_blocks_promotion(self):
        agent = self._agent()
        agent._next_candidate_anomaly_history[1] = (180.0, 5.0)
        # dx=+0.05 -> bearing~0deg, a 180deg jump from the stored 180.0
        next_est = reading(1, dx=0.05, dy=0.0, conf=0.9, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 2, "bearing jump must block promotion")
        self.assertEqual(agent._last_promotion_anomaly_reason, "bearing_jump")

    def test_distance_collapse_blocks_promotion(self):
        agent = self._agent()
        agent._next_candidate_anomaly_history[1] = (180.0, 5.0)
        # default dx=-0.05,dy=0 -> bearing~180deg (matches, no jump), distance
        # 0.05m -> a ~4.95m collapse from the stored 5.0m.
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 2, "implausible collapse must block promotion")
        self.assertEqual(agent._last_promotion_anomaly_reason, "distance_collapse")

    def test_normal_convergence_still_promotes(self):
        agent = self._agent()
        agent._next_candidate_anomaly_history[1] = (178.0, 0.1)  # small, plausible prior diff
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)  # bearing~180, dist=0.05
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 1, "plausible convergence must still promote")
        self.assertIsNone(agent._last_promotion_anomaly_reason)

    def test_no_history_never_blocks_first_attempt(self):
        agent = self._agent()
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 1, "no prior reading -> nothing to compare, must not block")

    def test_history_pruned_on_promotion(self):
        agent = self._agent()
        next_est = reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 1)
        self.assertNotIn(1, agent._next_candidate_anomaly_history)

    def test_off_by_default_never_blocks(self):
        agent = _pair_agent()  # gate off
        agent._target_anchor_index = 2
        agent._next_candidate_anomaly_history[1] = (180.0, 5.0)
        next_est = reading(1, dx=0.05, dy=0.0, conf=0.9, inlier=400, b2s=0.3, nt=0)
        agent._select_sequential_pair_relocalization([next_est])
        self.assertEqual(agent._target_anchor_index, 1, "gate off -> byte-identical prior behaviour")

    def test_reason_resets_between_attempts(self):
        agent = self._agent()
        agent._next_candidate_anomaly_history[1] = (180.0, 5.0)
        agent._select_sequential_pair_relocalization(
            [reading(1, dx=0.05, dy=0.0, conf=0.9, inlier=400, b2s=0.3, nt=0)]
        )
        self.assertIsNotNone(agent._last_promotion_anomaly_reason)
        agent._target_anchor_index = 2
        agent._next_candidate_anomaly_history[1] = (178.0, 0.1)
        agent._select_sequential_pair_relocalization(
            [reading(1, conf=0.9, inlier=400, b2s=0.3, nt=0)]
        )
        self.assertIsNone(agent._last_promotion_anomaly_reason)


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


class StaleRelocalizationDistrustTest(unittest.TestCase):
    """2026-08-04. Root cause of ep368's stop_gate freeze
    (line2_phase01_30ep_20260803): _latest_next_candidate_relocalization only
    refreshes on an attempt where next's own candidate is present, so once an
    anchor stops producing ANY candidate the reported reading silently reuses
    the last value forever -- confirmed via ground truth (distance_to_start_m
    converged 1.45m->0.26m while the reported anchor distance sat frozen at
    4.52m for 1500+ steps). This is a different failure signature from
    Injection C's _reading_unreliability (a fresh-but-bad reading): a stale
    cache can look perfectly confident, it just isn't being asked anymore.
    """

    def _agent(self, max_attempts=3, **kw):
        a = _pair_agent(
            sequential_pair_stale_relocalization_distrust=True,
            stale_relocalization_max_attempts=max_attempts,
            **kw,
        )
        a._target_anchor_index = 2  # current; next == 1
        return a

    def test_next_stale_attempts_increments_when_absent_resets_when_present(self):
        agent = self._agent()
        agent._select_sequential_pair_relocalization([good_reading(2)])  # next absent
        self.assertEqual(agent._next_stale_attempts, 1)
        agent._select_sequential_pair_relocalization([good_reading(2)])
        self.assertEqual(agent._next_stale_attempts, 2)
        agent._select_sequential_pair_relocalization([good_reading(2), good_reading(1, dy=3.0)])
        self.assertEqual(agent._next_stale_attempts, 0, "a fresh next candidate resets the counter")

    def test_current_stale_attempts_increments_when_absent(self):
        agent = self._agent()
        agent._select_sequential_pair_relocalization([good_reading(1, dy=3.0)])  # current absent
        self.assertEqual(agent._current_stale_attempts, 1)

    def test_reported_confidence_capped_once_threshold_reached(self):
        agent = self._agent(max_attempts=2)
        agent._select_sequential_pair_relocalization([good_reading(2)])
        agent._select_sequential_pair_relocalization([good_reading(2)])
        self.assertEqual(agent._next_stale_attempts, 2)
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertLessEqual(prog.relocalization_confidence, agent.reliability_low_confidence_floor)
        self.assertTrue(prog.distance_authority_low_reliability)
        self.assertEqual(prog.relocalization_stale_attempts, 2)

    def test_no_distrust_before_threshold_reached(self):
        agent = self._agent(max_attempts=5)
        agent._select_sequential_pair_relocalization([good_reading(2)])
        self.assertEqual(agent._next_stale_attempts, 1)
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertAlmostEqual(prog.relocalization_confidence, float(good_reading(1).confidence))
        self.assertFalse(prog.distance_authority_low_reliability)

    def test_off_by_default_never_distrusts_stale(self):
        agent = _pair_agent()  # flag off
        agent._target_anchor_index = 2
        for _ in range(50):
            agent._select_sequential_pair_relocalization([good_reading(2)])
        self.assertEqual(agent._next_stale_attempts, 50)
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertIsNone(prog.distance_authority_low_reliability)

    def test_current_role_uses_current_stale_counter_not_next(self):
        # Directly drive the two counters apart (rather than via
        # _select_sequential_pair_relocalization, where a single current-
        # absent attempt has the separate, real side effect of an immediate
        # single-attempt promotion -- see "Nothing to hold onto" in that
        # method) to isolate _anchor_progress_from_estimate's role-based
        # counter selection on its own.
        agent = self._agent(max_attempts=2)
        agent._current_stale_attempts = 2
        agent._next_stale_attempts = 0
        prog = agent._anchor_progress_from_estimate(good_reading(2), role="current")
        self.assertTrue(prog.distance_authority_low_reliability)
        self.assertEqual(prog.relocalization_stale_attempts, 2)
        prog_next = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertFalse(prog_next.distance_authority_low_reliability,
                          "role=next must read _next_stale_attempts, not current's")


class GrowingUncertaintyIntervalTest(unittest.TestCase):
    """2026-08-04. Growing-uncertainty variant of the staleness fix above --
    mirrors the isolated Route2 branch's [d-0.35, d+0.35] interval that
    widens by dead-reckoned travel since the last trusted reading. Onset pose
    is mutated directly on the agent (_return_pose_from_return_start) rather
    than driven through update_return_motion, to isolate the radius
    computation from the surrounding relocalization-attempt machinery, same
    technique this file's other test classes already use for their own
    isolated preconditions.
    """

    def _agent(self, base_floor=0.35, **kw):
        a = _pair_agent(
            sequential_pair_relocalization_uncertainty_mode="growing",
            stale_uncertainty_base_floor_m=base_floor,
            **kw,
        )
        a._target_anchor_index = 2  # current; next == 1
        return a

    def test_radius_is_none_when_mode_is_fixed(self):
        agent = _pair_agent()  # mode="fixed" (default)
        agent._target_anchor_index = 2
        agent._select_sequential_pair_relocalization([good_reading(2)])  # next absent -> stale=1
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertIsNone(prog.distance_uncertainty_radius_m)

    def test_radius_is_none_when_role_is_fresh(self):
        agent = self._agent()
        agent._select_sequential_pair_relocalization([good_reading(2), good_reading(1, dy=3.0)])
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertIsNone(prog.distance_uncertainty_radius_m, "next was present this attempt -> fresh, no radius")

    def test_radius_equals_base_floor_when_stale_but_stationary(self):
        agent = self._agent(base_floor=0.35)
        agent._select_sequential_pair_relocalization([good_reading(2)])  # next absent -> stale=1, onset recorded
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertAlmostEqual(prog.distance_uncertainty_radius_m, 0.35)

    def test_radius_grows_with_distance_traveled_since_onset(self):
        agent = self._agent(base_floor=0.35)
        agent._select_sequential_pair_relocalization([good_reading(2)])  # onset recorded here
        agent._return_pose_from_return_start = [2.0, 0.0, 0.0]  # simulate 2m of travel since onset
        agent._select_sequential_pair_relocalization([good_reading(2)])  # still absent -> stale=2
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertAlmostEqual(prog.distance_uncertainty_radius_m, 0.35 + 2.0)

    def test_onset_cleared_and_radius_resets_when_role_refreshes(self):
        agent = self._agent(base_floor=0.35)
        agent._select_sequential_pair_relocalization([good_reading(2)])  # next absent -> stale=1
        agent._return_pose_from_return_start = [2.0, 0.0, 0.0]
        agent._select_sequential_pair_relocalization(
            [good_reading(2), good_reading(1, dy=3.0)]
        )  # next present again -> resets
        self.assertIsNone(agent._next_stale_onset_pose)
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertIsNone(prog.distance_uncertainty_radius_m)

    def test_current_role_uses_current_onset_pose(self):
        agent = self._agent(base_floor=0.35)
        agent._select_sequential_pair_relocalization([good_reading(1, dy=3.0)])  # current absent -> stale=1
        agent._return_pose_from_return_start = [1.0, 0.0, 0.0]
        prog = agent._anchor_progress_from_estimate(good_reading(2), role="current")
        self.assertAlmostEqual(prog.distance_uncertainty_radius_m, 0.35 + 1.0)


class CrossRoleAgreementRouteMemoryTest(unittest.TestCase):
    """2026-08-04. current and next roles' ICP matches are against DIFFERENT
    anchors' point clouds -- a genuine independent cross-check, unlike
    anchor-corroboration's own reuse of this same reading. _latest_
    relocalization/_latest_next_candidate_relocalization are set directly on
    the agent (rather than built up through calls) to isolate
    cross_role_distance_to_start_m's own computation.
    """

    def _agent(self, **kw):
        a = _pair_agent(**kw)
        a._target_anchor_index = 2
        return a

    def test_next_role_reports_current_as_cross_role(self):
        agent = self._agent()
        agent._latest_relocalization = good_reading(2)
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        anchor2 = agent._anchor_by_index(2)
        expected = good_reading(2).distance_to_anchor_m + anchor2.route_remaining_to_start_m
        self.assertAlmostEqual(prog.cross_role_distance_to_start_m, expected)

    def test_current_role_reports_next_as_cross_role(self):
        agent = self._agent()
        agent._latest_next_candidate_relocalization = good_reading(1, dy=3.0)
        prog = agent._anchor_progress_from_estimate(good_reading(2), role="current")
        anchor1 = agent._anchor_by_index(1)
        expected = good_reading(1, dy=3.0).distance_to_anchor_m + anchor1.route_remaining_to_start_m
        self.assertAlmostEqual(prog.cross_role_distance_to_start_m, expected)

    def test_none_when_other_role_has_no_estimate(self):
        agent = self._agent()
        prog = agent._anchor_progress_from_estimate(good_reading(1, dy=3.0), role="next")
        self.assertIsNone(prog.cross_role_distance_to_start_m, "no cached current estimate -> cannot verify")


class _Progress:
    """Duck-typed stop_gate progress stub with the Injection-C field."""
    def __init__(self, d, conf, bearing=0.0, anchor_route_remaining_m=None,
                 low_reliability=None, relocalization_stale_attempts=None):
        self.distance_to_start_m = d
        self.relocalization_confidence = conf
        self.filter_std_m = None
        self.bearing_to_start_deg = bearing
        self.source = "sequential_pair"
        self.anchor_route_remaining_m = anchor_route_remaining_m
        self.distance_authority_low_reliability = low_reliability
        self.relocalization_stale_attempts = relocalization_stale_attempts


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

    def test_relocalization_stale_attempts_passed_through_to_decision(self):
        gate = self._gate()
        dec = gate.check(
            _Progress(8.0, conf=0.9, low_reliability=True, relocalization_stale_attempts=42),
            vlm_issued_stop=True,
        )
        self.assertEqual(dec.relocalization_stale_attempts, 42)

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


class MechanismDCorroborationOverrideTest(unittest.TestCase):
    """2026-08-04 (Mechanism D fix, investigations/2026-07-28-downgrade-batch-
    mechanism-failure-classification/FINDINGS.md): anchor-corroboration's veto
    was silently unreachable whenever distance_authority_low_reliability was
    also true, even though corroboration is explicitly designed to be trusted
    independent of this attempt's own reading quality. Root cause of ep205:
    d=10.76m, anchor's own remaining=7.05m -- both corroboration conditions
    satisfied, but the low-reliability defer fired first (unconditionally,
    before the flag in this test class existed).
    """

    def _far_progress(self, low_reliability=True, anchor_route_remaining_m=7.05):
        return _Progress(
            10.76, conf=0.9, low_reliability=low_reliability,
            anchor_route_remaining_m=anchor_route_remaining_m,
        )

    def test_off_by_default_still_defers(self):
        gate = ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, anchor_corroboration_enabled=True,
        )
        dec = gate.check(self._far_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred", "flag off -> byte-identical prior behaviour")

    def test_on_vetoes_when_corroboration_conditions_satisfied(self):
        gate = ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, anchor_corroboration_enabled=True,
            corroboration_overrides_low_reliability=True,
        )
        dec = gate.check(self._far_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")
        self.assertIsNotNone(dec.suggested_command)

    def test_on_still_defers_without_anchor_corroboration_enabled(self):
        gate = ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, anchor_corroboration_enabled=False,
            corroboration_overrides_low_reliability=True,
        )
        dec = gate.check(self._far_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_on_still_defers_when_anchor_itself_reads_close(self):
        # anchor_route_remaining <= r_in -> corroboration conditions NOT both
        # satisfied (anchor says close, reading says far -- a contradiction,
        # not corroborated evidence, per the module docstring).
        gate = ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, anchor_corroboration_enabled=True,
            corroboration_overrides_low_reliability=True,
        )
        dec = gate.check(self._far_progress(anchor_route_remaining_m=1.0), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_on_still_defers_when_not_low_reliability(self):
        # low_reliability=False -> this branch is never reached at all, the
        # normal high-conf accept/veto/defer path decides instead. d=10.76 >
        # r_out with high conf -> that path alone already vetoes, so this
        # only confirms the new branch isn't doubly interfering.
        gate = ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, anchor_corroboration_enabled=True,
            corroboration_overrides_low_reliability=True,
        )
        dec = gate.check(self._far_progress(low_reliability=False), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")

    def test_force_path_unaffected_by_new_flag(self):
        # FORCE's own anchor-corroboration was already unconditional on
        # low_reliability before this fix -- confirm the new flag doesn't
        # change that path at all (byte-identical either way).
        for corroboration_overrides_low_reliability in (False, True):
            gate = ReturnStopGate(
                r_in=3.0, r_out=3.0, min_confidence=0.5, anchor_corroboration_enabled=True,
                forced_stop_anchor_confirm_steps=2,
                corroboration_overrides_low_reliability=corroboration_overrides_low_reliability,
            )
            close = _Progress(2.0, conf=0.9, low_reliability=True, anchor_route_remaining_m=2.0)
            gate.check(close, vlm_issued_stop=False)
            dec = gate.check(close, vlm_issued_stop=False)
            self.assertEqual(dec.decision, "forced")


class BlindBudgetTest(unittest.TestCase):
    """2026-08-04. A distance_authority_low_reliability-driven 'deferred' is,
    in effect, an unconditional accept of the VLM's own stop claim -- bound
    how many consecutive such attempts can happen before falling back to
    'keep moving' instead of 'keep blindly trusting'. See
    GateDecision.blind_streak / blind_budget_enabled's docstrings.
    """

    def _gate(self, max_attempts=3, **kw):
        return ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5,
            blind_budget_enabled=True, blind_budget_max_attempts=max_attempts,
            **kw,
        )

    def _blind_progress(self):
        return _Progress(8.0, conf=0.9, low_reliability=True)

    def test_off_by_default_defers_forever(self):
        gate = ReturnStopGate(r_in=3.0, r_out=3.0, min_confidence=0.5)  # flag off
        for _ in range(50):
            dec = gate.check(self._blind_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred", "flag off -> byte-identical prior behaviour")

    def test_defers_until_budget_exceeded_then_treated_like_veto(self):
        gate = self._gate(max_attempts=3)
        for _ in range(3):
            dec = gate.check(self._blind_progress(), vlm_issued_stop=True)
            self.assertEqual(dec.decision, "deferred")
        dec = gate.check(self._blind_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "blind_budget_exhausted")
        self.assertIsNotNone(dec.suggested_command)

    def test_blind_streak_counts_regardless_of_vlm_issued_stop(self):
        # the ep89-style "reached true position but never proposed stop"
        # gap: blindness accumulates even when the VLM never asks to stop.
        gate = self._gate(max_attempts=3)
        for _ in range(3):
            dec = gate.check(self._blind_progress(), vlm_issued_stop=False)
            self.assertEqual(dec.decision, "pass")
        self.assertEqual(dec.blind_streak, 3)
        dec = gate.check(self._blind_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "blind_budget_exhausted", "budget already exhausted pre-stop")

    def test_a_trustworthy_reading_resets_the_streak(self):
        gate = self._gate(max_attempts=3)
        for _ in range(3):
            gate.check(self._blind_progress(), vlm_issued_stop=True)
        trustworthy = _Progress(8.0, conf=0.9, low_reliability=False)
        dec = gate.check(trustworthy, vlm_issued_stop=False)
        self.assertEqual(dec.blind_streak, 0)
        # back to deferred, not exhausted, since the streak restarted
        dec = gate.check(self._blind_progress(), vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred")

    def test_corroboration_veto_still_takes_priority_over_blind_budget(self):
        # when both the Mechanism-D override and blind-budget are on, and
        # corroboration's own conditions are satisfied, that veto should
        # still fire -- it's a more specific, positive signal than merely
        # "we've been blind a while."
        gate = self._gate(
            max_attempts=1, anchor_corroboration_enabled=True,
            corroboration_overrides_low_reliability=True,
        )
        far = _Progress(10.76, conf=0.9, low_reliability=True, anchor_route_remaining_m=7.05)
        gate.check(far, vlm_issued_stop=True)
        dec = gate.check(far, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed", "corroboration's own veto pre-empts blind-budget")


class UncertaintyIntervalConsumerTest(unittest.TestCase):
    """2026-08-04. stop_gate side of the growing-uncertainty variant: widen
    accept/veto's point comparison by distance_uncertainty_radius_m when
    use_uncertainty_interval is on. _Progress has no constructor kwarg for
    this field (added after _Progress was written) -- set directly on the
    instance; getattr(progress, ..., None) picks it up either way, matching
    how route_memory_agent.py's own duck-typed RelativeStartProgress works.
    """

    def _gate(self, **kw):
        return ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, use_uncertainty_interval=True, **kw
        )

    def test_off_by_default_ignores_radius(self):
        gate = ReturnStopGate(r_in=3.0, r_out=3.0, min_confidence=0.5)  # flag off
        prog = _Progress(2.9, conf=0.9)
        prog.distance_uncertainty_radius_m = 5.0  # huge radius, must be ignored
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted", "flag off -> byte-identical, ignores radius")

    def test_accept_blocked_when_worst_case_exceeds_r_in(self):
        gate = self._gate()
        prog = _Progress(2.9, conf=0.9)
        prog.distance_uncertainty_radius_m = 0.5  # 2.9+0.5=3.4 > r_in=3.0
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred", "worst case exceeds r_in -> not confidently accepted")

    def test_accept_still_fires_when_worst_case_within_r_in(self):
        gate = self._gate()
        prog = _Progress(2.4, conf=0.9)
        prog.distance_uncertainty_radius_m = 0.5  # 2.4+0.5=2.9 <= r_in=3.0
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")

    def test_veto_blocked_when_best_case_within_r_out(self):
        gate = self._gate()
        prog = _Progress(3.2, conf=0.9)
        prog.distance_uncertainty_radius_m = 0.5  # 3.2-0.5=2.7 <= r_out=3.0
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred", "best case within r_out -> not confidently vetoed")

    def test_veto_still_fires_when_best_case_beyond_r_out(self):
        gate = self._gate()
        prog = _Progress(8.0, conf=0.9)
        prog.distance_uncertainty_radius_m = 0.5  # 8.0-0.5=7.5 > r_out=3.0
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "vetoed")

    def test_missing_radius_behaves_like_point_comparison(self):
        gate = self._gate()
        prog = _Progress(2.9, conf=0.9)  # distance_uncertainty_radius_m left unset -> getattr default None
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted", "no radius info -> falls back to point comparison")


class CrossRoleAgreementStopGateTest(unittest.TestCase):
    """2026-08-04. FORCE/ACCEPTED additionally require the other role's own
    independent distance estimate to agree, targeting the recurring
    'confidently wrong' false-FORCE class (ep669/93/581/427) where anchor-
    corroboration's own two 'independent' signals turn out to be the same
    poisoned identity agreeing with itself. _Progress has no constructor
    kwarg for cross_role_distance_to_start_m -- set directly on the instance,
    matching UncertaintyIntervalConsumerTest's own convention.
    """

    def _gate(self, max_disagreement=1.5, **kw):
        return ReturnStopGate(
            r_in=3.0, r_out=3.0, min_confidence=0.5, confirm_steps=3,
            require_cross_role_agreement=True,
            cross_role_max_disagreement_m=max_disagreement,
            **kw,
        )

    def test_off_by_default_ignores_cross_role(self):
        gate = ReturnStopGate(r_in=3.0, r_out=3.0, min_confidence=0.5)  # flag off
        prog = _Progress(2.0, conf=0.9)
        prog.cross_role_distance_to_start_m = 20.0  # wildly disagrees, must be ignored
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted", "flag off -> byte-identical, ignores cross-role")

    def test_accept_blocked_when_cross_role_disagrees(self):
        gate = self._gate()
        prog = _Progress(2.0, conf=0.9)
        prog.cross_role_distance_to_start_m = 20.0
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "deferred", "cross-role disagreement blocks accept")

    def test_accept_fires_when_cross_role_agrees(self):
        gate = self._gate()
        prog = _Progress(2.0, conf=0.9)
        prog.cross_role_distance_to_start_m = 2.3  # within 1.5m
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted")

    def test_accept_fires_when_cross_role_missing(self):
        gate = self._gate()
        prog = _Progress(2.0, conf=0.9)  # cross_role_distance_to_start_m left unset -> None
        dec = gate.check(prog, vlm_issued_stop=True)
        self.assertEqual(dec.decision, "accepted", "cannot verify -> must not block")

    def test_force_blocked_when_cross_role_disagrees(self):
        gate = self._gate()
        prog = _Progress(2.0, conf=0.9)
        prog.cross_role_distance_to_start_m = 20.0
        for _ in range(3):
            dec = gate.check(prog, vlm_issued_stop=False)
        self.assertEqual(dec.decision, "pass", "cross-role disagreement blocks force")

    def test_force_fires_when_cross_role_agrees(self):
        gate = self._gate()
        prog = _Progress(2.0, conf=0.9)
        prog.cross_role_distance_to_start_m = 2.5  # within 1.5m
        for _ in range(2):
            dec = gate.check(prog, vlm_issued_stop=False)
            self.assertEqual(dec.decision, "pass")
        dec = gate.check(prog, vlm_issued_stop=False)
        self.assertEqual(dec.decision, "forced")


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
