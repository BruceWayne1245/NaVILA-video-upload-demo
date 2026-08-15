# hint_action_arbiter: single-reading confidence collapse has two sub-causes

Date: 2026-08-15
Status: **root-caused, direction agreed for the ②b/③ sub-case, NOT YET
IMPLEMENTED**. ②a (genuine ambiguity) direction proposed but not yet decided.
To land together with
[investigations/2026-08-15-v11-quarantine-veto](../2026-08-15-v11-quarantine-veto/FINDINGS.md)
and
[investigations/2026-08-15-hint-action-turn-gate-fix](../2026-08-15-hint-action-turn-gate-fix/FINDINGS.md).

## Background

Of the 22 return-failure episodes traced back to `hint_action_arbiter`
guidance going silent (`reason=low_relocalization_confidence, desired=None`)
on batch `line2_closure_off_cooldown_kdtree_100ep_20260815`, only 5-6 fit the
"turn override blocked/incomplete" pattern (see the turn-gate-fix doc). The
larger remaining group (~16 episodes) shows guidance going silent with no
turn-blocking event at all. This document root-causes that group.

## Two distinct sub-causes, same symptom

Checked real per-attempt diagnostic fields for the "next"-role candidate
(recomputed via `sequential_pair_anchor_relocalization` against the real
captured point cloud — not the production log, which only records the
*selected* current-role estimate, not next's own raw diagnostics) at the
exact steps `[hint_arbiter]` reported `low_relocalization_confidence`.

**②a — genuine, persistent ICP yaw/pose ambiguity** (e.g. `ep814`, next
role = anchor4): confidence 0.55-0.65, `match_class="ambiguous_high_confidence"`,
`best_to_second_score_ratio` 0.87-0.99 (near-tied top-2 pose hypotheses),
**stable across 175 real steps** — not noise, a persistent geometric symmetry
at that anchor's location the single-attempt ICP genuinely cannot resolve.
Ground-truth `true_dist` stays small/stable (~1.0-1.27m) the whole window —
the robot has not drifted, the anchor is just hard to disambiguate from a
single reading.

**②b / ③ — reading is basically accurate, confidence just noisily dips below
the 0.90 threshold** (e.g. `ep304`, `ep484`): `match_class="clean_full_pose"`
(not flagged ambiguous), estimated distance tracks ground truth closely
(`ep484` step 1075, the FIRST attempt of the whole return phase: true=0.54m,
est=0.59m — near-perfect), yet confidence=0.887, **0.013 below the 0.90
cutoff**. `ep484`'s current anchor never promotes even once across the
entire 1001-attempt return phase; guidance goes silent from the very first
attempt for a reading that was essentially correct.

Both sub-causes hit the same catastrophic downstream path: `check()` reads
only the single latest `relocalization_confidence` value (no window, no
trend, no re-evaluation) — one dip below 0.90, for whatever reason, and
`desired_kind` becomes permanently `None` for as long as current stays
pinned at that anchor (which, per the rest of this session's investigation,
is itself often indefinite).

## Decision: extend `trend_confidence` to hint_action_arbiter (②b/③)

This session earlier built `trend_confidence_enabled` for `stop_gate.py`
(rolling window, requires >=N high-confidence votes within
`trend_confidence_max_distance_spread_m` agreement to override a single
low-confidence reading) — implemented, tested (7 unit tests), verified not
to regress existing behavior when off. At the time the user explicitly asked
to keep evaluating other application sites rather than discard it after the
stop_gate A/B showed no aggregate lift (mid-session, ~feedback memory
`project_stage2_yaw_fix_and_residual_gate_20260726`-adjacent thread). **This
is that site.** Wiring the same window/vote logic into
`hint_action_arbiter`'s `relocalization_confidence` check directly targets
②b/③: a reading that is repeatedly close to (or just under) the threshold,
with agreeing distance estimates, should not permanently silence guidance
over one noisy dip.

Not yet decided how to handle ②a (genuine, stable ambiguity) — trend
smoothing over a *persistently* ambiguous reading won't resolve it (the
ambiguity doesn't average out; it's not noise). Two directions floated, not
yet chosen:
- Wire `loftr_rear_yaw_check`'s vision cross-check to actively arbitrate
  between the near-tied basins when `match_class="ambiguous_high_confidence"`
  is detected on the "next" role feeding hint_action_arbiter, instead of its
  current sole use (downgrading already-confident readings, precondition
  `confidence >= 0.9` — never fires for ②a since raw confidence is already
  <0.9 there, so it's structurally dead code for exactly this case).
  Requires wiring, not yet built or estimated.
- Accept ②a as currently unresolvable per-reading and rely on other
  mechanisms (V1.1 veto reducing how often current gets stuck near an
  inherently ambiguous anchor in the first place; downstream `stop_gate`
  cross-role-agreement as a backstop) rather than trying to fix hint_action
  specifically for this sub-case.

## Implementation sketch (not yet built)

- Reuse the existing `trend_confidence_enabled`/`_trend_confidence_trusts`
  pattern from `stop_gate.py` (same window/min-samples/max-distance-spread
  parameters), new opt-in flag on `HintActionArbiterConfig`
  (`trend_confidence_enabled: bool = False`).
  `hint_action_arbiter.check()` would need its own rolling history keyed by
  target anchor (reset when `target_anchor_index` changes, mirroring
  `_promotion_vote_history`'s per-anchor-index convention elsewhere in this
  codebase), and override `relocalization_confidence < min_relocalization_confidence`
  with a trusted trend read the same way `stop_gate.check()` does today.
- Needs offline replay validation against real captured data before
  adoption, per this project's established methodology — not yet done.

## Scope not yet quantified

The exact ②a vs ②b/③ split across all ~16 affected episodes has not been
fully enumerated — only `ep814` (②a) and `ep304`/`ep484` (②b/③) were directly
checked. Full classification (per-episode real diagnostic check, same method
as above) is the natural next step before estimating how many of the 16 the
trend_confidence extension alone would fix vs. how many need the
still-undecided ②a fix too.
