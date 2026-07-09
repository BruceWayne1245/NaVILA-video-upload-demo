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
