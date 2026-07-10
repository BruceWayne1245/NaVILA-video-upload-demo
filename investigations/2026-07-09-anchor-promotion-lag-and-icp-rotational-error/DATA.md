# 2026-07-09 — Full data appendix: every table produced during this session's `sequential_pair` anchor-selection / ICP-accuracy analysis

This is a raw-data companion to `FINDINGS.md` in this same folder. `FINDINGS.md` is the curated narrative (background + the two problems framed for literature search); this file dumps **every table generated during the session**, including ones not quoted in `FINDINGS.md`, so nothing analyzed today is lost. Methodology (ground-truth definitions, role/attempt alignment, etc.) is explained in `FINDINGS.md` §1–§2.1 and is not repeated here except where a table needs its own specific caveat.

Two datasets are used throughout:
- **Live batch** = `hard11_live_trust_aware_guard_20260707_accumulated` (real Isaac Sim run, 8 usable episodes: 4, 5, 187, 368, 678, 680, 994, 1040; anchor geometry source = `accumulated`, i.e. odometry-derived).
- **Offline replay** = ICP re-run against captured point clouds from `icp_replay_capture_hard11_20260706_accumulated`, using the same core config (`bounded_evidence` promotion + `alias_aware` + `belief`-mode closure + `trust_aware_guard`), but with `sequential_pair_anchor_geometry_source=oracle` (privileged anchor-to-anchor geometry, since the outbound odometry accumulator state isn't part of the capture) and no physics/sensor noise. **This is a real configuration difference from the live batch, not just "offline vs online" — keep it in mind when comparing numbers between the two.**

---

## A. Live batch — Task 1(a): anchor-selection accuracy (n=2788 attempts, 8 episodes)

**Current:**

| exact | lag-1 | lag-2+ | overshoot |
|---|---|---|---|
| 55.9% | 13.8% | 9.0% | 21.3% |

**Next** (n=2689, excludes true-current==anchor 0 rows):

| exact | +1 | +2 | +3+ | behind |
|---|---|---|---|---|
| 56.4% | 17.7% | 0.7% | 0.0% | 25.1% |

**Per-episode current:**

| ep | exact | overshoot | note |
|---|---|---|---|
| 4 | 45.9% | 48.4% | high overshoot |
| 5 | 20.2% | 0.0% | lag2+ 62.4% — known alias_aware stall |
| 187 | 68.3% | 4.9% | lag2+ 4.7% |
| 368 | 67.7% | 27.8% | |
| 678 | 48.7% | 38.7% | |
| 680 | 54.5% | 28.9% | |
| 994 | 80.1% | 3.6% | best episode |
| 1040 | 54.2% | 33.6% | |

**Per-episode next:** ep5 exact 19.7% / behind 80.3% (same stall); ep994 best at exact 76.5%.

---

## B. Live batch — Task 1(b): ICP hint accuracy (n=2788 accepted events, post-fusion values actually delivered as the hint)

| | distance (m) | bearing (deg) |
|---|---|---|
| median | 0.075 | 5.64 |
| mean | 0.260 | 19.88 |
| p90 | 0.503 | 57.17 |

**Bearing-error buckets with the two known failure-signature %s** (evaluated on the current-role covisibility record of the same attempt):

| bucket | % of all readings | n | near_tie&gt;0 | match_class flagged | both | either |
|---|---|---|---|---|---|---|
| &gt;10° | 39.0% | 1087 | 23.4% | 24.7% | 17.0% | 31.0% |
| &gt;20° | 26.0% | 726 | 29.1% | 29.2% | 20.9% | 37.3% |
| &gt;30° | 19.0% | 530 | 33.2% | 33.0% | 23.4% | 42.8% |

*(This reproduces the project's already-established FINDINGS2 baseline exactly, cross-validating the extraction methodology.)*

---

## C. Offline replay — Task 2(b): ICP bearing accuracy from `category_v2_ep*.json` (9 episodes, n=6424 readings, both current+next roles, all attempts regardless of acceptance)

Bearing only — no distance values exist in this dataset (the generating script never computed distance error).

| | bearing (deg) |
|---|---|
| median | 2.45 |
| mean | 22.10 |
| p90 | 89.69 |

| bucket | % of all readings | n | near_tie&gt;0 | match_class flagged | both | either |
|---|---|---|---|---|---|---|
| &gt;10° | 29.0% | 1863 | 55.3% | 47.6% | 39.6% | 63.3% |
| &gt;20° | 22.9% | 1473 | 60.9% | 53.5% | 44.7% | 69.7% |
| &gt;30° | 19.2% | 1233 | 61.3% | 53.8% | 44.7% | 70.4% |

`match_class` overall distribution: `clean_full_pose` 79.2% (5086), `ambiguous_high_confidence` 13.3% (857), `partial_pose_degenerate` 7.5% (481).

**How B and C compare**: not apples-to-apples — B only grades *accepted* post-fusion events (n=2788, one per attempt); C grades *every* raw per-role ICP candidate regardless of role/acceptance (n=6424, current+next both, pre-fusion). C's median (2.45°) is better than B's (5.64°, no physics/sensor noise), but C's mean/p90 (22.1°/89.7°) and failure-signature rates (~40–70% vs ~17–43%) are worse than B's — mostly because C includes raw "next" readings (pre-promotion, more often genuinely ambiguous) that B's event-level view never surfaces, since B only shows the post-`trust_aware_guard` "current" hint.

---

## D. Offline replay — Task 2(a): anchor-selection accuracy (computed post-hoc from `task2_ep*.json`, self-derived ground truth via polyline projection onto the anchor sequence — see `FINDINGS.md` methodology note below*)

8 of the planned 9 episodes completed before this analysis was stopped (367, 368, 4, 5, 680, 994, 1040, plus the original ep187 validation run); **ep408 was killed mid-run and is excluded** (never finished, no partial numbers used).

**Current** (n=2793, pooled):

| exact | lag-1 | lag-2+ | overshoot |
|---|---|---|---|
| 55.8% | 15.5% | 0.8% | **28.0%** |

**Next** (n=2792, pooled):

| exact | +1 | +2 | +3+ | behind |
|---|---|---|---|---|
| 55.2% | 23.5% | 6.1% | 1.6% | 13.6% |

**Per-episode current:**

| ep | n | exact | lag-1 | lag-2+ | overshoot |
|---|---|---|---|---|---|
| 187 | 551 | 64.1% | 23.0% | 0.0% | 12.9% |
| 367 | 271 | 63.8% | 13.3% | 0.0% | 22.9% |
| 368 | 321 | 53.6% | 10.3% | 0.0% | 36.1% |
| 4 | 256 | 61.7% | 9.0% | 0.4% | 28.9% |
| 5 | 381 | 16.8% | 23.4% | 5.2% | **54.6%** |
| 680 | 381 | 60.9% | 9.7% | 0.0% | 29.4% |
| 994 | 381 | 65.9% | 17.8% | 0.0% | 16.3% |
| 1040 | 251 | 61.8% | 7.6% | 0.0% | 30.7% |

**Per-episode next:**

| ep | n | exact | +1 | +2 | +3+ | behind |
|---|---|---|---|---|---|---|
| 187 | 551 | 64.1% | 12.9% | 0.0% | 0.0% | 23.0% |
| 367 | 271 | 63.8% | 22.9% | 0.0% | 0.0% | 13.3% |
| 368 | 321 | 53.6% | 33.0% | 3.1% | 0.0% | 10.3% |
| 4 | 255 | 63.5% | 32.5% | 2.0% | 0.0% | 2.0% |
| 5 | 381 | 11.3% | 23.1% | 39.6% | 11.5% | 14.4% |
| 680 | 381 | 60.9% | 29.4% | 0.0% | 0.0% | 9.7% |
| 994 | 381 | 65.9% | 16.3% | 0.0% | 0.0% | 17.8% |
| 1040 | 251 | 61.8% | 29.1% | 1.6% | 0.0% | 7.6% |

**Overshoot magnitude distribution (current, offline):**

| magnitude | n | % of overshoot |
|---|---|---|
| 1 | 590 | 75.4% |
| 2 | 148 | 18.9% |
| 3 | 44 | 5.6% |

**How D compares to A (live batch current-selection accuracy)**: overshoot is notably higher offline (28.0% vs 21.3%), and — most strikingly — **ep5 shows 54.6% overshoot offline vs 0.0% overshoot live**, the opposite of its live behavior (live ep5 is a pure lag/stall case, 0% overshoot). This is a real, not-yet-explained divergence between the two pipelines, plausibly connected to the `oracle` vs `accumulated` anchor-geometry-source difference (see header) or to the offline harness's `mechanism_enabled=False` agent construction (see `task2_replay.py`, which otherwise matches the live batch's `bounded_evidence`+`alias_aware`+`belief`+`trust_aware_guard` config) — this divergence was **not investigated further** this session (analysis was stopped by the user before drill-down); flagged here for anyone picking this back up.

*Ground-truth methodology for D: the offline capture does not store the oracle's live arc-length position, so a substitute ground truth was derived by projecting the robot's true world-frame position onto the piecewise-linear polyline formed by anchor world-positions in index order, using each anchor's own recorded `distance_from_start_m` as that point's arc-length coordinate. Validated sound on ep187: 551/1102 rows had a resolvable position, mean projection residual 0.211 m (max 1.197 m — plausible lateral offset from the path centerline), zero monotonicity violations, zero large (&gt;3 m) jumps in the derived arc-length sequence across the episode.

---

## E. Live batch — Q1 deep-dive: root causes of current-overshoot (21.3%) and next-behind (25.1%)

**Overshoot magnitude (live):**

| magnitude | n | % of overshoot |
|---|---|---|
| 1 | 567 | 95.6% |
| 2 | 26 | 4.4% |
| 3+ | 0 | 0% |

**Boundary/sampling-artifact check** (fraction of rows within X% of one anchor-spacing of the true arc-length boundary):

| threshold (% of spacing) | mag-1 overshoot rows within it | exact-match rows within it |
|---|---|---|
| 3% | 7.2% | 6.7% |
| 5% | 10.4% | 8.5% |
| 7% | 13.2% | 9.9% |
| 10% | 18.9% | 12.7% |
| 15% | 29.1% | 16.8% |

Real per-interval travel distance (5 sim-steps at ~0.35 m/s, from ep4's own recorded speed) ≈ 0.03–0.07 m against a 1.0 m anchor spacing = 3–7% — at that real range the two rows barely differ, so the sampling artifact explains only a small minority of overshoot.

**Overshoot diagnostics vs. baseline:**

| | match_class clean/ambig/degenerate | mean overlap_ratio | mean corridor_degeneracy_ratio |
|---|---|---|---|
| mag-1 overshoot (n=567) | 91.7% / 3.9% / 4.4% | 0.957 | 0.693 |
| exact-match baseline (n=1558) | 87.9% / 3.3% / 8.8% | 0.900 | 0.757 |

**Co-occurrence check:**

| pair | co-occurrence rate |
|---|---|
| current-overshoot & next-behind, same attempt | 7.1% / 6.2% |
| current-LAG (diff≥1) & next-behind, same attempt | **92.9% / 87.6%** |

**Concentration by episode:**

| ep | overshoot n | % of total overshoot | behind n | % of total behind |
|---|---|---|---|---|
| 4 | 119 | 20.1% | 21 | 3.1% |
| 5 | 0 | 0.0% | 286 | 42.3% |
| 187 | 22 | 3.7% | 90 | 13.3% |
| 368 | 99 | 16.7% | 27 | 4.0% |
| 678 | 136 | 22.9% | 57 | 8.4% |
| 680 | 113 | 19.1% | 80 | 11.8% |
| 994 | 13 | 2.2% | 75 | 11.1% |
| 1040 | 91 | 15.3% | 40 | 5.9% |

**Next-behind excluding ep5's known stall (n=390):**

| | n | % |
|---|---|---|
| next-candidate diagnostics genuinely poor | 129 | 33.1% |
| next-candidate diagnostics fine, still not promoted | 261 | 66.9% |

Sanity check on the "fine" bucket: median overlap_ratio 0.914, median corridor_degeneracy_ratio 0.735 (both comfortably clear of the "poor" cutoffs).

**Per-episode split of the "fine-but-stuck" share (within non-ep5 behind cases):**

| ep | % fine-but-stuck (i.e. 100% − % genuinely poor) |
|---|---|
| 368 | 96.3% |
| 678 | 94.7% |
| 994 | 36.0% |
| 4 | 28.6% |

---

## F. Live batch — Q2 deep-dive: multi-way categorization of bearing error &gt;10° (n=1087)

**Corridor-degeneracy threshold calibration (tested as a 3rd candidate signal, found not to separate populations):**

| | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|
| clean population (err≤5°, n=1329) | 0.752 | 0.841 | 0.936 | 0.941 | 0.953 |
| "neither A/B" subset of &gt;10° bucket (n=750) | 0.802 | 0.869 | 0.922 | 0.942 | 0.953 |

At clean's own p90 (0.936) as cutoff: 5.9% of clean vs 6.1% of unexplained subset above it (no separation). At p95: 4.1% vs 6.1% (still no separation).

**Final category breakdown (n=1087):**

| category | n | % |
|---|---|---|
| A: near_tie&gt;0 only | 69 | 6.3% |
| B: match_class flagged only | 83 | 7.6% |
| C: both | 185 | 17.0% |
| D: corridor-elevated only (tested, does not hold up as real — folded into F) | 46 | 4.2% |
| **F (incl. D): genuinely unexplained** | **750** | **69.0%** |

**Concentration of F (76 distinct episode/anchor groups touched):**

| ep/anchor | n | % of F | cumulative |
|---|---|---|---|
| ep1040 / anchor4 | 36 | 4.8% | 4.8% |
| ep187 / anchor8 | 31 | 4.1% | 8.9% |
| ep187 / anchor14 | 28 | 3.7% | 12.7% |
| ep680 / anchor5 | 26 | 3.5% | 16.1% |
| ep1040 / anchor7 | 26 | 3.5% | 19.6% |
| ep187 / anchor13 | 25 | 3.3% | 22.9% |
| ep187 / anchor5 | 23 | 3.1% | 26.0% |
| ep678 / anchor14 | 23 | 3.1% | 29.1% |
| ep680 / anchor14 | 23 | 3.1% | 32.1% |
| ep187 / anchor7 | 22 | 2.9% | 35.1% |

**Worst-case concrete examples, ep1040 anchor4 (largest F group, 36 readings — showing the 5 largest errors):**

| attempt | bearing err | dist err | match_class | overlap | corridor_deg | inliers | dx, dy, dθ |
|---|---|---|---|---|---|---|---|
| 249 | 64.8° | 0.421 m | clean_full_pose | 0.750 | 0.818 | 384 | 0.364, 0.232, 123.1° |
| 248 | 53.1° | 0.495 m | clean_full_pose | 0.755 | 0.818 | 354 | 0.304, 0.761, 140.6° |
| 225 | 49.5° | 0.230 m | clean_full_pose | 0.849 | 0.818 | 361 | 0.388, 0.966, 167.6° |
| 237 | 46.9° | 0.368 m | clean_full_pose | 0.799 | 0.818 | 409 | 0.400, 0.337, 127.3° |
| 233 | 46.0° | 0.127 m | clean_full_pose | 0.906 | 0.818 | 464 | 0.396, 0.124, 134.8° |

All five: `clean_full_pose`, `near_tie=0`, healthy overlap/inliers — translation small and reasonable, rotation confidently wrong by 46–65°, same rough direction across attempts. No currently-logged diagnostic flags any of these.

---

## G. Notes on what's NOT in this appendix

- `alias_score` (per-anchor identity-aliasing precompute) could not be checked against either overshoot (§E) or the &gt;10° bucket (§F/category E) in either dataset — the live batch's serialized measurement JSON only stores a `{shape, min, max}` summary of each anchor's point cloud, not the raw points needed to recompute it offline.
- Task 2(a)'s divergence from Task 1(a) (§D's closing note) was flagged but not root-caused — the analysis was stopped by the user before this could be drilled into.
- ep408 has no Task 2(a) numbers (offline replay was killed mid-run, never produced a result file).

---

## H. 2026-07-10 — Follow-up session: gate-level root cause of the "fine-but-stuck" next-behind bucket (§E), a fix, and a live A/B

This section answers a question raised directly against §E/§F's "next-candidate diagnostics look fine, still not promoted" finding (66.9% of non-ep5 next-behind attempts, n=261): **which of the actual promotion-vote gates is blocking these attempts, given that `match_class`/`near_tie_basin_count`/`overlap_ratio`/`corridor_degeneracy_ratio` (the four signals §E/§F screened on) are not what the promotion code itself checks?**

### H.1 Method: real-data replay against the live code, not simulation from first principles

Re-derived every quantity in this section directly from the same `hard11_live_trust_aware_guard_20260707_accumulated` batch's raw files, found locally on the eval workstation (`NaVILA-Bench/eval_results/.../measurements/*.json`, `.../trajectories/*.jsonl`) — not re-typed from FINDINGS.md/DATA.md's own tables:
- Ground truth arc-length per attempt: `route_memory.oracle_route_current_s_m`, recorded every simulation step in the trajectory JSONL (privileged, offline-only, same source implied by FINDINGS.md §2.1's methodology, now confirmed by field name), sampled at the same 5-step relocalization interval and matched in order to each episode's `relocalization_events` list.
- Per-attempt current/next ICP diagnostics: `route_relocalization_diagnostics.covisibility_records` inside each episode's measurement JSON — confirmed by direct code reading (`relocalization.py::sequential_pair_anchor_relocalization`'s `_append_covisibility_record` calls) to be the **raw, pre-closure-check** ICP result for whichever two anchors were actually offered as `{current, next}` that attempt, including `confidence`, `inlier_count`, `overlap_ratio`, `match_class`, `icp_near_tie_basin_count`, `corridor_degeneracy_ratio`, and the raw `estimated_anchor_dx_m/dy_m`.
- Actual accepted outcome per attempt: `route_memory.relocalization_events`, each carrying `target_anchor_index` (current after this attempt) and `sequence_observation.source` (suffixed `:current_retained` / `:next_promoted` by `_select_sequential_pair_relocalization`).

`ep678`/`ep680`'s measurement JSON hit the same intermittent Isaac-Sim write-corruption bug documented elsewhere in this project (see the main README's 2026-07-08 entry) — this time 3 **new** corruption signatures not previously catalogued (all regex/string-replace repaired, each confirmed to restore valid JSON): a dropped key name leaving an orphan `,\n: value` pair (missing `"overlap_ratio"`), a duplicated colon with a missing value (`"seed_count": : ,`), and a bracket/value splice (`]]"icp_best_to_second_score_ratio"` and a duplicated-and-concatenated float run into the next key's quotes).

**Validation that the replay methodology is sound**: total replayed attempts across all 8 episodes = **2788**, matching FINDINGS.md's n exactly. Pooled next-selection accuracy (excluding true-current==0): exact 56.7% / +1 19.6% / +2 0.7% / behind 23.0%, vs. FINDINGS.md's 56.4% / 17.7% / 0.7% / 25.1% (the few points of difference are attributable to this replay's step-alignment being an approximation — sampling the trajectory JSONL every `relocalization_interval_updates` steps in order rather than an exact per-attempt timestamp join). Non-ep5 next-behind poor/fine split: 35.8%/64.2% here vs. DATA.md's §E 33.1%/66.9% — same shape, close enough to trust the gate-level breakdown below.

### H.2 The three real promotion-vote gates, reconstructed exactly from code

`route_memory_agent.py::_select_sequential_pair_relocalization` (prior to this session's fix) decides whether to promote `next` using exactly three conditions on `next`'s and `current`'s **post-closure-check** `AnchorRelocalization` (i.e. after `_sequential_pair_closure_precheck`'s belief-mode fusion/`trust_aware_guard` reconstruction has already possibly rewritten them):

```python
close_enough = next_est.distance_to_anchor_m <= self.promotion_close_radius_m   # 0.75m at anchor_spacing_m=1.0
trend_ok = self._promotion_trend_improving(next_idx)                            # last 3 (of a 4-sample window) distances must shrink monotonically within a 0.05m margin
quality_ok = next_quality >= self.promotion_score_ratio * max(current_quality, 1e-9)  # next_quality >= 0.85 * current_quality
candidate_promote = quality_ok and (close_enough or trend_ok or current_est is None)
```

where `quality = confidence * sqrt(inlier_count)`, and `confidence` itself (`relocalization.py:1629`) is `min(1.0, overlap_ratio * max(0, 1 - median_residual_m/0.45) * 1.5)` — **this does not read `match_class` or `near_tie_basin_count` at all**, confirming those two diagnostics (used throughout §D–§F to classify "healthy" vs "poor") are structurally independent of what actually gates promotion. `candidate_promote` then has to clear `bounded_evidence`'s vote window (3-of-last-5, or 5-of-last-8 if `alias_aware`-flagged) before `_target_anchor_index` actually advances.

### H.3 Gate-level breakdown of the "fine-but-stuck" bucket (n=228 in this replay, vs. §E's 261)

| gate that failed | n | % of fine-but-stuck | concentrated in |
|---|---|---|---|
| `close_enough` AND `trend_ok` both fail | 74 | 32.5% | ep368 (89% of its own fine-but-stuck rows), ep1040 (73%) |
| votes not yet accumulated (`candidate_promote=True`, bounded_evidence count &lt;3) | 40 | 17.5% | ep994 (38%) |
| `quality_ok` fails (next's quality &lt; 0.85× current's) | 26 | 11.4% | ep187 (34%) |
| **passes every gate on the raw pre-closure-check reading, but the real live run did not promote at that attempt** | **88** | **38.6%** | **ep678 (50%), ep680 (71%)** |

The first three rows are the promotion design working as intended, just slowly (robot genuinely not close enough yet, distance readings genuinely noisy, or votes genuinely still accumulating) — not bugs.

### H.4 Root cause of the fourth row: closure-check/belief-fusion feeds into the promotion gate, not just the reported hint

Of the 88 "should have promoted per raw ICP" attempts, only **39 (44.3%)** are explained by `alias_aware`'s stricter 5-of-8 vote requirement (this replay can only approximate that check — `alias_score` per anchor is not retained in serialized data, same gap noted in §G, so a flat 3-of-5 was assumed unless the alias-adjusted count was also checked and still failed). The remaining **49 attempts (55.7% of the 88, ~1.8% of all 2788 attempts, concentrated almost entirely in ep678/ep680)** are not explained by anything already documented in this investigation.

Tracing the code (not inferring from data) found the actual mechanism: `_select_sequential_pair_relocalization` calls `_sequential_pair_closure_precheck` **first**, and only then computes `close_enough`/`trend_ok`/`quality_ok` against whatever that precheck returns. This batch runs `sequential_pair_closure_mode=belief` with `sequential_pair_closure_belief_trust_aware_guard=True` (confirmed from this batch's own logged config) — so whenever current/next's raw readings disagree beyond threshold, the promotion gates see a value that has already been blended (continuous belief fusion) or reconstructed (trust-aware substitution) toward the *other* side, not next's own independent raw ICP reading. **The trust_aware_guard/belief-fusion mechanism, built 2026-07-07 specifically to fix the *reported* bearing hint, was — without anyone having checked — also feeding into and delaying the separate *promotion* decision.** This is consistent with ep678/ep680 being exactly the two episodes already flagged in the main README's 2026-07-07 entry as showing sustained fusion-instability signatures (the `ep678` 164-attempt `anchor12` stall with wildly swinging fused bearing).

### H.5 Fix implemented (code, opt-in, topology-preserving)

`route_memory_agent.py`: new constructor flag `sequential_pair_promotion_use_pre_closure_estimates` (default `False`, byte-identical behavior when off, matching this project's convention of every mechanism change being opt-in). When `True`, `_select_sequential_pair_relocalization` computes `close_enough`/`trend_ok`/`quality_ok`/the promotion vote against each side's **raw, pre-closure-check** `AnchorRelocalization` instead. The final **reported** hint (`bearing_to_anchor_deg`/`distance_to_anchor_m`, once a side is selected) is completely unaffected — it still comes from the post-closure-check value and goes through the unchanged belief-fusion/trust_aware_guard pipeline. `_next_candidate_index` (still `current_idx - 1`, quarantine-skip-aware) and the `bounded_evidence`/`alias_aware` vote-window mechanism itself are both untouched — this only changes which values feed the three gates, not the two-candidate topology or the anti-cascade guarantee.

Wired through `round_trip_eval.py` as `--sequential_pair_promotion_use_pre_closure_estimates` (CLI flag + measurement-JSON config-logging entry, matching every other mechanism flag's existing pattern).

**Validated**: 4 new unit tests (`SequentialPairPromotionUsePreClosureEstimatesTest` in `tests/test_route_memory_agent.py`) covering default-off unchanged behavior, flag-on promoting on a raw reading that the post-fusion value would have blocked (constructed from a real trust-aware-guard reconstruction scenario), and confirming the reported hint still comes from the closure-fused value even with the flag on. Full suite: 99/99 pass (up from 95 pre-existing, zero regressions); a full `tests/` discovery run shows 209 tests with only one unrelated pre-existing failure (`test_loftr_matching.py` needs `cv2`, an environment gap unrelated to this change).

### H.6 Live A/B (launched, result pending as of this writing)

`promotion_use_raw_estimates_hard11_20260710_accumulated`, launched 2026-07-10T14:46 local time, fully detached (`nohup setsid ... & disown`, confirmed `PPID=1`/no controlling TTY — survives session/connection close). Identical hard-11 config to the already-validated `hard11_live_trust_aware_guard_20260707_accumulated` baseline (bearing mean 19.88°, anchor-selection 55.9% exact / 21.3% overshoot / 25.1% next-behind, never ≥3-anchor overshoot) plus only the new flag, so it is directly comparable without a fresh baseline re-run. Launcher: `/home/teambruce/run_promotion_use_raw_estimates_hard11_20260710.sh`; master log `/home/teambruce/promotion_use_raw_estimates_hard11_20260710_master.log`. Per-episode timeout 7200s; prior same-shape 11-episode batches took ~2.5–3h total. **Results not yet available as of this writing** — episode 4 was still in progress at time of documentation.

**What to check once it finishes**: (1) next-behind % should drop by roughly the H.3/H.4 magnitude (the 38.6%-of-fine-bucket slice this fix targets, i.e. up to ~3% of all attempts pooled, more concentrated in ep678/ep680); (2) overshoot % must not increase — the candidate topology and vote window are unchanged, so it shouldn't, but this needs empirical confirmation, not just the topology argument; (3) whether ep678/ep680 specifically show the largest improvement, matching where the replay-gap concentrated. If the live result diverges from this offline prediction, the most likely explanation is the un-modeled `alias_aware` interaction (§H.4's caveat) rather than a flaw in the fix itself.
