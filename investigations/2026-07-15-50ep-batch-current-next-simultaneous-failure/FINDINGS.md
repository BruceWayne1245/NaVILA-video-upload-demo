# 2026-07-15 — Analysis of the 50-episode two-batch shadow-vs-no-hint validation launched 2026-07-14; the residual return-failures traced to a current+next simultaneous-breakdown mechanism that existing promotion/quarantine logic structurally cannot catch; two static route-difficulty predictors tested and both falsified; handoff document for researching a replacement current/next matching primitive

**Context**: `investigations/2026-07-14-shadow-hint-analysis-and-vector-to-start-fix/PROGRESS.md` launched a 50-episode two-batch live validation (Batch 1: `shadow_hint_swap_50ep_20260714_accumulated`, the post-dtheta-fix Variant-1 shadow config; Batch 2: `no_hint_50ep_20260714`, the pure-VLM no-hint baseline) at 2026-07-14T12:42:59+01:00, on the hard-11 set plus 39 newly-sampled episodes. Both batches finished by 2026-07-15T04:09:11+01:00. This document analyzes those results and the residual return-failures in the shadow batch, using only raw ground-truth trajectory data (`position`/`yaw_rad` from the trajectory JSONL, which is Isaac Sim's privileged simulator state, never derived from any relocalization output) and raw per-attempt ICP records (`route_relocalization_diagnostics.covisibility_records`), per this project's established methodology of never trusting the smoothed/self-reported fields alone.

## Part 0 — headline batch results

Outbound-success episodes: 22/49 valid attempts in the shadow batch (`ep680` timed out with no data), 17/48 in the no-hint batch (`ep640`/`ep347` timed out). Conditioning on outbound success (the fair comparison, since hints only affect the return phase):

- **Shadow (post-dtheta-fix): 14/21 = 66.7% round-trip success.**
- **No-hint baseline: 7/17 = 41.2% round-trip success.**

Shadow is clearly and substantially better than no-hint at this much larger n (vs. the 8-episode 62.5%/44.4% comparison in the prior investigation), and this is the first same-day, same-50-episode-set, matched comparison between the two conditions. However, this is still well below the historical oracle-driven hard-11 ceiling (~87.5%), and 8/22 outbound-success episodes still failed return. The rest of this document is a forensic analysis of those 8: `134, 367, 994, 319, 708, 498, 354, 214`.

## Part 1 — the dtheta-chaining fix (2026-07-14) is confirmed still holding

Spot-checked `relative_start_progress` in multiple episodes' measurement JSON: `target_dx_m`/`target_dy_m` exactly equal `anchor_dx_m`/`anchor_dy_m` in every case checked. The fix is live and working as designed; none of what follows is a recurrence of the dtheta-composition bug.

## Part 2 — two distinct terminal failure modes among the 8

- **"Spin forever, episode times out without ever stopping"**: `134, 367, 708, 354, 214`. Return-phase command mix in these episodes is dominated by pure-yaw (`command=[0,0,±0.52]`, zero linear velocity) for very long stretches (up to 3249 consecutive records in `ep367`) — a VLM decision loop, not a physical obstruction (the robot accelerates completely normally the instant `command` switches to forward).
- **"VLM self-initiates a stop far from goal"**: `994, 319, 498`. In `994` and `498`, the *last* hint text shown to the VLM before it stopped was the degraded qualitative fallback — `"[System Hint: position uncertain (σ≈4.2m, filter lost lock); ... do NOT stop until you visually confirm you are back at the starting location.]"` — and the VLM stopped anyway, 11.34m and 8.65m from the true start respectively (success radius 3.0m). This is the VLM disregarding an explicit, correctly-issued "keep going" instruction, not a hint-content bug. `319` is a partial exception: its last hint locked onto a nearby-but-wrong anchor claiming "1.58m remaining" while the true distance to start was 6.94m — a confidently-wrong anchor identity at the very end, which would legitimately justify the VLM's decision to stop from the text it was actually given.

## Part 3 — bearing accuracy cleanly discriminates success from failure, and it is not about scene novelty

Computed ground-truth bearing error (`bearing_to_anchor_deg` vs. true bearing from true `position`/`yaw_rad` to the true `target_anchor_index`'s recorded `world_pose`) for all 22 outbound-success episodes:

| | mean of per-episode medians | mean per-episode frac>10° | mean per-episode frac>45° |
|---|---:|---:|---:|
| 14 SUCCESS episodes | 4.84° | 28.2% | 15.6% |
| 8 FAIL episodes | 55.18° | 71.7% | 55.3% |

Splitting by old (hard-11, previously calibrated many times) vs. new (39 never-before-tested-under-shadow episodes): OLD-success mean median 3.95° vs. OLD-fail 64.99°; NEW-success 5.51° vs. NEW-fail 49.30°. **Old and new scenes show the same success/fail split in bearing accuracy** — scene novelty does not explain the failures; 3 of the 8 failures (`134, 367, 994`) are hard-11 episodes previously validated as accurate under this exact pipeline.

## Part 4 — ruled out: "robot physically drifted off the known route into unmapped territory"

Initial within-episode quartile analysis (bearing error split into 4 chronological quarters of the return phase) showed most failures start accurate and then break down partway through and never recover (e.g. `ep134`: 1.8°→63.7°→63.6°→63.6°; `ep367`: 18.7°→122.0°→132.6°→171.3°). This looked consistent with a closed-loop drift story (bad hint → robot leaves the recorded path → ICP has to match genuinely novel, poorly-covered viewpoints → worse hints → more drift), which has real precedent in this project (`ep367`'s 2026-07-13 failure was root-caused exactly this way against its own oracle-driven counterpart).

**Directly checked against `nearest_reference_path.distance_m`/`nearest_return_path.distance_m` (logged every trajectory step, computed from true position against the recorded route, independent of any relocalization output) and this hypothesis does not hold for most of the batch.** In 4 of 5 breakdown episodes checked in detail (`134, 367, 994, 708`), this distance stays bounded at roughly 1-2m (the same order as the anchors' own ~1m spacing) throughout the entire episode, including deep into the "bearing error breakdown" period — the robot never leaves the known route. Only `ep498` shows a real, growing physical departure from the route later in the episode (up to 6.7m), and even that is plausibly a downstream *consequence* of earlier bad hints rather than the initiating cause.

Direct step-by-step inspection of a breakdown transition (`ep134`, steps 2916-2935) shows the true position essentially frozen (`ref_path_distance` 0.372m→0.356m) while the *same target anchor*'s reported bearing swings 4.6°→13.4°→2.2°→0.0°→47.7°→1.2° within a handful of steps. **This is per-attempt ICP instability at a fixed real-world location, not the robot being led somewhere new.**

## Part 5 — the huge whole-episode error medians are not evenly distributed; they are concentrated because the system dwells on 1-3 bad anchors for a hugely disproportionate share of all readings

Per-anchor breakdown of bearing error and reading-count share (out of the full route's anchor set):

| Episode | dominant bad anchor(s) | share of ALL return-phase readings | anchor's own median error |
|---|---|---:|---:|
| 134 (17 anchors) | anchor 7 alone | 57.5% | 63.6° |
| 367 (13 anchors) | anchors 5+7+8 | 73.3% | 124-166° |
| 214 (12 anchors) | anchors 1+5+3 | 72.8% | 133-172° |
| 498 (11 anchors) | anchor 5 | 36.1% | 68.3° |
| 319 (6 anchors) | anchor 5 | 48.2% | 70.8° |

If the shadow visited all ~6-17 anchors on a route roughly evenly, 1-3 bad anchors would contribute at most ~15-25% of readings — enough to drag the mean/tail but not the median. **Instead the system gets stuck dwelling on exactly these 1-3 anchors for 30-73% of the entire return phase**, which is why the whole-episode *median* (not just the mean) ends up catastrophic.

## Part 6 (code-confirmed) — why the dwelling happens: two independently-correct mechanisms have an uncovered gap between them

**Promotion (`_record_promotion_vote`, `route_memory_agent.py:1042`) is an unconditional sliding window with no escalation path other than a bar-relaxation.** It appends a pass/fail vote every attempt, keeps only the last `window` (5 normal / 8 if alias-aware), and checks for `min_votes` (3 / 5) passes — re-evaluated forever, every attempt, with **no logic to take any alternative action if the quota is never met**. The only release valve, `sequential_pair_promotion_alias_stall_attempts=200` (`_promotion_requirement_for_anchor`, line 1082), *loosens the bar* to the flat 5-window/3-vote requirement after 200 total votes on the same candidate — it does not skip, blacklist, or otherwise act on the candidate; it only makes promotion easier.

**Quarantine (`_record_next_anchor_trend`/`_record_next_anchor_stability`, lines 914-1016) explicitly, by design, never monitors the anchor currently in the "current" role.** Both modes contain the identical guard `if idx == current_idx (or self._target_anchor_index): continue`, and the "trend" mode's own docstring states this outright: *"Deliberately does NOT track the anchor currently in the 'current' role... quality degradation only after promotion is a separate, out-of-scope problem."* Once an anchor is promoted — whether cleanly or via the 200-attempt bar relaxation — nothing in the codebase can flag, replace, or route around it based on its own ongoing quality.

**Directly verified (ground-truth-checked) that when the system is stuck, BOTH the current anchor and its adjacent next candidate are simultaneously bad — not "current alone degraded while next was fine and just slow":**

| Episode | current anchor raw ICP bearing error (median) | adjacent next anchor raw ICP bearing error (median) |
|---|---:|---:|
| 134 | anchor7: 63.6° | anchor6: **125.1° (worse than current)** |
| 367 | anchor5: 160.9° | anchor4: 169.0° |
| 367 | anchor7: 86.2° | anchor6: 120.1° |
| 367 | anchor8: 83.8° | anchor7: 98.4° |
| 214 | anchor5: 167.4° | anchor4: 160.2° |

This closes the causal chain: a bad current anchor cannot be quarantined (quarantine doesn't watch current), and its would-be replacement (next) is *also* bad in these cases, so bounded-evidence promotion cannot accumulate a clean vote majority either — nobody is at fault individually, but the two correct-by-design mechanisms leave exactly this pincer scenario uncovered.

## Part 7 — two candidate static predictors for "why do these specific anchors go bad" were tested and both falsified/weakened

**Falsified: ICP's own self-reported `alias_score` (precomputed anchor-vs-anchor point-cloud similarity, threshold 0.6 for stricter promotion requirements) does not discriminate success from failure.** Success episodes actually show *equal or higher* alias-score pervasiveness than failures: mean fraction of anchors ≥0.6 is 93.0% (success) vs. 80.5% (fail); mean longest same-route-consecutive-high-alias run is 83.4% (success) vs. 74.8% (fail). Concretely, `ep1040` (round-trip **success**) has alias-score median 1.04 / max 1.42 across its route — higher than `ep134`'s (round-trip **failure**) median 0.88 / max 1.39. Several fully-successful episodes (`4, 5, 368, 408, 1040, 89, 647, 1038, 430`) have **100% of their non-start anchors** flagged ≥0.6, the same as the worst failures. At this threshold, on this dataset, `alias_score` is close to a constant, not an informative route-difficulty signal — a real negative result, not merely "not yet tuned."

**Weakened/mixed: a purely ground-truth-derived signal (turn angle between consecutive anchors' true recorded `world_pose` positions — completely independent of any ICP output) was tested as an alternative, non-circular route-geometry check.** 4 of 7 problem-anchor cases (`134, 354, 708, 214`) sit on genuinely low-turn-angle (near-straight, <15°) stretches — a real, independently-verifiable "featureless corridor" signature. But 2 cases (`367`: 41-49° turn angles; `498`: 63.7°) are directly *at* sharp turns, not straight stretches, contradicting the theory; and two fully-successful episodes (`ep4`, `ep5`) are equally straight (75-80% of their anchors <10° turn angle) without any breakdown. This metric is a partial, not clean, predictor.

**Net conclusion of Part 7: neither tested static, precomputable route-level feature reliably predicts which specific run of which episode will suffer this breakdown.** The mechanism in Part 6 (both roles going bad together, uncaught by design) is solidly confirmed; *why* it selectively happens on some runs of some episodes and not others (including runs of the identical episode ID under otherwise-identical config) remains open, and may be substantially driven by closed-loop run-to-run stochasticity (the exact viewing angles/positions a VLM-driven trajectory happens to take) rather than a static, precomputable property — this is inherently harder to fix via precompute-and-avoid than a static predictor would have been.

## Part 8 — data-driven attempt to size a proposed "next"-role dwell-time quarantine window; result is an honest non-clean-separation finding

Per user proposal: harden the **quarantine gate on the "next" role specifically** (not current, which Part 6 already explains is out of scope for existing quarantine and structurally hard to fix the same way) — if a "next" candidate fails to accumulate the required promotion vote quota within a fixed window of attempts (counted from when it first became eligible as "next", not the existing unbounded sliding re-evaluation), blacklist it outright (skip to the next-next candidate via the existing `_next_candidate_index` skip-ahead logic) rather than continuing to wait indefinitely or merely relaxing the bar at 200 attempts.

Reconstructed the full promotion-wait-time distribution from `relocalization_events` (index+1 == attempt number, by construction) across all 22 outbound-success episodes, separating legitimate/normal promotions from the known-bad "stuck" anchors identified in Part 5-6 (including anchors that never promoted again before the episode ended, i.e. permanently stuck — a lower-bound/censored wait time):

| | n | min | p25 | median | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| Normal/legit promotions (success + fail episodes) | 199 | — | — | 25 | 41 | 68 | **446** |
| Known-bad "stuck" anchor dwells (incl. censored-forever) | 24 | — | — | 56 | 124 | 201 | 364 |

**A pure elapsed-attempt-count window does not cleanly separate these two populations — the distributions substantially overlap.** False-positive rate (legitimate anchors incorrectly blacklisted) vs. true-positive rate (known-bad anchors correctly blacklisted) at various window sizes N:

| N | FP rate (legit anchors wrongly blacklisted) | TP rate (bad anchors caught) |
|---:|---:|---:|
| 25 | 48.7% | 62.5% |
| 50 | 22.1% | 50.0% |
| 60 | 16.6% | 45.8% |
| 80 | 11.1% | 37.5% |
| 100 | 7.5% | 33.3% |
| 150 | 4.5% | 25.0% |
| 200 | 1.5% | 16.7% |

There is no window size that is both low-false-positive and high-true-positive; a legitimate anchor in a fully-successful episode was observed taking as many as 446 attempts to promote, while several bad/stuck anchors promoted (or got permanently stuck) in well under 50. **Recommendation, with the caveat that this alone will leave real residual failures either way**: N=60-80 is a defensible middle ground (catches roughly 38-46% of known-bad cases at an 11-17% false-positive cost to legitimate slow-but-fine anchors) if a single elapsed-count threshold must be chosen. **Stronger recommendation**: don't gate on raw elapsed-attempt-count at all — gate on the *cumulative pass-fraction of the vote history over the candidate's entire "next" dwell* (mirroring exactly how this project's own quarantine mechanism evolved from a fragile fixed-window raw-spread check ("window" mode, 2026-07-04) to a whole-history fraction-based check ("trend" mode, 2026-07-05) after finding the raw-window version was mostly false positives) — this is very likely to separate the two populations better than total elapsed time alone, since it directly measures vote *quality* rather than vote *count*, but has not yet been tested against this data and should be validated before implementation, not assumed.

## Part 9 — handoff scope for researching a replacement current/next matching primitive

Per explicit user instruction, the following investigation is **only** about replacing the point-cloud-capture-to-match algorithm that computes `(anchor_dx_m, anchor_dy_m, anchor_dtheta_rad, confidence, match_class, ...)` for a given `(saved anchor descriptor, live local-map scan)` pair — i.e. `relocalization.py`'s `sequential_pair_anchor_relocalization` / `icp_rigid_transform_2d` and whatever precedes it (voxel downsampling, local-map extraction from LiDAR). **The `sequential_pair` framework itself (dual current+next anchor tracking, promotion/quarantine/closure-check control flow in `route_memory_agent.py`) is explicitly out of scope and should be preserved as-is.**

Relevant prior context already in this project, for whoever picks this up:
- A 2026-07-01 literature survey (`README.md`, "Latest update 2026-07-01 — literature survey...") already identified candidate directions for this exact problem class (corridor/repetitive-geometry degeneracy in low-density ~500pt/scan LiDAR matching): degeneracy-aware registration (X-ICP, arXiv 2211.16335; SuperLoc, arXiv 2412.02901, reports 54% accuracy gain in corridors specifically via a Fisher-information localizability score as a pre-match gate), and descriptor-based place recognition as an alternative to raw ICP (Scan Context/SC++, Kim & Kim IROS 2018; BEVPlace, arXiv 2302.14325; OverlapTransformer, arXiv 2203.03397).
- **Already tried and found wanting**: a Scan Context backend was implemented 2026-07-02 and found to underperform the LiDAR/ICP-based approach on anchor-selection accuracy at the time (see `README.md` 2026-07-02 entries). A rear-facing-camera LoFTR (RGB feature-matching) backend was investigated in depth through 2026-07-13 specifically as a potential *rotation* (dtheta) source — it won 93.8% of head-to-head rotation-accuracy comparisons against ICP, but its own *translation*-derived bearing was **worse** than ICP's (beats ICP only 12.6% of the time), and closing out that investigation explicitly concluded LoFTR-rear has "no remaining practical role in the current architecture" once fusion was removed. **Any new proposal should explain concretely why it would succeed where these two prior attempts did not**, rather than re-proposing the same directions from scratch.
- The localizability/eigenvalue data (`covisibility_records[].localizability`) and multi-basin yaw-curve data (`icp_top_basins`, `yaw_curve`) are already computed and logged on every attempt in this codebase (added across the 2026-07-05/07 sessions) — a real, already-available signal describing *why* a given ICP match is or isn't well-constrained, not yet exploited by any accept/reject/reweighting logic. Worth checking whether this existing signal (rather than a wholesale algorithm replacement) already contains enough information to solve the current/next simultaneous-failure problem before evaluating a new matching primitive from scratch.
- Point-cloud density is genuinely low (~250-2800 points/scan depending on voxel settings; current default 512 max points at 0.10m voxel) — any proposed replacement must be evaluated at this density, not at the higher densities (thousands to tens of thousands of points) typical of outdoor/automotive LiDAR SLAM literature.

## Summary of what's now confirmed true, and what remains open

**Confirmed (ground-truth or code verified):**
1. The 2026-07-14 dtheta-chaining fix is holding correctly; it is not the cause of any of this batch's residual failures.
2. Shadow-driven navigation (post-fix) meaningfully beats the no-hint baseline at n=50 scale (66.7% vs. 41.2% conditional round-trip success).
3. The 8 residual failures are dominated (in reading-count terms) by 1-3 anchors per episode where the shadow gets stuck dwelling far past a "fair share" of the route.
4. The robot does not physically leave the known/recorded route during these breakdowns (ruling out a drift-into-unmapped-territory story) in 4/5 episodes checked in detail.
5. Both the current anchor and its adjacent next candidate are simultaneously producing bad ground-truth-checked readings during these stalls — not a one-sided degradation.
6. By design, quarantine never monitors the "current" role, and promotion has no time-boxed escalation besides a bar-relaxation at 200 attempts — this exact combination structurally cannot resolve a simultaneous-bad-pair.

**Open / falsified / unresolved:**
1. `alias_score` does not predict which episodes will fail (falsified this session).
2. Ground-truth corridor turn-angle only partially predicts it (2/7 counter-examples, plus 2 successful counter-examples).
3. No window-size threshold on raw promotion-attempt-count cleanly separates legitimate slow anchors from genuinely bad ones (this session's Part 8 finding) — a quality-fraction-based gate (not yet tested) is the recommended next thing to try before concluding quarantine-hardening is a dead end.
4. Why specific runs of specific episodes (rather than others, including repeat runs of the same episode ID) hit this failure mode is unresolved — plausibly closed-loop run-to-run stochasticity rather than a static, precomputable property.
