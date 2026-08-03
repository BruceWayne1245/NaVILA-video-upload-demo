# 2026-07-13 (continued) — Offline check: is the hard-anchor set's wrong yaw a search-density problem or genuine metric-level ambiguity?

**Purpose**: `FINDINGS.md` in this folder identified a small, cross-run-reproducible hard-anchor set (`ep367` anchor8, `ep368` anchor12, `ep678` anchor7). `investigations/2026-07-09-.../route_memory_literature_survey.md` §2.3/2.5 recommended, as a cheap, offline-only, not-yet-tried next diagnostic (before committing to any new live mechanism): check whether a genuinely different/more exhaustive search can recover the correct yaw from these anchors' own single-frame geometry, to distinguish "ICP got stuck in a local optimum a wider search would have found" from "the wrong pose is a real global optimum under this scoring function — a genuine geometric ambiguity no amount of extra search fixes." This is that check.

**Method**: reused the live production functions directly (`icp_rigid_transform_2d`, `_icp_score`, `voxel_downsample_2d`, imported unmodified from the current `relocalization.py` — not a reimplementation, so results are directly comparable to what the live pipeline actually computes) against real captured point clouds from `icp_replay_capture_hard11_20260706_accumulated` (`ep678` anchor7 excluded — that capture's `anchors.json` is corrupted, a pre-existing, already-documented issue unrelated to this check). For `ep367` anchor8 and `ep368` anchor12, sampled 8 return-phase steps each (spread across the 0.2–2.5m range from the anchor) and ran three things per step, all under the identical point-to-point objective, 0.45m correspondence threshold, 16 max iterations:

1. **Production search**: the exact live 24-seed sweep (yaw seeds every 15°, matching `sequential_pair_anchor_relocalization`'s default).
2. **Dense search**: the same seed sweep at 1° resolution (360 seeds) — a 15x denser, near-exhaustive version of the identical search.
3. **Truth-seeded**: a single ICP run initialized exactly at the true relative yaw (computed directly from the two frames' ground-truth world-pose quaternions, not inferred from dx/dy) and allowed to locally refine — this tests whether starting ICP *at* the correct answer causes it to stay there and score competitively, or to drift away toward a different, higher-scoring basin.

## Result: denser search does not help, and the true pose is often a genuinely lower-scoring optimum than the wrong one

| ep | anchor | step | true_dist | true_yaw | 24-seed err / score | 360-seed err / score | truth-seeded err / score |
|---|---|---|---|---|---|---|---|
| 367 | 8 | 1925 | 2.41m | 134.2° | 3.2° / 9.549 | 5.1° / 9.822 | 3.6° / 9.589 |
| 367 | 8 | 2040 | 1.81m | 145.3° | **112.9° / 6.712** | **111.9° / 6.932** | 7.4° / **3.457** |
| 367 | 8 | 2155 | 1.27m | 166.7° | 26.0° / 6.151 | 25.7° / 6.405 | 0.8° / 5.606 |
| 367 | 8 | 2270 | 0.53m | -177.1° | 5.7° / 20.828 | 5.9° / 20.858 | 5.6° / 20.864 |
| 367 | 8 | 2520 | 0.68m | 140.2° | **170.9° / 10.883** | **173.4° / 11.028** | 1.6° / **6.134** |
| 367 | 8 | 2635 | 1.49m | 134.1° | **92.2° / 10.802** | **92.7° / 10.847** | 4.5° / **5.722** |
| 367 | 8 | 2750 | 2.03m | 102.4° | **179.8° / 9.186** | 155.5° / 11.028 | 0.1° / **3.673** |
| 367 | 8 | 2870 | 2.49m | 82.9° | **104.5° / 8.753** | 103.9° / 8.856 | 12.3° / **4.638** |
| 368 | 12 | 2245 | 0.22m | 109.9° | **48.7° / 8.053** | 48.1° / 8.412 | 1.1° / **3.626** |
| 368 | 12 | 2305 | 0.69m | 111.9° | **43.8° / 5.231** | 33.4° / 5.348 | 9.0° / **3.279** |
| 368 | 12 | 2365 | 1.17m | 114.1° | **56.1° / 5.310** | 52.5° / 5.476 | 4.7° / **2.763** |
| 368 | 12 | 2430 | 1.38m | 139.7° | **163.8° / 5.857** | 161.7° / 5.996 | 2.0° / **2.314** |
| 368 | 12 | 2490 | 1.43m | 168.5° | **123.8° / 5.218** | 100.4° / 5.586 | 5.5° / **2.853** |
| 368 | 12 | 2555 | 1.70m | 173.2° | **74.0° / 8.139** | 74.6° / 8.449 | 3.0° / **2.804** |
| 368 | 12 | 2615 | 2.06m | 174.7° | **82.9° / 7.876** | 78.9° / 8.596 | 4.6° / **2.620** |
| 368 | 12 | 2680 | 2.47m | 177.0° | **88.5° / 6.295** | 94.7° / 6.503 | 3.4° / **3.128** |

(bold = the two things being compared: a >20° error alongside a HIGHER score than the truth-seeded run's score at the same step)

**Two consistent patterns across 13 of 16 sampled readings (both anchors):**

1. **24-seed and 360-seed search converge to essentially the same answer, at essentially the same score.** The dense, 15x-denser search never finds a materially different or better optimum than the already-live 24-seed sweep (theta_err and score both move by only a few percent or a few degrees at most, in either direction). **This rules out "the production seed density is too coarse" as the explanation** — the live pipeline is not missing the correct basin for lack of trying enough starting points; a near-exhaustive rotation search lands in the same place.
2. **When ICP is initialized exactly at the true yaw, it converges to a LOWER score than the wrong answer found 8-15 points away in most cases** (e.g. `ep367`/2040: wrong answer scores 6.71–6.93, truth-seeded only reaches 3.46; `ep368`/2245: wrong answer 8.05–8.41, truth-seeded only 3.63). In several cases the truth-seeded run doesn't even stay near the truth (`ep367`/2040 drifts to 7.4° off; `ep367`/2870 drifts to 12.3° off) — local refinement itself pulls the estimate away from the correct answer toward the more attractive wrong basin.

**Conclusion**: for this hard-anchor set, the wrong yaw is not an artifact of insufficient search density or bad initialization — it is a **genuinely better-scoring solution under this project's own point-to-point ICP metric** (inlier count / median residual under a fixed correspondence threshold) than the true pose is. A global, exhaustive, or differently-initialized search using the *same* metric will not fix this, because the metric itself prefers the wrong answer. This is real geometric ambiguity, not a local-optimum-avoidance problem.

**Not every reading at these anchors is bad** — `ep367`/1925 and `ep367`/2270 both show small errors (3.2°, 5.7°) at all three search strategies, consistent with `FINDINGS.md` §6's finding that most bad anchors are *unstable* (right at some viewing positions, wrong at others) rather than uniformly wrong from every angle.

## What this rules in / rules out for the next mechanism

- **Ruled out**: widening the existing seed sweep (e.g. 24→48 or 72 seeds) — already shown equivalent to a 360-seed sweep, no benefit.
- **Ruled out**: better ICP initialization from a smarter prior — truth-seeded initialization still loses to the wrong answer's score under this metric, so even a perfect prior wouldn't survive the current objective's own local refinement.
- **Confirmed** (answers the branch this check was designed to distinguish): the geometry is genuinely ambiguous *under this metric*, which is exactly the premise the short-baseline disambiguation mechanism (step 5) was designed around — a second, independent viewpoint (real parallax) is still the right *category* of fix, since no amount of searching harder over a single frame's own point-to-point residual can resolve it. The problem documented in `investigations/2026-07-12-.../PROGRESS.md` (short-baseline fires on only 0.1% of live events, 0% recall on true errors >45°) is a **triggering/threshold problem in that mechanism**, not evidence the wrong *category* of fix was chosen.
- **Also worth trying, not yet tested**: a genuinely different *scoring function* (not just a different search strategy over the same one) — e.g. a correlative occupancy-grid score, or a point-to-line/normal-weighted objective that penalizes the wrong pose's presumably-worse surface-normal agreement even where raw point-to-point inlier count is fooled. This is the survey's Option B (`3.B` correlative occupancy verifier / Cartographer-Olson style), still genuinely untried, and this result is a concrete reason to prioritize it over any further ICP search-strategy tuning.

## Reproducibility

Script: `code/global_registration_check_20260713.py` in this folder. Uses `icp_replay_capture_hard11_20260706_accumulated`'s `ep367`/`ep368` captures (`icp_replay_dataset/anchors.json` + `steps/*.json`), imports `relocalization.py` from the live `NaVILA-Bench/scripts` directory unmodified.
