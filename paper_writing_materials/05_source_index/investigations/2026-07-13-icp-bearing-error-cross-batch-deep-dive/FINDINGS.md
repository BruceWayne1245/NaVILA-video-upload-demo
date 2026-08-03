# 2026-07-13 — Cross-batch deep dive into the ">10° bearing error" bucket: the problem is stable, mostly non-catastrophic, mostly unstable-not-fixed, and a small reproducible hard-anchor set now exists

**Purpose of this document**: `investigations/2026-07-12-promotion-fix-live-ab-and-next-behind-decomposition/PROGRESS.md` closed out with steps 1-2 (yaw-curve/yaw-observability diagnostics) and step 4 (Scan Context yaw cross-check) both showing negative/near-zero discriminative power, and step 5 (short-baseline disambiguation) implemented and live-validated but firing on only 3/2338 reported events (0.1%) with 0% recall against true errors >45°. Since none of steps 1/2/4/5 touch ICP's own raw estimate — they are all post-hoc diagnostics or a rarely-firing downgrade flag — the underlying rotational-error problem in the raw per-candidate ICP readings should be identical, within noise, in the `short_baseline_hard11_20260712_accumulated` batch (2026-07-12) and the `promotion_use_raw_estimates_hard11_20260710_accumulated` batch (2026-07-10) that preceded it. This document pools both batches' raw covisibility-record ICP readings (n=9030 combined) to get a larger, more precise, cross-run-validated characterization of the persistent ">10° bearing error" problem than any single batch could give — extending, not replacing, `investigations/2026-07-09-anchor-promotion-lag-and-icp-rotational-error/FINDINGS.md`'s original 69%-unexplained framing.

**Headline result**: the >10° rate is statistically identical across the two independent batches (32.6% vs 32.7%), confirming the problem is a stable property of the anchors/ICP pipeline, not run-to-run noise. Of the >10° readings, 46.5% still trigger no existing diagnostic at all (match_class=`clean_full_pose`, near_tie=0) — down somewhat from the original 69% figure (see §3 for why the denominators aren't directly comparable), but still the largest single bucket. New this session: (1) `confidence` and `median_residual_m` — not previously highlighted as candidate signals — show a real, moderate separation between "confidently wrong" and clean readings, unlike `corridor_degeneracy_ratio` or the 2026-07-10 yaw-curve/yaw-observability diagnostics, which show none; (2) most of the "unexplained" bucket is not catastrophic — 62% of it is under 60° error, only 21% exceeds 120°; (3) most persistently-bad anchors show attempt-to-attempt *instability* (error swinging session to session) rather than a single fixed wrong pose, which argues against "genuine static 180° symmetry" being the majority explanation; (4) a small set of anchors reproduce as bad across both independent live batches, giving a concrete, reusable hard-anchor set for validating any future fix without a fresh live run; (5) the 2026-07-09 survey's own flagship example (`ep1040`/anchor4`, previously "dθ stably wrong 120–170°") does **not** reproduce anywhere near that severity in either of these two later batches (14.9° and 31.4° mean respectively) — a caution against over-fitting any future mechanism to one historical example.

---

## 1. Methodology

Both batches ran the identical live production config (`bounded_evidence` + `alias_aware` + `trust_aware_guard` + `promotion_use_pre_closure_estimates`, `--sequential_pair_anchor_geometry_source=accumulated`, `--route_hint_source=oracle` so the VLM never sees this data — it is purely a parallel shadow-relocalizer diagnostic in both batches), plus only `--sequential_pair_short_baseline_disambiguation` added in the 2026-07-12 batch. Since that flag only ever sets `anchor_heading_reliable=False` on the *reported/fused* estimate and never touches the raw per-candidate ICP output, the two batches' raw `covisibility_records` are directly poolable.

For every `outcome=="pose_candidate"` covisibility record (both the `current` and `next` role per attempt, matching this project's established practice — see `investigations/2026-07-06-.../` and `2026-07-09-.../DATA.md`), ground truth is computed directly from the trajectory JSONL's per-step privileged `position`/`quaternion_wxyz` (never seen by the VLM, eval-only) against the corresponding anchor's `metadata.world_pose` (also privileged, stored at anchor-creation time) — i.e. a genuine ground-truth body-frame bearing to whichever anchor ICP was actually evaluating that attempt, not a comparison against which anchor "should" be current/next. Attempt-to-trajectory-row alignment uses this project's established approximation (`row_idx = 0 if attempt==1 else (attempt-1)*interval-1` into the return-phase-filtered row list, `interval=5`), validated in `investigations/2026-07-10-.../FINDINGS.md` §1 to reproduce known pooled counts exactly.

Episodes used: the 7 round-trip-succeeded episodes from each batch — 2026-07-10: `{4,134,367,368,678,994,1040}` (`ep1040`'s measurement JSON required repairing 2 corruption instances, same classes already documented in `investigations/2026-07-10-.../FINDINGS.md` §1 — a duplicated-string-glue defect and a dropped-key-before-colon defect, both fixed via targeted string replacement, re-verified to parse and match the already-published `2026-07-10` numbers); 2026-07-12: `{4,187,367,368,678,994,1040}`. Note the sets differ by one episode each (`ep134` vs `ep187`) since `ep134` timed out and `ep187` newly succeeded in the 2026-07-12 run — a real batch-to-batch difference, not a methodology choice.

**Important caveat found this session**: for episodes where the oracle hint + `hint_action_arbiter` fully determines the robot's actual path (the VLM's own output is overridden whenever it would conflict), the return trajectory can be **bit-for-bit identical** across independently-launched batches. Confirmed directly: `ep367` anchor8's per-attempt bearing errors are numerically identical to the 11th decimal place between the two batches (mean 57.29301090805101°, n=50, both runs). This means cross-batch "confirmation" for `ep367`-style anchors is really one experiment observed twice, not two independent trials — treat `ep367`'s persistence entries in §7 with that caveat. Other anchors (`ep368` anchor12, `ep4` anchor11) show real, different numbers between the two batches, confirming the two runs are not wholesale identical and that genuine independent variation does exist elsewhere (most likely from residual VLM-action stochasticity where the arbiter doesn't need to override, or physics/scene non-determinism).

---

## 2. Headline: the >10° rate is stable across two independent batches

| batch | n readings | >10° | median | mean | p90 |
|---|---|---|---|---|---|
| 2026-07-10 (`promotion_use_raw_estimates_hard11_20260710_accumulated`) | 4473 | 32.6% (1457) | 2.88° | 26.77° | 111.41° |
| 2026-07-12 (`short_baseline_hard11_20260712_accumulated`) | 4557 | 32.7% (1491) | 3.33° | 24.58° | 105.04° |
| **combined** | **9030** | **32.65% (2948)** | **3.12°** | **25.67°** | **107.37°** |

Per-episode >10° rate (2026-07-12 batch) ranges 19.8% (`ep4`) to 42.9% (`ep994`) — a real, substantial per-episode spread, but every episode shows a meaningful long tail; there is no "clean" episode in this data.

---

## 3. Full breakdown of the >10° bucket, combined n=2948

| category | n | % of bucket |
|---|---|---|
| `match_class` self-flagged (`ambiguous_high_confidence` / `partial_pose_degenerate` / `height_inconsistent_2p5d`) | 1246 | 42.3% |
| `icp_near_tie_basin_count > 0` | 1388 | 47.1% |
| **unexplained (`match_class==clean_full_pose` AND `near_tie==0`)** | **1371** | **46.5%** |

`match_class` distribution within the bucket: `clean_full_pose` 1702 (57.7%), `ambiguous_high_confidence` 891 (30.2%), `partial_pose_degenerate` 355 (12.0%).

**Why this 46.5% isn't directly comparable to the 2026-07-09 survey's 69% figure**: that number was computed against the *reported/fused* hint population (n=1087 out of 2788 accepted events, one reading per attempt) checked against three diagnostics including `corridor_degeneracy_ratio`; this document uses the *raw per-candidate* ICP population (both current+next role per attempt, ~2 readings per attempt) checked against `match_class`+`near_tie` only (since `corridor_degeneracy_ratio` is confirmed, again, to never separate the populations — see §4). The two are related but not the same denominator or diagnostic set; both agree on the qualitative picture (roughly half the bad bucket is invisible to every diagnostic tried so far), which is the load-bearing conclusion, not the exact percentage.

---

## 4. What actually separates "confidently wrong" from clean — and what still doesn't

| feature | unexplained (n=1371) | clean ≤5° (n=5405) | separation? |
|---|---|---|---|
| `overlap_ratio` | median 0.767, p10 0.572 | median 0.934, p10 0.791 | **real, moderate** — lower but heavily overlapping ranges |
| `inlier_count` | median 314 | median 401 | **real, moderate** |
| `confidence` | median 0.787, p90 1.000 | median 1.000, p10 0.963 | **real** — but 10% of unexplained-bad readings still hit confidence=1.0 |
| `median_residual_m` | median 0.136 | median 0.060 | **real, ~2.3x** — the clearest single-feature gap found this session |
| `corridor_degeneracy_ratio` | median 0.793 | median 0.765 | **none** — confirms the standing 2026-07-05/07-08 finding, now on 9030 pooled readings |
| `yaw_peak_width_deg` (2026-07-10 diagnostic) | median 0.000 (n=711) | median 0.413 (n=2691) | **none / wrong direction** — confirms PROGRESS.md §6's negative result |
| `yaw_score_normalized_entropy` | median 0.978 | median 0.939 | **negligible** — both saturated near 1.0 |
| `true_dist_m` | median 0.808 | median 0.809 | **none** — error is not simply a function of how far the anchor is |

**New finding this session**: `confidence` and `median_residual_m` — two of the oldest, cheapest, already-logged scalar fields in the pipeline, never singled out as candidate signals in prior investigations — show the clearest separation of anything checked so far, clearer than `overlap_ratio` (previously the best-known signal per the 2026-07-05 Finding 3 entry). Neither is clean enough alone to gate on without real false positives (confidence still hits 1.0 for 10% of bad readings; residual's unexplained-population p10 of 0.063m overlaps clean's p90 of 0.095m), but a combined score (e.g. `median_residual_m / confidence`, or feeding both into the same kind of calibrated-evidence-model the 2026-07-09 survey already proposed for the promotion gate) is a concrete, cheap, not-yet-tried angle that doesn't require any new algorithm — it only requires looking at fields the pipeline already computes on every single attempt.

---

## 5. Not all of the "unexplained" bucket is catastrophic

Distribution of `bearing_err` within the 1371-reading unexplained bucket:

| range | n | % |
|---|---|---|
| [10°, 30°) | 582 | 42.5% |
| [30°, 60°) | 268 | 19.5% |
| [60°, 90°) | 123 | 9.0% |
| [90°, 120°) | 100 | 7.3% |
| [120°, 150°) | 138 | 10.1% |
| [150°, 180°) | 160 | 11.7% |

62% of the unexplained bucket is under 60° error; only 21.8% exceeds 120° (i.e. genuinely "backwards"). This means the "ICP confidently wrong" story is not uniformly a dramatic 180°-flip phenomenon — a majority of it is a more mundane "ICP's noise floor is higher than `clean_full_pose` implies" problem, coexisting with a smaller, more severe near-antipodal tail. Any future fix should be evaluated separately against these two sub-populations — a mechanism that only catches the severe tail (as short-baseline disambiguation was designed to, via a coarse ±20° threshold) will structurally never touch the larger, milder majority.

---

## 6. Within-run instability dominates over static wrong-answer bias

Grouping unexplained readings by `(batch, episode, anchor)` and restricting to groups with ≥5 readings (94 groups), and classifying by coefficient of variation (std/mean) of the bearing error within that group:

- **20/94 groups (21%) are "tight"** (cv < 0.3) — a consistent, close-to-deterministic wrong answer every time that anchor is queried within a run. The most extreme: `ep678` anchor7 (2026-07-12 only, n=10, mean=173.7°, std=1.9°) — essentially a perfect, stable ~180° antipodal flip, the cleanest textbook "genuine rotational symmetry" case found in either batch.
- **74/94 groups (79%) are "spread"** (cv ≥ 0.3) — the error swings substantially attempt to attempt at the *same* anchor within a single run, not settling on one wrong pose.

This matters for fix selection: a mechanism premised on "the anchor has one alternate strong local optimum that a second viewpoint would reveal as different from the first" (the short-baseline disambiguation design) is well-matched to the tight/deterministic minority, but the majority of bad anchors are not behaving that way — they look more like genuine attempt-to-attempt ICP instability (jittering between several candidate poses depending on subsampling/seed luck), which a single extra observation may not resolve any better than the first one did.

---

## 7. Cross-run persistence: a small, reproducible hard-anchor set

Restricting to the 6 episodes present in both batches (`4, 367, 368, 678, 994, 1040`) and requiring ≥3 unexplained readings with mean error >45° in **both** independently-launched batches:

| ep | anchor | 07-10 mean (n) | 07-12 mean (n) | note |
|---|---|---|---|---|
| 367 | 8 | 57.3° (50) | 57.3° (50) | **bit-identical — see §1 caveat, one trial not two** |
| 367 | 12 | 58.2° (5) | 58.2° (5) | bit-identical, small n — same caveat |
| 368 | 12 | 60.4° (24) | 134.9° (26) | **genuinely independent, both bad, got worse** — real evidence of a persistent but unstable failure mode |
| 4 | 11 | 48.3° (14) | 143.5° (3) | genuinely independent, both bad; 07-12 sample is small |

`ep368` anchor12 is the strongest evidence in this dataset of a real, reproducible, non-noise anchor-level defect: two independently-launched batches both find it badly wrong, with the specific error magnitude itself unstable (60°→135°) — consistent with §6's finding that most bad anchors are unstable rather than a single fixed wrong pose, even when the "is this anchor bad" verdict itself reproduces reliably.

**A caution on over-fitting to a single historical example**: `investigations/2026-07-09-.../FINDINGS.md` and the literature survey both used `ep1040`/anchor4 as the flagship "clean-but-wrong" poster child (there reported as dθ stably wrong 120–170°, from an offline-replay/oracle-geometry capture). In these two later live-batch (accumulated-geometry) runs, the same anchor shows mean error 14.9° (2026-07-10, n=89) and 31.4° (2026-07-12, n=43) — both far below its previously-documented severity. This does not mean the anchor is fixed; it means either the offline capture's oracle-geometry substitution genuinely differs from live accumulated geometry for this anchor, or (consistent with §6) this anchor's failure is itself unstable/intermittent rather than a fixed property. Either way: any future fix should be validated against the reproducible set above (especially `ep368` anchor12 and `ep678` anchor7), not solely against `ep1040`/anchor4, which does not reproduce at its originally-documented severity in current live data.

---

## 8. Summary table for future reference

| finding | status |
|---|---|
| >10° bearing error rate | stable at ~32.6% across two independent live batches |
| `corridor_degeneracy_ratio` as a discriminator | **dead, confirmed again** (no separation, n=9030) |
| `yaw_peak_width_deg` / `yaw_score_normalized_entropy` (2026-07-10 diagnostics) | **dead, confirmed again** (no separation, matches PROGRESS.md §6's offline finding, now also true live) |
| `confidence` / `median_residual_m` as discriminators | **new, real (moderate) separation — not yet exploited anywhere in the pipeline** |
| severity distribution of the unexplained bucket | 62% mild (<60°), only 22% severe (>120°) — not uniformly catastrophic |
| within-run stability of bad anchors | 79% unstable/spread, 21% tight/deterministic — majority is not a fixed alternate optimum |
| cross-run reproducible hard-anchor set | `ep367` anchor8/12 (same-trial caveat), `ep368` anchor12, `ep4` anchor11 (independent) |
| `ep1040`/anchor4 (prior flagship example) | does **not** reproduce at previously-documented severity in either live batch |

---

## Methodology notes / reproducibility

- Ground truth: trajectory JSONL per-step `position`/`quaternion_wxyz` (return-phase rows only) vs. anchor `metadata.world_pose`, both privileged eval-only fields never exposed to the VLM (`--route_hint_source=oracle` throughout).
- Row alignment: `row_idx = 0 if attempt==1 else (attempt-1)*route_relocalization_interval_updates-1`, `interval=5` for both batches — the same formula validated exactly in `investigations/2026-07-10-.../FINDINGS.md`.
- `ep1040`'s 2026-07-10 measurement JSON required repair before use: a duplicated-string-glue defect (`"direct_oracle_route_anchor""direct_oracle_route_anchor""shadow_source":` → `"direct_oracle_route_anchor", "shadow_source":`) and a dropped-key-before-colon defect (`"shadow_progress": {\n\n: "anchor_relocalization",` → the missing key is `"source"`, confirmed by diffing against an uncorrupted `shadow_progress` block elsewhere in the same file) — both are the same corruption classes already documented in `investigations/2026-07-10-.../FINDINGS.md` §1, not new corruption patterns.
- Scripts used for this analysis are included in this folder's `code/` subdirectory (`bearing_analysis_20260710.py`, `bearing_analysis_20260712.py`, `deep_dive_20260713.py`) for reproducibility, matching this project's established convention of snapshotting analysis code alongside its FINDINGS document.

## Next steps

1. Try a combined `median_residual_m` / `confidence` score as a cheap addition to the existing diagnostic set (§4) — this is genuinely new and untested, unlike `corridor_degeneracy_ratio` and the yaw-curve/yaw-observability diagnostics which are now confirmed dead twice over (offline in PROGRESS.md §6, live in this document).
2. Re-validate any future mechanism against the reproducible hard-anchor set in §7 (especially `ep368` anchor12 and `ep678` anchor7) rather than `ep1040`/anchor4, which no longer reproduces at its originally-documented severity.
3. Given §6's finding that most bad anchors are unstable rather than statically wrong, a mechanism that only fires on a single strong disagreement (as short-baseline disambiguation's ±20° gate does) will structurally miss most of this population — worth revisiting whether an averaging/sequence-consistency check across several attempts at the same anchor (not just two widely-separated viewpoints) would catch more of the unstable majority.
