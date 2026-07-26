# Stage-2 camera-yaw axis bug found+fixed, and a distance-agnostic confidence gate for it

Snapshot: `2026-07-26`. Follows `investigations/2026-07-25-representative-stage1-wrong-picks-under-1m/` (Stage-1 camera-pairing combo selection, now validated at 98-99% accuracy inside 2m via class-sum + margin gating). This session picks up the Stage-2 open thread flagged there and in `investigations/2026-07-25-loftr-rear-view-visual-diagnosis/SESSION_SUMMARY_PART2_CORRECTIONS.md`: "given a correctly-identified combo, does the LoFTR-match -> RANSAC/Kabsch rigid-transform solve compute an accurate rotation?"

## Bug found: `relocalization.py:246-250`, `camera_rotation_to_body_yaw()`

**Symptom.** A 10-sample pilot (hand-selected from `representative_dataset.json`, all Stage-1-correct at high class-sum margin, spanning 0.32-3.29m) showed the production Stage-2 output collapsing to ~0 deg / ~180 deg almost every time, regardless of the true relative yaw (which ranged 55-165 deg across the 10 samples).

**Root cause.** The function's final step extracts yaw as `atan2(v[1], v[0])` where `v = rotation_current_body_anchor_body[:, 0]` (anchor's forward axis expressed in current's frame) — i.e. it assumes a standard robotics body convention (X-forward, Y-left, Z-up), where yaw lives in the X-Y plane. But this project's actual saved `camera_rotation_body` extrinsic (confirmed by direct inspection of real capture data, e.g. `ep1062` anchor9: front camera's `camera_rotation_body` is the identity matrix) uses a camera-native convention (X-right, Y-down, Z-forward) as "body" for this field specifically — so the horizontal (yaw) plane is actually X-Z (indices 0, 2), not X-Y (indices 0, 1). Index 1 (the down axis) is analytically **always ~0** for a pure yaw rotation under this convention, so `atan2(~0, x)` can only ever return exactly 0 deg or exactly 180 deg — a hard mathematical collapse, not noise. This has been live since `_loftr_rear_yaw_check` was added 2026-07-13 (`investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/`), reusing this same function.

**Fix (validated, not yet applied to `relocalization.py`).** Extract yaw from indices `(2, 0)` instead of `(1, 0)`, plus a sign flip when the "current" side's view is the rear camera (found empirically — the rear extrinsic's effect on the composed matrix isn't a clean axis swap, it also inverts this component; direct cause not fully re-derived, but the correction is exact across every combo type tested):

```python
col0 = rotation_current_body_anchor_body[:, 0]
yaw = math.atan2(col0[2], col0[0])
if current_view is rear:
    yaw = -yaw
```

**Critically, the underlying LoFTR match + RANSAC/Kabsch fit is NOT the problem** — the raw camera-to-camera rotation's own yaw component (extracted before body-frame composition) already matches the true geometric alignment angle to within ~1-2 deg on every sample tested. The bug is entirely in this one coordinate-frame conversion step.

## Validation at scale (249 samples, `code/stage2_probe_largescale.py`)

Stratified sample from `representative_dataset.json` (Stage-1-correct-class, margin>=0.4), 249 usable, spanning 0.32-6m+ (35% at 0-1m, 30% at 1-2m, 20% at 2-3m, 15% at 3m+):

| | production (buggy) | fixed |
|---|---:|---:|
| median error | 17.4 deg | **0.33 deg** |
| mean error | 23.7 deg | 4.98 deg (tail-dragged) |
| p90 error | 51.2 deg | 2.13 deg |
| frac < 5 deg | 16.9% | **91.2%** |
| frac < 15 deg | 43.8% | 92.0% |
| frac < 30 deg | 69.1% | 93.6% |

By true distance (fixed formula only):

| distance | n | median err | frac < 5 deg |
|---|---:|---:|---:|
| 0-1m | 87 | 0.22 deg | 96.6% |
| 1-2m | 75 | 0.36 deg | 94.7% |
| 2-3m | 50 | 0.35 deg | 90.0% |
| 3m+ | 37 | 0.45 deg | 73.0% (mean 17.8, p90 79.3 — real tail starts here) |

Confirms the 10-sample pilot's fix generalizes cleanly, not a coincidence. The median stays excellent even past 3m; what degrades is the *fraction* of samples with a large-error tail, i.e. Stage-2 needs its own confidence gate, same as Stage-1 did.

## A distance-agnostic confidence signal: RANSAC fit residual

**Raw match count does NOT reliably detect "different room, no shared view."** Checked against the full representative dataset (9244 samples): median max-combo LoFTR match count decays smoothly with distance (1233 -> 480 -> 267 -> 208 -> 167 -> 146 for 0-1/1-2/2-3/3-4/4-6/6m+) but **never drops toward zero**, even at 6m+ — LoFTR keeps finding hundreds of matches between images that are very likely different rooms, almost certainly on repeated textures/architecture (walls, floor, lighting), not genuine correspondence.

**`median_residual_m`** (the post-RANSAC 3-D point-cloud alignment residual, already computed by the existing pipeline, no new cost) is a much cleaner signal — it smoothly tracks true distance (median 0.014m at 0-1m -> 0.026m -> 0.031m -> 0.044m at 3-4m -> 0.163m at 4m+, though the 4m+ bucket is only n=1, thin) because it measures geometric self-consistency across *all* inlier matches simultaneously, which spurious textural matches can rarely fake at scale.

Gating on `median_residual_m <= 0.06`, on the 249-sample set:

| distance | n | kept | kept frac < 5 deg |
|---|---:|---:|---:|
| 0-1m | 87 | 99% | 96.5% |
| 1-2m | 75 | 91% | 98.5% |
| 2-3m | 50 | 88% | 95.5% |
| 3m+ | 37 | 65% | 95.8% |

Overall: 89.2% coverage, 96.8% of kept samples < 5 deg error. The gate is not just crudely correlating with distance (it doesn't just reject "everything past 2m") — within *every* distance bucket the samples it keeps are consistently ~95-98% accurate, and it correctly thins out coverage exactly where the raw-fixed-formula tail lives (3m+: 65% kept vs. 99% at 0-1m).

## Correction: "confidently wrong" is reduced, not eliminated, in vision

Checked explicitly (not assumed) whether the residual gate has its own confidently-wrong failures: among the 222 samples passing `resid<=0.06`, **4 (1.8%) still have >=30 deg error.** Worst case: `ep844 anchor7 step1425`, combo `anchorFront_currentFront`, **distance=0.00m** (robot essentially co-located with the anchor), `inlier_count=3226/3227` (~100% inlier ratio), `median_residual_m=0.0015` (an order of magnitude better than the already-good 0-1m median) — by every existing signal this is the single most "confident" reading in the whole 249-sample set, yet the computed yaw is wrong by 43.8 deg.

Likely mechanism (not yet root-caused in depth): near-zero baseline/parallax between the two camera positions leaves rotation under-observable from point correspondences alone — Kabsch SVD can converge to a low-residual rotation that isn't the true one when the two point clouds are captured from almost the same viewpoint, regardless of how many points are matched. This is an extension of the already-documented "close-range camera-offset artifact" (<0.3-0.5m, `SESSION_SUMMARY_PART2_CORRECTIONS.md`'s ep688/ep490 cases), now confirmed at the more extreme 0.00m case with a concrete counter-example to "confident implies correct."

**Bottom line: vision's confidently-wrong rate under the residual gate (~1.8% of gated samples) is far lower than LiDAR/ICP's (96.7% of return failures are confidently-wrong ICP per `investigations/2026-07-24-confidently-wrong-open-problem-summary/`), but it is not zero** — the near-zero-distance/parallax-degenerate case is a distinct, identifiable failure mode worth a separate guard (e.g. a minimum-baseline sanity check), not something the residual gate alone can catch.

## Fix applied to production (`relocalization.py`, same day)

The `camera_rotation_to_body_yaw` fix described above is now live in `NaVILA-Bench/scripts/relocalization.py` (snapshot: `code/production_snapshot/relocalization.py`). Implementation notes:
- Branches on whether `descriptor_camera_to_body()` returned real extrinsics (`(2, 0)`-axis formula + rear-side sign flip) vs. the missing-data fallback (`(1, 0)`-axis formula, unchanged) — the fallback matrix and real captured data turned out to use genuinely incompatible axis conventions, not just a sign difference, so both paths are kept explicit rather than unified into one formula.
- `tests/test_geometry_pipeline.py`'s `TestCameraRotationToBodyYaw.test_extrinsic_camera_axes_extract_anchor_yaw` was rewritten to use real captured-data fixtures (rotation matrices verbatim from this investigation's own samples) instead of a synthetically-composed scenario — a first attempt at a fully synthetic multi-combo sweep (200 random trials) silently re-introduced the *same* axis-convention mistake one level up (composing a world-yaw rotation with the real extrinsic via the wrong axis), which is exactly the trap this whole investigation started from. Real-data fixtures sidestep needing to re-derive that composition at all.
- Full suite re-run: `tests/test_geometry_pipeline.py` + `tests/test_route_memory_agent.py` = 229 tests, 14 pre-existing skips (unchanged baseline), zero regressions.
- Re-validated the *production function itself* (not the standalone probe scripts) against the same 249-sample stratified set: median error 0.33 deg, 91.1% < 5 deg — matches the probe-script numbers above exactly, confirming the deployed fix behaves identically to what was validated.

`_loftr_rear_yaw_check` itself is still hardcoded to one combo (anchor-rear vs. current-front) and still diagnostic-only (`--sequential_pair_loftr_rear_yaw_check`, off by default) — generalizing it to try all 4 combos and attach the Stage-1 margin gate + Stage-2 residual gate is the next planned step (see below), not done yet.

## `_loftr_rear_yaw_check` generalized (same day) + validated directly against ICP's `confidently_wrong` flag

`_loftr_rear_yaw_check` now tries all 4 combos, applies the Stage-1 class-sum margin gate to pick the winning class (tie-broken by match count within the class), runs Stage-2 on the chosen combo via the fixed `camera_rotation_to_body_yaw`, and applies the residual gate — returning `vision_gate_passed` plus `stage1_margin`, `chosen_combo`, `median_3d_residual_m`. Still diagnostic-only (off by default), but now actually produces meaningful output for the first time.

**Validation (`code/vision_vs_confidently_wrong.py`): all 259 genuine `confidently_wrong` ICP samples in `representative_dataset.json`, vs. a same-size random control sample of `confidently_wrong=False` cases.**

| | confidently_wrong (n=259) | control (n=259) |
|---|---:|---:|
| median true distance | 1.44m | 3.03m |
| vision_gate_passed | 47.5% | 27.4% |
| accuracy among gate-passed | **63.4% < 5°** | 97.2% < 5° |

The gap (63.4% vs. 97.2%) looked at first like vision genuinely struggling on the hard cases. Breaking it down by distance fully explains it, and reveals something more specific and more important:

**The entire gap is one sharp, narrow failure band: true distance < 0.01m (robot essentially exactly at the anchor).** Among gate-passed confidently-wrong samples: at distance < 0.01m, accuracy is **4.4%** (median error 54°, n=45) — the vision gate is not just unhelpful here, it's confidently wrong itself. At distance >= 0.01m, accuracy is **97.4%** (n=78) — matching the general-population rate from the 249-sample validation almost exactly.

**Critically, `confidently_wrong` ICP cases are disproportionately concentrated in exactly this same near-zero-distance band: 17.4% of all 259 confidently-wrong samples have true distance < 0.01m, vs. 0/259 (0%) of the control sample.** This means the near-zero-baseline/parallax degeneracy found earlier (`ep844 anchor7`) is not a rare 1.8% edge case — it is a real, physically-grounded, **shared blind spot between LiDAR ICP and vision**: near-zero translation makes rotation recovery ill-conditioned for both modalities' math (ICP's point-cloud alignment and vision's Kabsch SVD), for related but not identical reasons. This is a materially different conclusion from this morning's framing ("confidently-wrong reduced but not eliminated, ~1.8%, isolated case") — at the intersection with ICP's own confidently-wrong failures specifically, the shared blind spot accounts for over a third of the accuracy gap, not a rare fluke.

**Attempted a self-contained (no ground-truth) guard using vision's own estimated distance** (`hypot(loftr_rear_dx_m, loftr_rear_dy_m)`, already free from the existing RANSAC translation output) as an extra gate. It does NOT cleanly separate the bad cases at the true ~1cm boundary — vision's own distance estimate is itself unreliable in exactly this regime (median |estimate - true| = 0.10m, p90 = 0.75m, among confidently-wrong gate-passed samples). A threshold conservative enough to reliably exclude the bad band (>=0.15-0.20m) recovers 95-96% accuracy but rejects ~60% of the confidently-wrong gate-passed samples to do it, vs. the ~37% an oracle (ground-truth) threshold would need to reject. Not yet resolved which threshold (if any) is the right practical tradeoff.

**Bottom line for the confidently-wrong-ICP suppression effort:** outside the near-zero-distance band, this vision cross-check is genuinely strong evidence (97%+ agreement-when-available on exactly the hardest ICP cases, the target this whole effort cares about). Inside the band (roughly 1 in 6 confidently-wrong cases), neither modality's rotation estimate should be trusted — this needs a different mitigation (e.g. an independent "is translation near-zero" signal, or accepting it as a known hard floor) rather than expecting vision to rescue it.

## Pending / next steps

1. Decide on a practical near-zero-baseline guard (threshold tradeoff above still unresolved) before proposing vision as a cross-check signal to any consumer.
2. The 4m+ distance bucket has only 1 sample in the original 249-sample validation — too thin to confirm the residual-gate's behavior holds at longer range; worth a targeted larger sample there.
3. Root-cause *why* `confidently_wrong` ICP concentrates so heavily at true distance < 0.01m (17.4% of the whole confidently-wrong population) — is this a specific recurring behavior, e.g. the robot re-approaching/hovering at an anchor during return, or an artifact of how attempts are sampled?
4. How to combine the Stage-1 margin gate + Stage-2 residual gate + a resolved near-zero-baseline guard into the project's broader confidently-wrong-ICP suppression effort (independent cross-check vs. replacement signal vs. fused score) — still open, now better-scoped than this morning.
5. Per the user's clarification 2026-07-26: this project runs two parallel tracks. This session (Route 1) is the non-model geometry/vision-matching pipeline; a separate Codex-run track (Route 2) trains/uses a model to directly judge ICP-reading trustworthiness (`investigations/2026-07-26-v2-integrated-anchor-state/` and related). The two tracks are independent; this investigation folder is Route 1 only.
