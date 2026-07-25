# 2026-07-25 Session, Part 2 — Methodology Corrections, Stage-1/Stage-2 Split, and Representative Dataset Rebuild

**Author**: Claude (Route 1)
**Status**: in progress -- a background data collection job is running as of this writeup; see §5 for current state and how to pick this up.

This document continues `SESSION_SUMMARY.md` (same folder, written earlier today) and `FINDINGS.md` (the original 5-image visual diagnosis). Part 1 covered candidate reachability, the LiDAR-only-fixes-are-closed finding, and a long sequence of Stage-1 selector attempts (match count, cross-combo/cross-modal agreement, 3D spatial degeneracy, four flavors of global image descriptor including SALAD and a self-built AnyLoc-style VLAD vocabulary). **Two significant methodology errors were found and corrected during Part 2, described below — both materially change how Part 1's numbers should be read.** This document exists specifically so the corrections aren't lost or re-discovered the hard way by whoever picks this up next.

---

## 1. Error #1: Stage-1/Stage-2 conflation in every "selector accuracy" number from Part 1

**The mistake:** every selector-accuracy figure reported in Part 1 (e.g. "match-count selector: 4%", "SALAD: 5-6% as a selector") used the label *"correct" = the selected combo's final RANSAC-solved bearing is within 30° of ground truth*. This conflates two genuinely independent things:

- **Stage 1** — did the selector pick the camera-pairing combo that actually has real image overlap with the anchor (the "look toward the same place" question)?
- **Stage 2** — given that correct combo, did the LoFTR-match → RANSAC/Kabsch rigid-transform solve compute an accurate rotation?

**How this was caught:** the user pushed back specifically on case E (`FINDINGS.md`), arguing the two images looked too obviously different to need something as heavy as AirRoom. Re-checking case E's *other* 3 camera-pairing combos (not the one originally visualized) showed `anchorFront_currentFront` genuinely depicts the same bedroom (same bed, chair, window — visually confirmed) yet still has a 65° bearing error — i.e. Stage 1 succeeded, Stage 2 didn't. The same pattern was then confirmed on cases B and D (both already had a combo with correct Stage-1 identity), and independently on cases 03/04/06 from the "10 cases for review" folder, where combos with 500-2400 RANSAC inliers (overwhelming evidence of genuine overlap) *still* failed the 30°-bearing threshold.

**The fix:** built a **pure-geometry Stage-1 ground truth** with zero dependency on any vision/matching output — `stage1_ground_truth_eval.py`. Exploits a known, verified simulator constant (each robot's rear camera is exactly 180° rotated from its front camera in the body frame — confirmed numerically earlier today: 179.97°). So each of the 4 candidate views' WORLD heading is just `body_world_yaw` (+180° for rear), computable directly from oracle position/orientation data alone. For a candidate pairing, its "alignment angle" = the angular difference between the two views' world headings; the combo with the smallest alignment angle is the ground-truth-predicted correct one. Distance is handled as a separate axis (see §2), not folded into this.

**Re-evaluating the same 100 confidently-wrong samples against this clean ground truth** (`stage1_selector_eval.py`) gave dramatically different numbers than Part 1's 4-9%:

| Selector | Stage-1 accuracy (clean) |
|---|---|
| AnyLoc-VLAD (self-built vocabulary) | **71.0%** |
| LoFTR match-count | **69.0%** |
| SALAD | 63.0% |
| DINOv2-patchmean | 55.0% |
| DINOv2-CLS | 49.0% |
| ResNet18 (ImageNet) | 37.0% |

(4-way chance baseline = 25%.) **Stage 1 is not a near-random, "confidently wrong" problem the way Part 1 concluded — several already-tested methods clear it reasonably well.** Stage 2 (precision given a correctly-identified combo) is a real, separate, previously under-characterized problem — cases 03/04/06 show it failing even with hundreds of high-quality inliers, for reasons not yet root-caused (a related, not-yet-fully-explained close-range camera-offset artifact was found earlier at <0.3-0.5m — see `FINDINGS.md`'s ep688/ep490 cases — but 06 at 1.42m shows the same pattern at a distance where that specific artifact shouldn't dominate, so there is likely a second, distinct Stage-2 precision issue still unexplained).

**Caveat on the table above, found immediately after:** see Error #2 — this same table also inherited an unrepresentative sample.

---

## 2. Error #2: the 100-sample "confidently_wrong" set used all session is not representative

**The mistake:** every experiment in Part 1 (candidate reachability, the 4-pairing test, all selector attempts, the table above) ran on the same 100-sample set built at the very start of today's session. That set was constructed by taking the **30-episode "known confidently-wrong" catalogue from the 2026-07-24 `RESEARCH_BRIEF.md`** (itself derived from the *older* `reliability_fixon_100ep_20260721` / `reliability_v11_prospective_capture_shadow_100ep_20260722` batches, not fresh from yesterday's run), matching 21 of those 30 anchors to yesterday's `reliability_v11_decision_shadow_rgbd_100ep_20260724` RGB-D captures (same frozen episode manifest), then subsampling up to 120 return-phase steps per anchor. **This is a pre-selected sample of already-known-hard anchors, not a random or representative cross-section of the full 100-episode run** — and within it, one single anchor (episode 785, anchor 8) contributed 76/100 "confidently_wrong" samples.

**How this was caught:** the user noticed the near/far distance-binned accuracy table showed a suspicious monotonic-looking trend (far range = higher accuracy) and asked why, given yesterday's run has ~100 episodes worth of data, one distance bin ended up dominated by a single anchor. Checking anchor composition per distance bin confirmed: the 1-2m bin was 69/70 samples from anchor 785/8 alone; the >3m bin was 14/16 from anchor 18/3 alone. A controlled test holding environment fixed (785/8 only, varying just distance within it) found **no real distance effect** (point-biserial r=0.041, p=0.724, non-monotonic) — the apparent "far=better" pattern in the pooled table was an anchor-identity confound, not a distance effect. This means **every number in §1's table, and everything in Part 1, describes the behavior of a handful of specific, pre-selected anchors — dominated by one of them — not the general behavior of the pipeline across the run.**

**The fix, currently running:** `representative_dataset_build.py`, launched as a `systemd-run --user` background service (`navila-representative-dataset-build.service`, survives session disconnect per this project's established practice) at 2026-07-25T15:51 BST. Scope:

- **All 58 usable episodes** of the 100-episode run (42 excluded: 37 legitimately have no return-phase data at all because outbound failed — `finalize_outbound()`/anchor capture never fires for those, this is expected, not a bug; ~3-5 are genuine data issues — timeout `ep428`, at least one corrupted `anchors.json` on `ep95` — small enough to not matter).
- **All 676 anchors** across those 58 episodes (not just 21 pre-selected ones), avg 11.7 anchors/episode.
- 15 return-phase steps sampled per anchor (evenly spaced, stride-5 to match relocalization cadence).
- Per sample, computes: (a) the pure-geometry Stage-1 ground truth from §1, (b) LoFTR match-count Stage-1 pick, (c) a genuine ICP-24-seed `confidently_wrong` flag (same methodology as the original `replay.py`), so the eventual analysis can report Stage-1 accuracy on the full representative sample AND, separately, restricted to whichever subset turns out to be genuinely confidently-wrong within it — per the user's explicit instruction to build the general baseline first, not start from the hard cases.
- Checkpoints after every anchor (writes `representative_dataset.json` incrementally) — safe to inspect or resume mid-run.
- ETA ~3.5 hours from launch (smoke-tested at ~1.26s/step before launching the full run).

---

## 3. What still stands from Part 1 (not affected by either error)

- **LiDAR-only fixes are closed** (§1.1-1.2 of `SESSION_SUMMARY.md`): candidate reachability (recall@4=3%, recall@24=20%) and the global-registration diagnostic (dense 72-seed sweep only finds 5% more; ground-truth-seeded ICP scores competitively only 2.5% of the time even with oracle seeding) are both independent of the Stage-1/Stage-2 split and independent of the anchor-representativeness issue, since they test the LiDAR objective function's own structural behavior, not a selector's accuracy against a possibly-skewed sample. This conclusion holds.
- **The two visual failure mechanisms** identified in `FINDINGS.md` (majority: wrong camera pairing chosen because "current-front ≈ anchor-rear" only holds near dtheta≈180°; minority: genuine repetitive-texture self-similarity, case C) are still valid qualitative findings, though their *relative proportion* in a representative sample is now unknown pending §2's rebuild.
- The finding that **generic architectural features (ceiling corners, doorframes) and same-house consistent wall/floor materials both cause spurious high-confidence matches between genuinely different rooms** (cases B and the ep18/step4590 material-confusion example) is architecturally important and unaffected by the sampling issue — these are real, demonstrated failure modes, just not yet known to be the *typical* case.

## 4. What needs to be re-run or re-checked once §2's job completes

1. Recompute §1's Stage-1 accuracy table on the representative sample, both overall and restricted to the newly-and-properly-identified confidently-wrong subset.
2. Re-run the SALAD / AnyLoc-VLAD embeddings (only match-count is being collected in the background job to keep it lighter; embeddings can be added as a fast follow-up pass over the same cached anchor/step data if the representative sample confirms they're worth re-testing).
3. Only after Stage 1 is properly characterized on a representative sample: investigate the still-unexplained Stage-2 precision failures (cases 03/04/06 — high-inlier-count combos still failing the 30° threshold) as an independent question, since conflating it with Stage 1 was exactly today's first mistake.
4. Reassess whether AirRoom (or any heavier object-aware model) is actually justified, now that Stage 1's true difficulty is being measured properly — Part 1's case for AirRoom was built partly on selector-accuracy numbers now known to be contaminated by both errors above.

## 5. Current state (for anyone resuming this)

- Background job `navila-representative-dataset-build.service` is running under `user@1006.service` (verified in-cgroup, survives disconnect). Check with `systemctl --user status navila-representative-dataset-build` and `tail representative_dataset_build.progress.log`.
- Output accumulates in `representative_dataset.json`, one anchor's worth of samples appended at a time — safe to read mid-run for a partial/preliminary look.
- All Part-1 scripts, intermediate results, and the 10-case visual review grids remain in this investigations folder's history for reference; none of the *code* was wrong, only the sampling scope and the correctness-label definition used to interpret its output.
