# 2026-07-10 — Live A/B results for `sequential_pair_promotion_use_pre_closure_estimates`, and a decomposition of the residual next-behind rate

**Purpose of this document**: this is the follow-up to `investigations/2026-07-09-anchor-promotion-lag-and-icp-rotational-error/DATA.md`'s §H, which root-caused the "fine-but-stuck" next-behind bucket to the promotion gates reading closure-fused (not raw) ICP estimates, implemented `--sequential_pair_promotion_use_pre_closure_estimates`, and launched a live A/B (`promotion_use_raw_estimates_hard11_20260710_accumulated`, launched 2026-07-10T14:46) with the fix on. That batch finished at 2026-07-10T16:50:53 (exit=0, all 11 episodes attempted). This document analyzes those results: (1) whether the fix worked, (2) a full decomposition of what still causes the residual next-behind rate, and (3) a strict, manually-verified check of the one failure mode that would actually matter operationally — the shadow's "next" anchor going stale (robot physically passes it before promotion completes).

**Important scope note, confirmed directly against this batch's config**: `--route_hint_source=oracle` was active throughout, meaning the VLM navigated entirely off the oracle's privileged hint the whole time. Everything in this document — `relocalization_events`, `covisibility_records`, the promotion gates, all of it — is the **shadow** `sequential_pair` relocalizer's own belief, running in parallel purely for offline evaluation. None of the accuracy numbers below affected this batch's actual round-trip navigation; this is solely evaluating whether the shadow mechanism is accurate enough to eventually replace the oracle hint.

Ground truth throughout is derived from `oracle_route_current_s_m` (a privileged, per-step field in the trajectory JSONL, sampled at the same `relocalization_interval_updates` cadence as the shadow's own attempts) → `true_idx` = the anchor with the largest `distance_from_start_m` that is still ≤ that value, same rule as `investigations/2026-07-09-.../DATA.md`. **One data-quality caveat found and confirmed this session**: this field is not perfectly reliable — see §5.

---

## 1. Batch completion and data repair

11 episodes attempted (the fixed hard-11 set: 4, 5, 134, 187, 367, 368, 408, 678, 680, 994, 1040); master log confirms `all done` at 2026-07-10T16:50:53, exit=0.

**Usable (outbound success + return success + relocalization events present): 7 of 11** — `4, 134, 367, 368, 678, 994, 1040`.
**Not usable**: `187`, `408`, `680` (outbound failed — pre-existing VLM-startup-timeout / "robot stops moving" flakiness, unrelated to this fix, matching prior sessions' documented gaps); `5` (outbound succeeded, return failed this run).

**Two measurement JSONs hit the already-documented intermittent Isaac Sim write-corruption bug** (same class as `investigations/2026-07-09-.../DATA.md` §H.1's 3 signatures), both repaired via targeted regex and re-verified to parse cleanly:
- `ep5/measurements/8.json`: `"median_residual_m": : ,` → `"median_residual_m": null,` (duplicated-colon-missing-value signature). **ep5 still ended up excluded from the usable set** — the repair succeeded, but `return_success=False` in this run regardless (a separate, unrelated flakiness event, not caused by the corruption or the fix).
- `ep1040/measurements/1760.json`: two separate corruption instances — a duplicated-and-glued string value (`"...anchor""...anchor""shadow_source":` → `"...anchor", "shadow_source":`) and an orphaned `: value` pair with a dropped key name (`"shadow_progress": {\n\n: "anchor_relocalization",` → inserted a placeholder key). ep1040 parsed clean after both fixes and is included in all numbers below.

The direct 2026-07-07-baseline-overlap episode set available this run is `{4, 368, 678, 994, 1040}` (5 of the baseline's 8: `5, 187, 680` are missing this run for the flakiness reasons above, not because of the fix).

---

## 2. Did the fix work? Current- and next-anchor accuracy vs. the 2026-07-07 baseline

**Current-anchor accuracy, per-episode, restricted to the 5 directly-overlapping episodes:**

| ep | baseline exact% | this run exact% | Δexact | baseline overshoot% | this run overshoot% | Δovershoot |
|---|---|---|---|---|---|---|
| 4 | 45.9 | 62.6 | **+16.7** | 48.4 | 24.4 | **−24.0** |
| 368 | 67.7 | 73.2 | +5.5 | 27.8 | 19.1 | −8.7 |
| 678 | 48.7 | 72.6 | **+23.9** | 38.7 | 11.1 | **−27.6** |
| 994 | 80.1 | 69.6 | **−10.5** | 3.6 | 4.3 | +0.7 |
| 1040 | 54.2 | 55.9 | +1.7 | 33.6 | 20.3 | −13.3 |
| **simple avg (5 eps)** | **59.3** | **66.8** | **+7.5** | **30.4** | **15.8** | **−14.6** |

ep678 — the episode `investigations/2026-07-09-.../DATA.md` §H.4 specifically named as the concentration point of the un-fixed gate bug (55.7%-of-88 unexplained cases, "concentrated almost entirely in ep678/ep680") — shows the single largest improvement, matching the prediction. ep4 also improved sharply. **ep994 is the one episode that got worse** (exact −10.5pp); see §4 for why (a genuine, this-run-specific ICP degeneracy cluster, not a fix regression).

**Full-batch pooled (7 episodes, n=2282 current-anchor attempts):** exact 65.3%, lag-1 15.6%, lag-2+ 0.5%, overshoot 18.6% (max magnitude 2, never 3+, confirming the "advance ≤1 anchor" structural guarantee held) — vs. baseline pooled (8 episodes, n=2788): exact 55.9%, lag-1 13.8%, lag-2+ 9.0%, overshoot 21.3%.

**Next-anchor accuracy, pooled (n=2191, 7 episodes):** exact 65.5%, +1 14.6%, +2 1.6%, +3+ 0.0%, **behind 18.3%** — vs. baseline pooled (n=2689): exact 56.4%, +1 17.7%, +2 0.7%, +3+ 0.0%, behind 25.1%. (This 25.1%→18.3% comparison is confounded by the different episode set — ep5, which had an 80.3% next-behind stall in the baseline, isn't in this run's denominator at all — so the improvement is real in direction but the magnitude of this particular delta should not be trusted at face value.)

**Verdict on H.6's three checks:**
1. Overshoot must not increase — ✅ it dropped substantially (30.4%→15.8% avg over the 5 overlap episodes), bounded magnitude confirmed unchanged.
2. Next-behind should drop, concentrated in ep678/ep680 — ✅ direction confirmed, ep680 unavailable this run to check directly, ep678 confirmed.
3. ep678/ep680 show the largest improvement — ✅ for ep678 (largest exact-% gain and largest overshoot-% drop of all 5 overlap episodes); ep680 unverifiable this run.

---

## 3. Gate-level decomposition of the residual next-behind rate

**Methodology correction made mid-session, recorded here so it isn't repeated**: an initial reconstruction of `_promotion_trend_improving` used an over-lenient formula (any 3-of-4 consecutive non-increasing samples). Reading the actual code (`route_memory_agent.py:964-972`) found the real check is stricter: given `self.promotion_window=4`, `self.promotion_min_improving_samples=3`, take the last 3 raw distance samples for a candidate; require **both** (a) the last sample is at least 0.05m below the first-of-3 (net shrink, not just non-increase) and (b) every consecutive pair non-increasing within a 0.05m margin. Using the lenient version overstated the "gates already passed but didn't promote" bucket at 43.8% of all behind attempts; the corrected version drops that to 17.1%, and a look-ahead check (does `reported_current_idx` actually change within the next 1-5 attempts) resolves all but 0.54% of that as ordinary vote-window timing, not a bug. **Conclusion: the H.4 gate-vs-fusion bug this session's fix targeted is resolved to a residual of ≈0.5% of behind attempts** (down from the pre-fix estimate of ~55.7% of 88 cases, ≈1.8% of all attempts, concentrated in ep678/ep680).

Reconstructed directly from `route_memory_agent.py` (line refs current as of this session): `_select_sequential_pair_relocalization` (:1094), `_relocalization_quality` (:950, `confidence * sqrt(max(1, inlier_count))`), `_record_promotion_sample`/`_promotion_trend_improving` (:953-972), `_record_promotion_vote`/`_promotion_requirement_for_anchor` (:974-1061, bounded_evidence window=5/min_votes=3 by default, alias-aware stricter window=8/min_votes=5 not modeled here since `alias_score` isn't serialized in this batch's measurement JSON — same gap noted in `investigations/2026-07-09-.../DATA.md` §G).

**Per-attempt classification of all 368 "current-lag≥1" (behind) attempts, pooled across the 7 usable episodes:**

| gate reason | n | % | verdict |
|---|---|---|---|
| `close_enough` and `trend_ok` both fail | 153 | 41.6% | design-intended caution |
| `bounded_evidence` votes not yet accumulated (3-of-5) | 69 | 18.8% | design-intended caution |
| `quality_ok` fails (next's quality < 0.85× current's) | 69 | 18.8% | real ICP-quality problem (§4) |
| next candidate produced no ICP estimate at all this attempt | 14 | 3.8% | see §4.3 |
| gates already passed, still not promoted, resolves within 1-3 attempts | 61 | 16.6% | vote-window timing artifact of this per-attempt snapshot method, not a real delay |
| gates already passed, still not promoted, 4+ attempts / episode end | 2 | 0.54% | genuinely unexplained (both ep134) |

---

## 4. Two structurally different populations behind the 18.3% next-behind rate

Per-attempt row counts (above) are a poor way to compare "how much of a problem is this" across categories, because a single long-duration stuck anchor generates many more attempt-rows than a short one. Re-grouped by **candidacy span** — one contiguous run of attempts where a given anchor sits as "next" before either being promoted or the episode ending (89 spans total across the 7 episodes) — the picture is different and more informative:

| span category | n spans | % of all spans | median attempts/span | median real distance traveled/span | robot physically passes the anchor before promotion | never promotes within the episode |
|---|---|---|---|---|---|---|
| gate-delay-dominant (close_and_trend_fail / votes_not_enough) | 36 | 40.4% | 19 | **0.70m** | **0%** (0/36) | 0% |
| ICP-degeneracy-dominant (quality_fail) | 45 | 50.6% | 31 | **1.06m** | see §5 (initially reported 4.4%, corrected to 1/45 = 2.2% real) | 6.7% (3/45) |
| other/mixed | 8 | 9.0% | 7 | 0.25m | 0% | 0% |

### 4.1 Gate-delay spans: slow, but never lets the anchor go stale

Across all 36 design-intended-delay spans, the robot's true position never dropped past the anchor being waited on before promotion completed (0/36). This is the correct interpretation of "lag" for this category: real elapsed distance (median 0.70m, up to 1.53m worst case) but zero cases of the tracked "next" anchor becoming stale. **This category should not be read as a next-anchor-accuracy problem** — it is `bounded_evidence`'s designed confirmation delay working exactly as intended, structurally analogous to how `lag-1` is already treated as "normal" in the current-anchor metric.

### 4.2 ICP-degeneracy spans: bigger, slower, and spread across every episode — not just ep994

A raw per-attempt count of the `quality_fail` bucket (69 attempts) is 65% concentrated in ep994, which is misleading in the same way row-counting misleads elsewhere: at the **span** level, ICP-degeneracy-dominant spans appear in **all 7 usable episodes**, not just ep994:

| episode | # degenerate spans | anchors affected |
|---|---|---|
| ep4 | 5 | 1, 2, 3, 8, 9 |
| ep134 | 9 | 1, 3, 5, 7, 9, 10, 12, 13, 14 |
| ep367 | 7 | 1, 2, 3, 5, 7, 8, 9 |
| ep368 | 6 | 1, 2, 3, 5, 7, 8 |
| ep678 | 5 | 3, 4, 5, 11, 13 |
| ep994 | 9 | 3, 4, 5, 7, 8, 12, 13, 14, 15 |
| ep1040 | 4 | 2, 3, 7, 8 |

**These cluster along consecutive stretches of the route rather than isolated single anchors**: checking the gap between consecutive affected anchor indices within each episode, a majority of gaps are exactly 1 (adjacent anchor) in most episodes — e.g. ep994: 6/8 gaps = 1; ep367: 4/6 gaps = 1; ep4: 3/4 gaps = 1. Typical pattern is 3-5 consecutive anchors along one stretch of a route showing degenerate ICP, not a single unlucky anchor surrounded by clean ones.

**ep994's specific regression (§2) traced to one such cluster**: anchor4's candidacy span (attempts 293-369, 77 attempts, 2.06m of travel) shows next's `estimated_distance_to_anchor_m` oscillating between ~0.3m and ~3m attempt-to-attempt, with `match_class` flipping between `clean_full_pose`/`ambiguous_high_confidence`/`partial_pose_degenerate` — a real ICP multi-basin-instability signature (same class as this project's long-standing `corridor_or_sparse`/"confidently wrong" findings), not a promotion-logic bug. Compounding this: `current`'s own confidence stayed pinned at 0.8-1.0 throughout (the already-documented confidence-saturation problem — `confidence*sqrt(inlier_count)` doesn't discriminate a genuinely-good current from a falsely-confident one), making the `quality_ok` gate's 0.85× threshold *relative to current* harder to clear even when next's raw match is real evidence of improvement.

### 4.3 The 14 "no ICP estimate at all" attempts (ep4 only)

29 attempts in ep4 had only a single `covisibility_record` instead of the expected two (current-only, no next candidate produced any pose estimate that attempt) — concentrated near the route's tail-end anchors (anchor1, close to the return-start). This falls through to "retain current" by design (safe default, not a bug), but is worth a small follow-up: currently these attempts leave no record at all of *why* next's ICP produced nothing (insufficient points? total match failure?) — see §6 recommendation 3.

---

## 5. Strict recheck: how often does the robot physically pass the "next" anchor before it's promoted?

This is the only failure mode that would actually matter operationally (per user framing: if the robot is heading toward anchor 12 while `current=14`/`next=13`, both are stale and any navigation relying on the shadow would be actively wrong). Defined strictly as: `true_idx < next_idx` (ground truth has already dropped below the anchor still waiting to be promoted) while `reported_current_idx != next_idx` (not yet promoted).

**First pass across all 2191 next-candidate attempts found 11 attempts / 2 distinct events** (ep134 next_idx=3, ep994 next_idx=3) meeting this condition. **Manual, attempt-by-attempt verification against raw trajectory data found only 1 of these 2 is real:**

- **ep134, attempts 275-280 — a data artifact, not a real overtake.** `oracle_route_current_s_m` jumped from 5.553→1.157 (attempt 274→275) and back to 5.232 (attempt 280→281), with `target_anchor_index` (a different, oracle-hint-side field in the same trajectory record) simultaneously flipping 4→0→4. Cross-checked against the robot's actual `position` and `distance_to_start_m` for the same steps: real position moved by a total of ~0.4m (`distance_to_start_m` 0.858→1.170, smooth and monotonic) — nowhere near the ~4.4m implied by the `oracle_route_current_s_m` swing. **This is a transient computation glitch in the oracle route-projection field itself** (plausibly a `stop_gate`-adjacent or path-self-intersection artifact — the exact trigger wasn't tracked further), not a real robot position change. A full scan of all 7 episodes for any other |Δs_m| > 1.0m between consecutive attempts found **zero other instances** — this is an isolated, one-off data-quality issue in this one batch/episode, not a systemic ground-truth reliability problem.
- **ep994, attempts 391-395 — real.** `oracle_route_current_s_m` decreased smoothly (3.079→2.783 across 5 attempts) and legitimately crossed anchor3's boundary (3.01m), confirmed against the same episode's `position`/`distance_to_start_m` moving smoothly and consistently in the same direction. `current` (anchor4) and `next` (anchor3) were both genuinely stale relative to the true position (which had reached anchor2's neighborhood) for these 5 attempts (~0.22m of extra travel) before promotion completed at attempt 396.

**Corrected result: exactly 1 genuine "next-anchor overtaken" event in this entire 7-episode batch — 0.05% of all 2191 next-candidate attempts, 1.1% of the 89 candidacy spans — lasting 5 attempts / ~0.22m before self-resolving.** The 4.4% figure reported earlier in this session's live discussion (2/45 ICP-degeneracy spans) should be treated as superseded by this stricter, manually-verified count; roughly half of that earlier figure was itself a downstream artifact of a ground-truth glitch, not a real tracking failure.

---

## 6. Recommendations

1. **Do not touch the promotion-gate math to address the residual next-behind rate.** §3-4 show ~77% of it (close_and_trend_fail + votes_not_enough + timing-artifact-resolved-quickly) is the design working as intended, and §5 confirms the one failure mode that would actually matter (real anchor overtaking) is a 0.05%/attempt, 1.1%/span, self-resolving-within-0.22m occurrence — there is no evidence the gate thresholds themselves need to change.
2. **The ICP-degeneracy problem (§4.2, ~50.6% of candidacy spans, present in every episode, clustered along consecutive anchor stretches) is the one worth new investigation**, but it is an ICP-accuracy problem, not a promotion-logic problem: consider (a) a `quality_ok` exception path that reads `match_class`/`icp_near_tie_basin_count` directly (mirroring what `trust_aware_guard` already does for closure-fusion) instead of relying solely on the confidence-based quality ratio, which is known to saturate for a falsely-confident `current`; (b) instrumenting whether these consecutive-anchor clusters correlate with `corridor_degeneracy_ratio` or scene structure (doorways, repeated hallway segments) to see if they're predictable in advance rather than only detectable per-attempt.
3. **Log an explicit `outcome=no_estimate` covisibility record** when ICP produces literally no candidate for a role (§4.3, 14 attempts, all ep4) instead of silently omitting the record — cheap, and removes an analysis blind spot.
4. **ep134's `oracle_route_current_s_m` glitch (§5) is worth a five-minute look** if anyone is touching the oracle route-projection code — isolated and harmless here (didn't affect any real decision, since this batch used `route_hint_source=oracle` directly, not the shadow), but would corrupt ground-truth grading in any future analysis that reuses this field without knowing about it.
5. **ep994's regression (§2) does not need a fix** — it's explained entirely by §4.2's ICP-degeneracy cluster landing on different anchors this run than in the baseline run (run-to-run scene/seed variation), not a consequence of today's promotion fix.

## Methodology notes / reproducibility

- Ground truth: `oracle_route_current_s_m` from the trajectory JSONL's per-step `route_memory` field (return-phase rows only), sampled at `row_index = 0 if attempt==1 else (attempt-1)*relocalization_interval_updates - 1` into the return-phase-filtered row list, same approximation formula validated in `investigations/2026-07-09-.../DATA.md` §H.1 (n=2788 replay reproduced the live batch's own n exactly).
- `next_idx` per attempt derived from `route_relocalization_diagnostics.covisibility_records` (2 records/attempt = current+next candidate; whichever anchor_index doesn't match the previous attempt's accepted `target_anchor_index` is "next").
- Promotion gate constants used: `promotion_close_radius_m=0.75`, `promotion_score_ratio=0.85`, `promotion_window=4`, `promotion_min_improving_samples=3`, `sequential_pair_promotion_window=5`, `sequential_pair_promotion_min_votes=3` — all read directly from `route_memory_agent.py` defaults, confirmed matching this batch's logged config.
- Known unmodeled gap (inherited from `investigations/2026-07-09-.../DATA.md` §G): `alias_score` per anchor isn't serialized in measurement JSON, so the alias-aware stricter 5-of-8 vote requirement couldn't be distinguished from the flat 3-of-5 default in §3's gate reconstruction.
