# 2026-07-13 (continued 4) — Is the fusion-corruption problem actually fixed? Why does fusion exist? Can bearing be reported without ever touching dtheta?

**Purpose**: prompted by the user's question about why rotation-angle (dtheta) instability matters when their own system only consumes bearing/distance-to-anchor. This document answers three concrete questions with code + fresh data, not recollection: (1) is `trust_aware_guard` (2026-07-07) actually fixing the fusion-corruption problem today, on real 07-10/07-12 live-batch data; (2) what was closure-check/belief-fusion originally built to solve, and does that reason still apply to the current code; (3) is it structurally possible to report bearing without ever letting dtheta corrupt it.

## 1. Is fusion-corruption fixed? No — and a second, unpatched mechanism is now the dominant cause

Matched every reported/fused `relocalization_event` (n=4334, pooled across the `promotion_use_raw_estimates_hard11_20260710_accumulated` and `short_baseline_hard11_20260712_accumulated` batches — both already have `trust_aware_guard` on) against the *raw* per-candidate covisibility record for the same anchor at the same attempt, and computed both against ground truth.

| | raw (pre-fusion) | fused/reported (what actually gets used) |
|---|---|---|
| median bearing error | 2.18° | **6.15°** |
| mean bearing error | 13.56° | **23.70°** |

| category | n | % |
|---|---|---|
| **FUSION-CORRUPTED** (raw <15°, fused >45°) | 309 | **7.13%** |
| FUSION-FIXED (raw >45°, fused <15°) | 21 | 0.48% |
| both bad (>45° both) | 277 | 6.39% |
| both good (<15° both) | 2710 | 62.53% |

**Fusion corrupts ~15x more readings than it fixes (7.13% vs 0.48%).** `trust_aware_guard` (built 2026-07-07 specifically to stop this) is still active in both batches this data comes from — the corruption rate has not gone to zero.

**New finding — a second, un-guarded mechanism is now responsible for the majority of it.** Breaking down the 309 corrupted events by their `backend` tag:

| backend tag | n corrupted | has `+ema` suffix? |
|---|---|---|
| `sequential_pair+belief_fused+ema` | 249 | yes |
| `sequential_pair+ema` | 23 | yes |
| `sequential_pair+belief_trust_aware_reconstructed+ema` | 17 | yes |
| `sequential_pair+belief_fused` | 13 | no |
| `sequential_pair+belief_trust_aware_reconstructed` | 7 | no |

**289/309 (93.5%) of today's fusion-corrupted readings carry the `+ema` suffix** — i.e. they passed through `_temporally_smooth_relocalization()`, a *separate* blending step (`route_memory_agent.py:1741`) called unconditionally on every accepted estimate (`route_memory_agent.py:853`, right after `_select_sequential_pair_relocalization` returns), not just when `sequential_pair_closure_check` is enabled. It blends the fresh accepted estimate with the *previous* accepted estimate (reprojected onto the new anchor via the same `_reproject_delta_to_anchor` dtheta-dependent geometry), using the exact same `circular_weighted_mean` primitive already proven numerically unstable for large disagreements (the 2026-07-07 investigation's whole finding). Its only escape hatch is a blunt disagreement cutoff, `orientation_filter_max_disagreement_rad = 60°` — there is no `trust_aware_guard`-style match_class/near_tie check here at all; `trust_aware_guard` only patches `_sequential_pair_closure_belief_fusion` (the *current-vs-next, same-attempt* cross-check), never `_temporally_smooth_relocalization` (the *this-attempt-vs-previous-attempt* blend). **The exact bug class trust_aware_guard was built to fix in one place is still live, unguarded, in a second place — and today it's responsible for the large majority of the remaining corruption.** 23 of the 309 corrupted events (`sequential_pair+ema`, no belief_fused/trust_aware tag at all) show this mechanism corrupting a reading that the same-attempt cross-check found *perfectly fine* — proof this is an independent corruption source, not just fusion's damage carrying an extra tag.

Note this same EMA step runs on essentially every accepted event regardless of whether it was fusion-corrupted (4209/4334 = 97.1% of all events carry `+ema`), so this is not a rare edge case — it is the default path.

## 2. Why does fusion (continuous blend) exist at all, and does that reason still hold?

Read directly from `_sequential_pair_closure_belief_fusion`'s own docstring (`route_memory_agent.py:2067`): belief-mode blending (instead of outright rejecting a disagreement) exists because *"`_sequence_match_observation`'s `no_sequence_candidates` gate depends on `_distance_since_sequence_observation_m` staying near zero (it only resets on an accepted observation); an outright reject skips that reset and... can cascade into a permanent, unrecoverable stall once dead-reckoning drift compounds past that gate's own tolerance — five of seven regressed episodes in that batch showed exactly this signature."* This was a real, measured 2026-07-05 regression in the *old* odometer/arc-length architecture.

**Checked directly against the current code: that justification no longer applies.** `_select_sequential_pair_relocalization` (the function actually driving the live `sequential_pair` backend, `route_memory_agent.py:1184`) never calls `_sequence_match_observation` at all — it has its own, separate selection logic (`close_enough`/`trend_ok`/`quality_ok` promotion gates, `route_memory_agent.py:1264-1284`), and none of its own reject paths (`no_pair_candidates`, `no_target_anchor`, `no_current_or_next_anchor_candidates`, `no_selected_pair_candidate`, `no_sequence_observation`) touch `_distance_since_sequence_observation_m` or depend on any reset happening. `_sequence_match_observation` (the function whose gate the fusion docstring is protecting) is legacy code retained for older, non-`sequential_pair` backends. This matches and directly confirms (by independently reading the code, not recalling) the same conclusion the 2026-07-08 trend-gated-reject investigation already reached from a different angle.

**Answer: fusion's original justification is stale.** The current `sequential_pair` architecture has no odometer-reset dependency for an outright reject to break. Rejecting a genuinely irreconcilable current/next disagreement outright today would not reintroduce the 2026-07-05 stall — there is nothing left in the live call path for it to stall.

**Caveat — the *cross-check itself* (not the continuous-blend design choice) did catch real problems before belief mode existed**: the closure-check's own docstring (`route_memory_agent.py:1859`) says the original "threshold" mode (reject when neither side dominates, else substitute) *"catches 3 of 4 known single-bad-ICP-read overshoot triggers."* So the fix here is not "delete the cross-check" — it's "stop being forced to smoothly blend disagreements that should just be rejected or resolved by the already-built match_class/near_tie trust signal," which `trust_aware_guard` already does for large disagreements. The gap is (a) `trust_aware_guard`'s own large-disagreement threshold still lets a "moderate" disagreement band fall through to the old blend (a previously-documented, still-open gap from 2026-07-08), and (b) `_temporally_smooth_relocalization` has no `trust_aware_guard` equivalent at all.

## 3. Can bearing be reported without dtheta ever corrupting it?

Checked every place dtheta is actually *consumed* in the current `sequential_pair` path:

- **Promotion timing** (`close_enough`, `trend_ok`, `quality_ok`) — computed from `distance_to_anchor_m` and `confidence * sqrt(inlier_count)` only. **Does not use dtheta at all.**
- **The reported hint fields** (`bearing_to_anchor_deg`, `distance_to_anchor_m`) — derived purely from `(anchor_dx_m, anchor_dy_m)`. **dtheta's numeric value is never read by the hint itself**, only a derived boolean (`anchor_heading_reliable`) is exposed.
- **The only two places dtheta's numeric value is used for cross-reading reconciliation** (the only way it can corrupt bearing) are exactly the two mechanisms audited above: `_sequential_pair_closure_precheck`/`_sequential_pair_closure_belief_fusion` (current-vs-next, same attempt) and `_temporally_smooth_relocalization` (this-attempt-vs-previous, across time). Both use `_reproject_delta_to_anchor`, which needs dtheta to convert one anchor's reading into another anchor's frame.

**So yes, structurally**: if both of these reconciliation steps were replaced with "just report whichever single anchor's own raw `(dx, dy)` was selected, unmodified" (i.e. keep dtheta only as a per-attempt diagnostic input to `match_class`/`near_tie_basin_count`, never as a value that gets blended or reprojected across readings), the entire fusion-corruption pathway (the 7.13% figure above) would disappear by construction — there would be no mechanism left that can take a clean raw bearing and make it worse. **The trade-off**: this would also give up whatever the closure-check's cross-anchor check catches (3/4 of a specific single-bad-ICP-overshoot failure mode, per its own docstring) and the EMA filter's original purpose (damping single-observation position/heading jitter across attempts, `route_memory_agent.py:1742`'s "Direction 1 persistent-error fix"). Given this document's own numbers (0.48% fixed vs 7.13% corrupted for the cross-anchor fusion), that trade looks favorable; the EMA step's own fix-vs-corrupt ratio hasn't been isolated separately in this analysis and would be worth checking before removing it outright — but 93.5% of currently-corrupted readings pass through it, so at minimum it needs the same match_class/near_tie-based trust check `trust_aware_guard` already gave the other mechanism.

## Recommendation

1. **Extend `trust_aware_guard`'s match_class/near_tie trust logic to `_temporally_smooth_relocalization`**, not just `_sequential_pair_closure_belief_fusion` — this is the single highest-leverage fix identified in this whole investigation line, since it's implicated in 93.5% of currently-measured corruption and has no guard at all today.
2. **Re-examine whether continuous blending is needed at all now that the 2026-07-05 stall-avoidance justification is stale** — a real reject/downgrade path (mirroring the 2026-07-08 trend-gated-reject design that was validated-as-flawed but never re-attempted with a value-consistency signal) is worth a second look now that its original blocking concern (the odometer-reset dependency) is confirmed gone.
3. Before doing (1) or (2) live, offline-replay this same corrupted-event set against a candidate fix (match_class-guarded EMA) the same way `trust_aware_guard` itself was validated, to directly measure whether the 7.13% corrupted-rate drops.

## Reproducibility

Script: `code/fusion_corruption_check_20260713.py` in this folder. Data: `promotion_use_raw_estimates_hard11_20260710_accumulated` + `short_baseline_hard11_20260712_accumulated` measurement JSONs (already-established batches, no new live run needed for this analysis).
