# 2026-07-08 — `hard11_live_trust_aware_guard_20260707_accumulated` full analysis: anchor-selection accuracy, ICP bearing/distance accuracy, comparison vs no-guard baseline, and root-cause of residual bearing-error outliers

This document consolidates every analysis run against the `hard11_live_trust_aware_guard_20260707_accumulated` live batch (the first full hard-11 live A/B validation of `--sequential_pair_closure_belief_trust_aware_guard`, launched 2026-07-07T19:04, finished 2026-07-07T21:18:51, 2h14m). It supersedes the "pending analysis" note at the top of the main README as of 2026-07-07.

## 1. Round-trip outcome: 8/11 vs the no-guard baseline's 7/11

Batch summary (`summary.tsv`) initially undercounted successes because `ep678`/`ep680`'s `measurements/*.json` hit the same intermittent write-corruption bug already documented for `--capture_anchor_match_snapshots`/`--capture_icp_replay_dataset` (spliced/duplicated/dropped JSON fragments from live Isaac Sim writes) — this time on plain measurement output too. Five distinct corruption patterns were found and repaired with targeted regex passes (phantom key/value pairs, duplicated floats glued to the next key, doubled array-closing brackets) rather than discarding the files; both parsed cleanly afterward and confirmed `round_trip_success=True` for both (`ep678`: distance_to_start=1.617m; `ep680`: 1.125m), matching what the raw trajectory JSONL already implied.

Corrected outcome: `ep4/5/187/368/678/680/994/1040` succeeded (8), `ep134/367/408` failed (3, all pre-existing unrelated gaps — `ep134` VLM-startup-timeout, `ep367` VLM-startup-timeout this run, `ep408` the known "robot stops moving" bug, this time manifesting during outbound rather than return). vs. the same-day no-guard baseline (`hard11_live_bounded_evidence_alias_20260707_accumulated`, ran 13:37–16:29): 7/11 (`ep5` failed there — see §3). The `ep134/187/367` swings between the two batches trace to VLM-server-startup flakiness (pre-existing, unrelated to today's fix), not the guard.

## 2. Anchor-selection accuracy (shadow vs. ground truth), n=2788 dedup relocalization events across the 8 usable episodes

Methodology (reused from the 2026-07-07 investigation, validated then): "current anchor" ground truth = `target_anchor_for_route_position(oracle_route_current_s_m)` (largest anchor whose `distance_from_start_m` ≤ the robot's true route-arc-length position); "next anchor" (oracle) = oracle's own live `target_anchor_index` (lookahead-shifted). Shadow only exposes one index per step (`route_memory_shadow.target_anchor_index`, i.e. `RouteMemoryAgent._target_anchor_index`), so it is compared against both references.

**Current anchor vs. true position:** 55.9% exact match, 13.8% lag-1 (consistent with `bounded_evidence`'s built-in 3-of-5-vote confirmation delay), 8.9% lag≥2, 21.2% overshoot (never ≥3 anchors — confirms the structural "advance at most one anchor per attempt" guarantee holds). **90%+ of all lag≥2 events come from a single episode, `ep5`** (see §3) — excluding it, lag≥2 drops to 1.2%.

**Next anchor vs. oracle's `target_anchor_index`:** dominated by lag (79.0%: 55.9% lag-1, 14.1% lag-2, 9.0% lag≥3), lead only 0.9%. This is **not a new finding** — oracle's own pointer is deliberately lookahead-shifted (`target_s = current_s − lookahead_m`) to avoid VLM spin-in-place, while shadow reports its un-shifted "current" anchor; the two are offset by design, matching the 2026-07-07 entry's "0–2-anchor lag dominant, consistent with `bounded_evidence`'s confirmation delay" finding. **Recomputing "next anchor" against a position-based reference instead of oracle's pointer collapses mathematically to the exact same distribution as "current anchor" above** (shadow has no separate reported "next" value — its one index plays both roles), confirming the 79%-lag number is mostly a definitional artifact of the two different reference points, not a shadow tracking failure.

## 3. `ep5`: severe, but confirmed-legitimate, `alias_aware` promotion stall

Run-length-encoding shadow's raw `target_anchor_index` sequence (356 events) shows only 4 distinct anchors ever visited (13→12→11→10), with **anchor11 stuck for 169 consecutive events and anchor10 for 153 (322/356 = 90% of the episode)** — the episode still succeeded physically (`distance_to_start=1.308m`) only because the VLM navigates off the oracle hint, not the shadow. Covisibility diagnostics for the stuck anchors show genuine ambiguity, not a silent bug: anchor11/anchor10 show 46% `ambiguous_high_confidence` match_class and mean `near_tie_basin_count` 2.2–2.4 (vs. typically 0 for clean anchors). This matches the already-documented 2026-07-06 finding that `ep5`'s route is uniformly self-similar (alias_score 0.61–0.91 on *every* anchor) — neither stall reached the 200-attempt `alias_stall_attempts` relief threshold before the episode ended, so promotion legitimately never got the required 5-of-8 confirming votes. **Actionable, not yet changed:** 200 may be too conservative for routes this uniformly self-similar.

`ep5` alone also explains most of the raw distance-error tail (see §4) via stale-reading effects (shadow frozen on anchor10 while the robot's true distance to it kept growing).

## 4. ICP bearing/distance accuracy, guard batch pooled (n=2788)

| | distance (m) | bearing (deg) |
|---|---|---|
| median | 0.075 | 5.64 |
| mean | 0.260 | 19.88 |
| p90 | 0.503 | 57.17 |

Distance mean is pulled up **37% by `ep5` alone** (excluding it: median 0.069m, mean 0.163m, p90 0.393m) — top-15 distance outliers are all `ep5`/anchor10, a stale-reading artifact of §3's stall, not a per-attempt ICP failure. Bearing mean is **not** dominated by any single episode (excluding `ep5`: mean 19.74°, essentially unchanged) — the bearing tail is genuinely spread across episodes.

**Per-(episode, anchor) breakdown (99 groups) isolates exactly how much of the bearing tail is a few bad anchors vs. broad noise:** 15/99 groups (9.8% of all 2788 readings) have group-mean bearing error >45°; excluding them, the remaining 90.2% of readings have **median 4.73°, mean 14.65°, p90 39.49°** — a materially better picture than the pooled numbers above. The 15 bad groups are not evenly scattered: `ep678` (5/16 anchors), `ep187` (4/15), `ep680` (2/17), `ep994` (2/16), `ep368` (1/12), `ep5` (1/4) — always a minority of each episode's anchors, never a wholesale-episode failure.

Diagnostics on those 15 groups split into two distinct signatures:
- **"Confidently wrong"** (majority `clean_full_pose`, overlap 0.7–1.05, `near_tie_basin_count`≈0) — e.g. `ep678 anchor16` (9/9 clean, overlap 0.99), `ep187 anchor16/17` (100% clean), `ep5 anchor13` (100% clean). Nothing in the existing diagnostics flags these; they are the still-open "anchor-15-style" rotational self-similarity problem (distinct from anchor-identity aliasing), unrelated to the fusion bug this fix targeted.
- **"Genuinely ambiguous, self-reporting"** — e.g. `ep187 anchor6/13` (`near_tie_basin_count` mean 1.24–1.43, 25–41 `ambiguous_high_confidence` readings), `ep994 anchor10` (43% `partial_pose_degenerate`, `corridor_degeneracy_ratio` 0.95). These *do* self-report uncertainty in their own diagnostics — see §6 for why that signal still isn't acted on.

## 5. Comparison vs. the same-day no-guard live baseline (`hard11_live_bounded_evidence_alias_20260707_accumulated`, 9 usable episodes, n=3849)

| | no-guard | guard | Δ |
|---|---|---|---|
| distance median/mean/p90 (m) | 0.250 / 1.165 / 4.722 | 0.075 / 0.260 / 0.503 | −70% / −78% / −89% |
| bearing median/mean/p90 (deg) | 19.89 / 42.83 / 147.02 | 5.64 / 19.88 / 57.17 | −72% / −54% / −61% |
| current-anchor exact match | 40.4% | 55.9% | +15.5pp |
| current-anchor overshoot | 45.8% | 21.3% | −24.5pp |

**Every one of the 7 episodes common to both batches improved on bearing mean, with zero regressions**: `ep4` 43.50°→7.41°, `ep5` 72.13°→20.80°, `ep368` 26.13°→12.37°, `ep678` 43.57°→31.59°, `ep680` 43.87°→22.24°, `ep994` 38.77°→19.59°, `ep1040` 27.15°→19.39°. This is a live-batch confirmation of the fix at a scale (9 episodes, thousands of readings) beyond the single-anchor offline validation that motivated launching it (§6).

## 6. What "yesterday's" (2026-07-07) offline LiDAR validation actually covered — and its limits

Two distinct, non-overlapping pieces of offline evidence preceded the live batch, both in session `ee5c40d7-7b90-41dd-820f-cca908540482`'s scratch work (not yet committed to the repo before this writeup):

1. **`fusion_corruption_full_survey.py` (16:58, 8 usable episodes, n=2793 readings)** — replayed the *pre-guard* pipeline and compared fused vs. raw single-anchor ICP: fused median=6.63° mean=30.28° p90=122.90° vs. **raw median=2.50° mean=19.86° p90=78.97°**. This established that raw ICP was already good and the fusion layer was the problem — the evidence that motivated *building* the guard.
2. **`validate_guard_ep187_detail.py` (17:36–18:48, single anchor: `ep187`/anchor14, n=43 readings)** — offline guard on/off comparison: 48.30°→**8.91°** mean, 37.2%→4.7% of readings >45°. This one result is what justified *launching* the live 11-episode batch.

**There was no full-scale (8+ episode) offline validation of the guard turned ON before the live batch ran.** Today's live batch (§4–§5) is the first time the fix has been validated beyond that single anchor, and it holds up — in fact the live-batch aggregate improvement is broader than the single-anchor offline number predicted.

## 7. Root cause of the residual bearing-error outliers (§4's 15 bad groups): the trust-aware substitution mechanism is not miscalibrated, it's under-triggered

Code-verified in `route_memory_agent.py`. `_sequential_pair_closure_belief_fusion` (the quality-weighted blend, `confidence * sqrt(inlier_count)`) overwrites **both** anchors' final `dx/dy/dtheta` — `fused_b` is `_reproject_delta_to_anchor`'d *from* the blended `fused_a`, not derived from `b`'s own original reading — so when the blend goes wrong, contamination spreads to whichever anchor is reported next, not just the weaker side.

`_sequential_pair_closure_belief_trust_aware_reconstruct` — the match_class/`near_tie_basin_count`-aware pure-substitution mechanism (`_candidate_is_trustworthy`: untrustworthy if `match_class not in (None, "clean_full_pose")` or `near_tie_basin_count > 0`) — is exactly the "use the more-reliable anchor + known anchor-to-anchor geometry to recompute the uncertain one" mechanism, and it works correctly when invoked (confirmed: `ep187 anchor13` had 10/55 events go through it with clean pure-substitution results). **But it is only invoked when disagreement exceeds the "large" threshold** (`sequential_pair_closure_belief_large_position_disagreement_m=1.5`m / `..._heading_disagreement_deg=90.0`, both configurable). Below that (but above the separate, smaller 0.75m/30° threshold that gates entry into the fusion machinery at all — i.e. exactly the band where real corruption is occurring), everything falls through to the plain, match_class-blind blend.

**Direct empirical proof (`ep187 anchor13`'s real attempts, backend confirmed as `belief_fused` not `belief_trust_aware_reconstructed`):**

```
attempt=107  anchor10(clean_full_pose, quality=10.77)  vs  anchor13(ambiguous_high_confidence, quality=10.32)  -> weight 51%/49%
attempt=110  anchor10(clean_full_pose, quality=10.66)  vs  anchor13(ambiguous_high_confidence, quality=11.11)  -> weight 49%/51%
attempt=118  anchor10(clean_full_pose, quality=9.64)   vs  anchor13(ambiguous_high_confidence, quality=9.49)   -> weight 50%/50%
```

`ambiguous_high_confidence` means the ICP found multiple near-tied basins — but its `confidence`/`inlier_count` don't drop meaningfully vs. a clean match, so the blind quality score can't discriminate it from `clean_full_pose`, producing a near-coinflip blend between a good and a bad reading instead of the intended "trust the reliable side" substitution. This is the **same root cause for both failure signatures in §4**: moderate disagreements that should be substitution candidates keep landing in the blind blend, either corrupting an otherwise-good anchor (the "confidently wrong" signature) or failing to override a genuinely ambiguous one (the "self-reporting ambiguous" signature) — both are one bug, not two.

## 8. Pending: offline threshold sweep (launched 2026-07-08, **results not yet available as of this writing**)

Reusing the existing `offline_replay_guard.py` harness (no code changes to the live pipeline — `large_position_disagreement_m`/`large_heading_disagreement_deg` are already CLI-configurable), sweeping 6 points from `0.75m/30°` (= fully removed, since that equals the separate "normal" closure threshold below which the fusion branch is never reached at all) up to `1.5m/90°` (current default), across the 9 offline-replayable hard-11 episodes (`ep678` excluded — its `icp_replay_dataset/anchors.json` capture is corrupted beyond the repair patterns that worked for the live measurement JSONs). Goal: answer (1) whether the large-disagreement gate can simply be removed outright, and (2) if not, what value it should be lowered to. This document will be updated (or a follow-up entry added) once the sweep completes.

**Pending / next steps:**
1. Finish the threshold sweep; identify the best `large_position_disagreement_m`/`large_heading_disagreement_deg` (or confirm removing the gate entirely is safe).
2. Implement the winning configuration as the new default (or restructure so trust-aware evaluation runs for *any* disagreement that reaches the fusion branch, falling back to the blind blend only when `_candidate_is_trustworthy` can't discriminate — i.e. both or neither side looks clean).
3. Re-validate offline against the 15 bad (episode, anchor) groups identified in §4, then a fresh live hard-11 A/B.
4. The "confidently wrong" signature in §4 (clean `match_class`, high overlap, still wrong) is explicitly **not** addressed by this threshold change — `_candidate_is_trustworthy` has no signal to catch a single anchor that's wrong all on its own with no partner disagreement large enough to compare against. Still open, per the original bearing-reliability survey.
5. Consider lowering or reworking `ep5`-style `alias_stall_attempts` (currently 200) for routes flagged as uniformly self-similar on most/all anchors.
