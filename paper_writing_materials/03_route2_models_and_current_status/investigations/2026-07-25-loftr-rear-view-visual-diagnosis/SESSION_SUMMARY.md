# 2026-07-25 Session Summary — Candidate Reachability, LiDAR Search Ceiling, and Vision Selector Attempts

**Author**: Claude (Route 1)
**Scope**: full day's investigation following up `investigations/2026-07-24-confidently-wrong-open-problem-summary/`. This document consolidates every experiment run today; `FINDINGS.md` (same folder) has the detailed visual root-cause pass (5 annotated match images) referenced in §4 below.

**Bottom line up front**: LiDAR-only fixes (denser search, candidate retention, anchor self-symmetry prescreening) are now conclusively ruled out — not a search problem, the ICP objective landscape itself favors the wrong answer even under oracle seeding. Vision (LoFTR independent pose estimate) has real theoretical headroom — trying multiple camera pairings roughly triples the achievable accuracy ceiling — but **every selector tried today to actually realize that headroom failed**, several performing worse than guessing. The unsolved bottleneck is precise: we cannot currently tell, from any single reading or any comparison between readings (LiDAR-vs-LiDAR, vision-vs-vision, or LiDAR-vs-vision), whether that reading is trustworthy. This rules out the whole family of "score a candidate, trust it if the score is high" approaches — the same conclusion the project already reached for raw LiDAR scalar confidence, now confirmed to extend to vision.

---

## 1. LiDAR-only candidate generation/search — ruled out

### 1.1 Candidate reachability (offline replay, reusing production `icp_seed_sweep_2d`)
- Ground-truth-verified confidently-wrong sample, n=100 steps across 18 of the 30 originally-catalogued failure anchors (2 dropped: `ep428` no captured data / timeout, `ep646` not confidently-wrong per original table).
- **recall@4 = 3%** (matches the project's known ~4.8% figure — cross-validates this session's offline replay methodology against the original online-derived statistic).
- **recall@24 (full 24-seed sweep, not just the top-4 production persists) = 20%** — meaningful headroom exists in principle from just keeping more of what's already searched.

### 1.2 Global registration diagnostic (dense sweep + ground-truth-seeded convergence)
On the 80 cases where even the full 24-seed sweep didn't contain the correct answer:
- **Dense 72-seed sweep (5° spacing) finds GT in only 4/80 (5%)** — ruling out "seed density" as the bottleneck.
- **Ground-truth-seeded ICP** (initialize the optimizer exactly at the correct rotation): converges and *stays* near GT in 44/80 (55%) — so GT often *is* a real, reachable local optimum, just one arbitrary fixed seeds rarely land in.
- **But of those 44, only 2/80 (2.5% overall) score competitively (≥95% of the wrong top-1's score)** — i.e. even with a perfect oracle seed, the point-to-point ICP objective itself prefers the wrong answer 97.5% of the time.

**Conclusion**: this is an objective-landscape problem, not a search-coverage problem. No amount of better/denser LiDAR-only search recovers this.

### 1.3 Anchor self-symmetry score (pure LiDAR, anchor-creation-time, offline pre-screening)
- Tested the research report's `S_i(Δθ) = sim(D_i, rotate(D_i, Δθ))` formulation: 18 known-problem anchors vs. 54 control anchors from the same episodes.
- Problem anchors mean `symmetry_ratio` = 0.289; control anchors mean = 0.290. **AUROC = 0.475** — no discriminative power. Ruled out as implemented (possible reason: real ambiguity may be anchor-vs-*different*-live-scan aliasing, not anchor-vs-self-rotated symmetry — a different, untested hypothesis, low priority).

---

## 2. Vision (LoFTR-rear independent pose estimate) — real headroom, no working selector

### 2.1 Single fixed pairing (production's `_loftr_rear_yaw_check`, built 2026-07-13, designed as the fix in `investigations/2026-07-23-.../FINDINGS.md` §6.1, executed for the first time today)
- Confidently-wrong subset (n=100): **9% correct**.
- ICP-already-correct control subset: **14-20.8%** correct depending on sample (n=64 hand-sampled / n=313 full set) — notably, vision does *worse* than chance-adjacent even on cases LiDAR gets right.
- Switching `outdoor`→`indoor` pretrained LoFTR weights: 9%→10%, 14%→25% — some improvement on easy cases, negligible on hard cases; rules out weight domain-gap as the *dominant* cause.
- Camera extrinsics verified numerically sane (front/rear differ by 179.97° in body frame).
- "Closest physical approach" sanity set (7 cases, robot within 0.15-0.4m of anchor): **0/7 correct**, several with near-100% RANSAC inlier ratios — first clue that inlier count doesn't track correctness at all.

### 2.2 Visual root-cause pass (see `FINDINGS.md` + 5 images in this folder)
Five hand-picked cases visualized (matched keypoints on anchor-rear | current-front image pairs) revealed two distinct, separable failure mechanisms:
- **Majority mechanism**: the "current front ≈ anchor rear" pairing assumption only holds when ground-truth `dtheta` is close to 180°. When it deviates (dtheta far from 180°), the two camera views show **genuinely different rooms** — LoFTR still produces plausible-looking matches (using generic architectural features — ceiling corners, doorframes — that recur across many different rooms in this Matterport dataset), but the "match" is geometrically meaningless by construction. This concentrates exactly where the project's confidently-wrong failures already cluster (multi-door turn-around junctions), since heading is least stable there.
- **Minority mechanism**: even when the pairing assumption holds (dtheta≈180°, genuinely overlapping content), highly repetitive local texture (case C: parallel ceiling beams, 2103/2131 = 98.7% RANSAC inliers) still produces a confidently-wrong match — a direct visual analogue of the LiDAR problem.

### 2.3 Trying all 4 front/rear camera-pairing combinations (not just the fixed one)
- Confidently-wrong (n=100): fixed-pairing=9%, **oracle-best-of-4=23%**, naive auto-select-by-match-count=4% (worse than doing nothing), ≥1 combo has substantial overlap (≥30 matches) in **100%** of cases.
- ICP-correct control (n=313): fixed=20.8%, **oracle-best-of-4=46%**, naive auto-select=20.4% (flat, no improvement).
- **Confirms the majority-mechanism finding quantitatively**: trying multiple pairings roughly *triples* the theoretical ceiling — most failures are a "looked in the wrong direction" methodology problem, not fundamental unsolvability. But naive selection-by-match-count captures none of this headroom, because wrong-room combos can produce just as many (or more) matches as the correct combo (case B: wrong combos had 129-178 matches, correct combos 101-163 — no separation by count).

### 2.4 Selector attempts — all failed to realize the oracle ceiling

| Selector tried | Confidently-wrong (baseline 9%, oracle 23%) | Control (baseline 20.8%, oracle 46%) |
|---|---|---|
| Naive: highest LoFTR match count | 4% | 20.4% |
| Within-vision cross-combo angle agreement (≤25°) | 6.1% precision (of 66% that had any agreement) | 27.2% precision (of 89.1%) |
| Cross-modal (any of 24 ICP candidates × any of 4 vision combos agreeing ≤25°) | 8.4% precision (of 95% "agreeing" — likely inflated by multiple-comparisons noise, see caveat below) | not tested |
| 3D spatial-spread / degeneracy ratio of RANSAC inlier points (LiDAR-`corridor_degeneracy_ratio` analogue) | AUROC 0.573 (weak); 6% as selector | not tested |
| Global scene similarity, ImageNet ResNet18 | AUROC 0.550 (weak); 6% as selector | not tested |
| Global scene similarity, SALAD (DINOv2 + optimal transport, purpose-trained for visual place recognition) | AUROC 0.506 (~random); 5% as selector | not tested |

**Caveat on the cross-modal test**: comparing all 24 ICP candidates against all 4 vision combos (up to 96 pairs) with a generous 25° tolerance is likely to find *some* coincidental near-agreement by chance alone even between unrelated wrong values; the 95%-agreement / 8.4%-precision numbers should be read as an upper bound on how bad a properly-constrained version might look, not a clean result.

**Why within-vision agreement fails specifically**: errors are correlated, not independent, across camera pairings of the same physical scene — the same texture/aliasing that fools one view combo often fools a different combo looking at overlapping/nearby content in a consistent way. This directly echoes the research report's own warning that perceptual-aliasing errors tend to be correlated, not independent random outliers — now with direct empirical confirmation on this project's own vision data.

**Why the 3D spatial-spread metric fails on repetitive structure (case C)**: it measures whether matched points span a diverse 3D volume, not whether the *correspondences themselves* admit an equally-good alternative assignment. Case C's ceiling-beam matches spread across the whole image (near-far, up-down) — spatially diverse — while still being systematically ambiguous about *which* beam matches *which*. This is a periodicity/self-correlation problem, not a spatial-coverage problem; the metric tested measures the wrong thing for this specific failure mode. A proper fix would need an explicit repetition/self-correlation check, not tried yet.

**Why SALAD underperforms even a generic ImageNet classifier**: likely domain gap — SALAD is trained on GSV-Cities (real-world, outdoor, Google Street View imagery); this project's data is indoor, synthetic Matterport renders. A second, larger instance of the same domain-gap pattern already seen with LoFTR's outdoor/indoor pretrained weights. Notably, on the one hand-picked "obviously different rooms" example (case B), SALAD *did* rank the wrong combo lowest, more cleanly than ResNet18 — so the underlying idea (holistic scene descriptor > local keypoint count for this specific failure mode) has qualitative merit; it's the specific off-the-shelf model that doesn't transfer to this domain, not the concept.

---

## 3. Overall conclusion

1. **Pure LiDAR-only approaches are closed.** Confirmed by two independent, decisive experiments (§1.1-1.2): the confidently-wrong problem is not a search-coverage gap; the ICP objective structurally favors the wrong pose regardless of how it's searched.
2. **Vision has real theoretical headroom** (oracle-best-of-4 roughly triples raw accuracy) **but no working selector was found today**, across five structurally different signal types (raw match count, within-vision agreement, cross-modal agreement, 3D geometric constraint quality, two flavors of global scene descriptor).
3. **The core unsolved problem is precise**: neither LiDAR nor vision, alone or compared against each other, currently supports a reliable judgment of "is this one reading correct" — not just "which of several candidates is correct." This rules out the entire class of confidence-scoring/filtering approaches, not just today's specific attempts.
4. **Two failure mechanisms are now cleanly separated for vision specifically**: a majority "wrong camera pairing selected" methodology problem (theoretically fixable, practically unsolved due to the missing selector) and a minority genuine visual self-similarity problem (case C, needs a periodicity-aware detector, not yet tried).

## 4. Open threads for whoever picks this up next

- A periodicity/self-correlation-aware degeneracy check for vision correspondences (the true analogue of the LiDAR corridor-degeneracy check, distinct from the spatial-spread metric tried in §2.4 which tests the wrong property).
- AnyLoc (frozen DINOv2 + VLAD, not fine-tuned on outdoor-specific data the way SALAD is) as a possibly more domain-general global descriptor, not yet tried.
- A properly-constrained cross-modal consistency test (ICP top-1 vs. best single vision combo, not an unconstrained 24×4 search) to get a clean (non-inflated) read on whether cross-modal agreement carries any real signal once the multiple-comparisons issue is removed.
- Active probing and temporal multi-hypothesis tracking (report's remaining untested directions) — both sidestep the "judge a static reading" framing entirely, which is where every attempt today failed regardless of signal source.
- Architecting for robustness to undetectable bad readings (bound the consequence rather than detect the error), matching the philosophy already underway in the Policy V2 work on Route 2.
