# LoFTR Rear-View Independent Pose Estimate — Root-Cause Visual Diagnosis

**Date**: 2026-07-25
**Author**: Claude (Route 1)
**Status**: preliminary, needs human judgment call on the images before deciding next step

## Context

Following up on `investigations/2026-07-24-confidently-wrong-open-problem-summary/`:
this session (1) ran the offline candidate-reachability replay confirming
recall@4≈3% / recall@24≈20% on ground-truth-verified confidently-wrong
attempts, (2) ran a global-registration-style diagnostic (dense 72-seed
sweep + ground-truth-seeded ICP convergence) showing that even with a
perfect oracle seed, the correct pose scores competitively against the
wrong one in only **2/80 (2.5%)** cases — i.e. pure LiDAR point-to-point
ICP, however searched, will not reliably prefer the correct answer; this is
an objective-landscape problem, not a search-coverage problem, (3) tested
an anchor self-rotational-symmetry prescreening score, which had **zero**
discriminative power (AUROC 0.475) between the 18 known confidently-wrong
anchors and 54 control anchors.

That leaves vision as the only untested-and-not-yet-ruled-out direction.
`relocalization.py`'s `_loftr_rear_yaw_check` (built 2026-07-13, designed as
the fix in `investigations/2026-07-23-confidently-wrong-convergence-and-vision-path/FINDINGS.md`
§6.1, but never executed against real data until today) pairs the anchor's
**rear** camera view against the current robot's **front** camera view
(LoFTR feature matching + depth backprojection + RANSAC rigid transform),
independent of ICP's LiDAR candidates entirely.

## What was measured today (numeric, before this visual pass)

- Confidently-wrong subset (n=100): LoFTR-rear correct (bearing err ≤30°) in **9%**.
- ICP-already-correct control subset (n=64): LoFTR-rear correct in only **14%**.
- Switching from kornia's `outdoor` to `indoor` pretrained LoFTR weights barely moved either number (10% / 25%) — rules out pretrained-weight domain gap as the dominant cause.
- Camera extrinsics were verified numerically sane (front/rear body-frame rotation differs by 179.97°, as expected).
- A 7-case "closest physical approach" sanity set (robot standing within 0.15-0.4m of the anchor — should be the easiest possible case) scored **0/7 correct**, with suspiciously huge, near-100% RANSAC inlier ratios in several cases.

## What the visualizations show (this pass)

Five hand-picked cases, LEFT = anchor's rear-camera RGB, RIGHT = current step's front-camera RGB, green lines = RANSAC inliers, red = LoFTR matches that failed the RANSAC/depth-validity filter:

| File | Case | Ground-truth `dtheta` | Result |
|---|---|---|---|
| `A_best_correct_hit_ep785_anchor8_step1665.png` | best correct hit in the sample | **150.4°** (near 180°) | correct (28.0° error), scenes visually consistent (same corridor) |
| `B_typical_wrong_ep18_anchor3_step3255.png` | typical confidently-wrong case | **-72.5°** (far from 180°) | wrong (35.0° error); LEFT is a stairway/lobby, RIGHT is a completely different lounge/bar area |
| `C_closest_approach_huge_inliers_ep87_anchor6_step2190.png` | "should be trivial" closest-approach case | **170.7°** (near 180°) | wrong (98.2° error) despite 2103/2131 (98.7%) RANSAC inliers; both views show **repetitive parallel ceiling-beam structure** — a visual analogue of the LiDAR "corridor degeneracy" problem |
| `D_closest_approach_normal_inliers_ep814_anchor5_step1985.png` | "should be trivial" closest-approach case | **-68.5°** (far from 180°) | wrong (95.5° error); LEFT and RIGHT show different, non-overlapping areas of the building |
| `E_control_easy_but_loftr_wrong_ep490_anchor6_step2310.png` | ICP-already-correct control step | **77.8°** (far from 180°) | wrong (122.3° error); LEFT is a closet/bathroom area (with a visible texture/geometry render glitch on the wardrobe), RIGHT is clearly a bedroom — different rooms |

## Preliminary interpretation (needs human confirmation)

A clean pattern across all five: **when ground-truth `dtheta` is close to 180°, the anchor-rear and current-front views show genuinely overlapping/related physical content; when `dtheta` deviates meaningfully from 180°, the two views show unrelated parts of the building entirely** — at which point LoFTR is being asked to match two images of different rooms, and any resulting "match" (however many keypoints, however high the RANSAC inlier ratio) is geometrically meaningless by construction, not a matching-quality failure.

This would mean the dominant root cause is **not** a pretrained-weight domain gap and **not** obviously a pose-solving code bug (case B/D/E's matches look self-consistent within each unrelated-room pair, which is exactly what you'd expect from RANSAC finding *a* locally-consistent-looking transform among noise) — it is that **the fixed "anchor-rear ≈ current-front" pairing assumption only holds when the robot's current heading happens to be close to 180° from the anchor's original outbound heading**, and this project's confidently-wrong failures are concentrated at **multi-door turn-around junctions** (per `RESEARCH_BRIEF.md` §2) — exactly the geometry where a robot's heading is least likely to hold a stable 180° relationship to its outbound heading at that same anchor.

Case C is a secondary, independent finding: even when the pairing assumption *does* hold (dtheta near 180°), highly repetitive local texture (parallel ceiling beams) can still produce a confidently-wrong visual match — a direct visual-domain analogue of the LiDAR "confidently wrong" problem this whole investigation is about, worth keeping in mind as a residual failure mode even if the pairing-geometry issue above is fixed.

## Open question for the human reviewer

Do these five images support the "pairing-geometry breaks down away from dtheta≈180°" reading, or is there a different/additional explanation visible in the images (e.g. does case B/D/E's matching look more like a genuine bug — matches pointing at clearly non-corresponding objects *within* a plausible single scene — rather than "two unrelated rooms entirely")? This determines whether the next step should be:
(a) **dynamic camera-pair selection** informed by whatever rough heading estimate is available (even a noisy one), instead of a fixed rear/front pairing — directly addresses the dtheta-dependence finding; or
(b) a **deeper pose-solving code audit** if the images instead suggest a convention bug once dtheta is accounted for; or
(c) treating this as further evidence that vision, at least via this specific mechanism, has a narrower operating envelope than assumed, and re-weighing the whole vision-vs-not decision.
