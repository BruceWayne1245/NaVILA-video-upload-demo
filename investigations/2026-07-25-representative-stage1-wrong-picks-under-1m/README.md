# Representative Stage-1 evaluation + 10 close-range (&lt;1m) wrong picks

Snapshot: `2026-07-25T19:20+01:00`. Follows `investigations/2026-07-25-loftr-rear-view-visual-diagnosis/` (which first flagged the Stage1/Stage2 metric conflation and the unrepresentative-sample problem).

## Representative dataset

Built by `representative_dataset_build.py` (`systemd-run --user` service `navila-representative-dataset-build.service`, ran 15:51-18:39 same day), covering **all 676 anchors across all 58 usable episodes** of the `reliability_v11_decision_shadow_rgbd_100ep_20260724` run — not the earlier 21 pre-selected "known-bad" anchors (which had 76/100 samples from a single anchor, 785/8). Per (anchor, sampled return-phase step) pair it computes:
- pure-geometry Stage-1 ground truth (`gt_best_combo`): the camera-pairing combo (anchor-front/rear × current-front/rear) with the smallest world-heading alignment angle — independent of any vision matching.
- the match-count selector's own pick (`match_count_pick`): whichever of the 4 combos gets the most LoFTR matches.
- a genuine ICP "confidently_wrong" flag from the real 24-seed `icp_seed_sweep_2d` production sweep.

**9244 samples, 58 episodes, 618 anchors with at least one usable sample.** Genuine confidently-wrong incidence: 259/9244 = 2.8%, spread across 117 distinct anchors (max single-anchor share 4.2%) — confirms the earlier 76%-from-one-anchor sample was severely unrepresentative on this axis too, not just the distance-vs-anchor confound found earlier.

## Stage-1 match-count selector accuracy (corrected, representative)

| Subset | n | accuracy | chance |
|---|---:|---:|---:|
| full representative sample | 9244 | **36.3%** | 25.0% |
| confidently-wrong subset | 259 | **39.8%** | 25.0% |
| NOT confidently-wrong subset | 8985 | 36.2% | 25.0% |

By distance (full sample):

| distance bin | n | accuracy |
|---|---:|---:|
| 0-1.0m | 1726 | 48.3% |
| 1.0-2.0m | 1750 | 44.3% |
| 2.0-3.0m | 1488 | 37.7% |
| 3.0m+ | 4280 | 27.6% |

**This supersedes the same-day earlier "match-count 69%" correction number.** That number was computed correctly (Stage1/Stage2 metrics not conflated) but still on the old unrepresentative 21-anchor/100-sample set. On the full representative set, real Stage-1 accuracy is **36.3% overall / 39.8% on genuinely confidently-wrong cases** — well above chance (25%), but far below 69%. The distance trend (accuracy falls from 48% near to 28% far) now spans 117+ distinct anchors in the confidently-wrong subset and 618 anchors overall, so it is much less likely to be a single-anchor confound than the similar-looking trend rejected earlier this session.

## 10 close-range (&lt;1m) wrong picks

At close range (&lt;1m GT distance) genuine overlap should be geometrically easy, yet the match-count selector still gets it wrong 893/1726 times (51.7% error rate in this bin). Below are 10 hand-selected cases, one per distinct episode for diversity (script: `wrong_pick_under1m_selection.json` picks the first qualifying sample per episode, seeded shuffle for order), each rendered as all 4 camera-pairing combos (`render_wrong_pick_under1m.py`) with the ground-truth combo and the algorithm's picked combo labeled directly on the image.

| case | episode | anchor | step | GT distance (m) | GT best combo | match-count picked |
|---|---:|---:|---:|---:|---|---|
| 1 | 28 | 12 | 3460 | 0.725 | anchorRear_currentFront | anchorFront_currentRear |
| 2 | 355 | 12 | 3215 | 0.816 | anchorFront_currentRear | anchorRear_currentFront |
| 3 | 613 | 14 | 4525 | 0.657 | anchorFront_currentFront | anchorRear_currentRear |
| 4 | 658 | 5 | 2520 | 0.459 | anchorRear_currentFront | anchorFront_currentRear |
| 5 | 682 | 4 | 1115 | 0.068 | anchorRear_currentFront | anchorFront_currentRear |
| 6 | 698 | 13 | 2935 | 0.560 | anchorRear_currentRear | anchorFront_currentFront |
| 7 | 762 | 1 | 1695 | 0.718 | anchorRear_currentFront | anchorFront_currentRear |
| 8 | 888 | 6 | 2300 | 0.186 | anchorRear_currentFront | anchorFront_currentRear |
| 9 | 890 | 8 | 2815 | 0.216 | anchorRear_currentFront | anchorFront_currentRear |
| 10 | 1062 | 9 | 2390 | 0.588 | anchorFront_currentRear | anchorRear_currentFront |

**Pattern visible in the table alone:** in 9/10 cases the selector picked the combo that is front/rear-flipped on *both* sides relative to ground truth (e.g. GT `anchorRear_currentFront` vs. picked `anchorFront_currentRear`) — i.e. it consistently prefers the geometrically "opposite" pairing to the correct one, not a random wrong answer.

**Visual spot-check of 2/10 cases (case 1, case 5) gives two different verdicts, not one uniform bug:**
- **Case 1 (ep28 anchor12, distance 0.725m) is a clear-cut selector error.** GT combo (`anchorRear_currentFront`) shows the same hallway/paintings on both sides — genuine overlap. The picked combo (`anchorFront_currentRear`) pairs the anchor's hallway view against a completely different, darker current-REAR scene — no real overlap at all. The selector picked a visually wrong match here.
- **Case 5 (ep682 anchor4, distance 0.068m — almost exactly on top of the anchor) is a genuine near-tie, not an obvious error.** Because the robot is essentially at the anchor's exact position, *both* crossed pairings show strong real overlap: GT's `anchorRear_currentFront` shows the same bedroom-with-blue-drape room on both sides, but the picked `anchorFront_currentRear` also shows the same bathroom scene on both sides. Only the exact heading-alignment angle favors GT; a human glancing at the picked pair would not obviously call it wrong.

So the "always picks the flipped combo" pattern is real, but its severity varies: sometimes it's a genuine visual mismatch (case 1), sometimes both the GT and the picked combo are simultaneously valid matches for different room-pairs and only the geometric alignment angle breaks the tie (case 5) — consistent with a locally symmetric/self-similar layout (e.g. a straight corridor or a small room where front and rear both open onto plausible-looking space). The other 8 cases have not been visually checked yet; do not assume either verdict generalizes without looking.

Image files (`case0N_epE_anchorA_stepS.png`, 4-row grid: FF/FR/RF/RR pairings, anchor side left / current side right, `[GROUND TRUTH]` and `[ALGORITHM PICKED]` tags on row titles):
- `case01_ep28_anchor12_step3460.png`
- `case02_ep355_anchor12_step3215.png`
- `case03_ep613_anchor14_step4525.png`
- `case04_ep658_anchor5_step2520.png`
- `case05_ep682_anchor4_step1115.png`
- `case06_ep698_anchor13_step2935.png`
- `case07_ep762_anchor1_step1695.png`
- `case08_ep888_anchor6_step2300.png`
- `case09_ep890_anchor8_step2815.png`
- `case10_ep1062_anchor9_step2390.png`

## Open thread

The 9/10 "flipped-combo" pattern suggests the match-count selector (or the underlying front/rear descriptor construction) may have a systematic front/rear-confusion bias, not just noisy per-case matching — worth checking directly against `build_rear_view_descriptor` and whether match counts are somehow symmetric/uninformative between a combo and its front/rear-flipped counterpart. Not yet investigated; visual inspection of the 10 images above is needed to confirm whether the "flipped" combo genuinely looks similar to a human (a real visual aliasing case) or whether this is a bug in how combos are being scored/labeled.
