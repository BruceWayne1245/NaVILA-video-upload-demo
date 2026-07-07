# ICP Bearing / Rotation Error Investigation: Literature and Open-Source Survey

**Date:** 2026-07-07  
**Project:** Round-Trip LiDAR / Route Memory for Round-Trip VLN  
**Focus:** After the route-memory relocalizer has selected the approximately correct anchor, how can we detect and mitigate unreliable ICP bearing / yaw estimates?

---

## 0. Executive Summary

The current open problem is no longer primarily **anchor identity aliasing**. The 2026-07-06 investigation already addressed the anchor-promotion cascade with `bounded_evidence` and `alias_aware` promotion. The remaining issue is different:

> Once the shadow relocalizer has selected the approximately correct anchor, the reported **bearing / yaw** from ICP can still be badly wrong on a minority of anchors, sometimes by 50–180 degrees, while the existing diagnostics still report high confidence.

The most important finding is that this is not ordinary Gaussian noise. The error distribution has a sharp long tail: median bearing error is around 6–7 degrees, but p90 is above 120 degrees. The jump from p75 to p90 suggests discrete wrong-basin locks rather than smooth drift.

The most promising solution is not to replace the relocalizer wholesale. Instead, add a **Bearing Reliability Layer** around the current `sequential_pair_anchor_relocalization` output. This layer should decide whether the estimated bearing/yaw is trustworthy, while still allowing translation / distance-to-anchor to be used when those remain reliable.

Recommended high-level solution:

```text
Existing ICP diagnostics
+ sequential-pair closure check
+ anchor-level rotational self-alias precompute
+ per-attempt yaw posterior / score landscape
+ bearing-only suppression, not full relocalization rejection
```

If only one new method is implemented first, implement **per-attempt yaw posterior scoring**. If only one low-cost method is implemented first, implement **rotational self-alias precompute**. If the fastest route-level A/B test is needed, enable **bearing-specific reliability suppression** plus `--sequential_pair_closure_check --sequential_pair_closure_mode=belief`.

---

## 1. Current Project Diagnosis

### 1.1 What has already been fixed

The earlier problem was an **anchor-identity lead-lock cascade**: the system could promote the wrong `next` anchor to `current` too quickly when local structure repeated along the route. That was addressed with:

- `--sequential_pair_promotion_mode=bounded_evidence`
- `--sequential_pair_promotion_alias_aware`
- per-anchor `alias_score` based on non-adjacent anchor ICP overlap

Those fixes reduce or prevent promotion racing through repeated local structures.

### 1.2 The current remaining problem

The current problem is more specific:

> The relocalizer may choose the correct or approximately correct anchor identity, but the **bearing / yaw** it reports from ICP can still be wrong.

This manifests as rotational multi-modality inside a single anchor's local point cloud, rather than cross-anchor identity confusion.

The recomputed pooled bearing-error numbers from the hard-11 replay data are approximately:

| Metric | Value |
|---|---:|
| Number of accepted readings | 2793 |
| Median bearing error | 6.63 deg |
| Mean bearing error | 30.28 deg |
| p90 | 122.96 deg |
| p95 | 159.7 deg |
| p99 | 175.7 deg |
| Fraction >90 deg | 13.2% |
| Fraction >135 deg | 8.4% |
| Fraction <=5 deg | 44.5% |

The distribution is cliff-like: p75 is only about 31 degrees, while p90 is about 123 degrees. This strongly suggests **wrong basin selection** rather than continuous measurement noise.

### 1.3 Error is anchor-concentrated

The error is not uniformly spread across all anchors.

- 101 distinct `(episode, target_anchor_index)` groups were inspected.
- 28 of 101 anchor groups had mean bearing error above 45 degrees.
- These bad groups cover about 27% of readings but dominate total error mass.
- Excluding these 28 groups, the remaining 73 anchors have much better behavior:
  - median: about 4.0 deg
  - p90: about 32.2 deg
  - mean: about 12.1 deg

This means the typical anchor is already usable. The system mainly needs to detect and suppress unreliable bearing from a minority of structurally bad anchors.

---

## 2. Observed Failure Modes

The diagnostic rerun suggests at least three distinct sub-modes.

### Mode 1: Near-tied second yaw solution

Some anchors show obvious multi-basin behavior:

- high `icp_near_tie_basin_count`
- frequent `ambiguous_high_confidence`
- repeated selection of the same wrong basin

Example pattern:

```text
ep368 anchor12:
  mean bearing error ≈ 130.8 deg
  near-tie fraction ≈ 35%
  match_class: clean_full_pose 75%, ambiguous_high_confidence 25%
```

This mode is easy to act on because the current diagnostic signals already expose it.

### Mode 2: Inherently weak or under-constrained anchor

Some anchors are geometrically weak:

- many `partial_pose_degenerate` classifications
- low localizability eigenvalues
- low overlap / confidence in some cases

Example pattern:

```text
ep994 anchor2:
  mean bearing error ≈ 99.7 deg
  partial_pose_degenerate ≈ 78%
  overlap mean ≈ 0.627
  confidence mean ≈ 0.663
```

However, this mode has a caveat. Some anchors are geometrically degenerate but still have high naive overlap/confidence.

Example:

```text
ep680 anchor7:
  mean bearing error ≈ 168.3 deg
  partial_pose_degenerate ≈ 66%
  overlap mean ≈ 0.893
  confidence mean ≈ 1.000
```

This means overlap/residual confidence alone is not sufficient. The localizability / Jacobian signal is important because it can identify under-constrained rotational degrees of freedom even when residuals look good.

### Mode 3: Undetected single-basin wrong lock

This is the most concerning mode.

Example:

```text
ep187 anchor14:
  mean bearing error ≈ 48.3 deg
  clean_full_pose: 100%
  near-tie fraction: 0%
  overlap mean ≈ 0.854
  confidence mean ≈ 0.977
```

Every current self-diagnostic says the match is fine, yet the true bearing is significantly wrong.

This suggests that the current 24-seed yaw sweep and basin clustering may miss a competing solution. The ICP process converges confidently into a single wrong basin, and the final residual/overlap metrics do not reveal the problem.

Mode 3 is the main reason the project needs a new yaw-specific reliability mechanism.

---

## 3. Constraints from the Current System

Any solution should respect the current project constraints:

1. **No unbounded temporal accumulator.**  
   Past VIO/odometry-style accumulators caused permanent-lock failure modes. Any temporal smoothing must be bounded and local.

2. **Return-phase matching cost is already significant.**  
   The live system already pays for frequent local-map matching. Expensive global registration should be used only offline or as a rare fallback.

3. **The sequential-pair backend only considers `{current, next}`.**  
   The solution should work in this local setting and should not require matching against the full route on every update.

4. **Translation may remain useful even when yaw is bad.**  
   Many failed cases have reasonable distance/translation but poor bearing. The system should avoid hard-rejecting the entire relocalization unless necessary.

5. **The desired output is not only a better yaw estimate.**  
   The more important output is a reliable boolean or uncertainty score:

```text
anchor_heading_reliable: bool
bearing_uncertainty_deg: float
bearing_failure_reason: enum
```

---

## 4. Relevant Literature and Open-Source Directions

### 4.1 Degeneracy / localizability-aware ICP

#### X-ICP

**Paper:** X-ICP: Localizability-Aware LiDAR Registration for Robust Localization in Extreme Environments  
**Link:** <https://arxiv.org/abs/2211.16335>

X-ICP analyzes the alignment strength of scan-map correspondences and detects weakly constrained directions. Instead of blindly accepting the full ICP update, it constrains or suppresses updates along degenerate directions.

Relevance to this project:

- Very relevant to Mode 2.
- Conceptually close to the current `_localizability_from_correspondences` code.
- Suggests the project should not only classify the entire match as full/degenerate, but should identify which DOF is degenerate, especially yaw.

Recommended adaptation:

```text
If the yaw component of the localizability eigenvector is weak:
    keep translation if reliable
    suppress bearing/yaw
    mark anchor_heading_reliable = False
```

#### ICP observability / covariance theory

**Paper:** Observability, Covariance and Uncertainty of ICP Scan Matching  
**Link:** <https://www.researchgate.net/publication/267515355_Observability_Covariance_and_Uncertainty_of_ICP_Scan_Matching>

Key point: point-to-plane ICP Hessian better reflects observability than point-to-point ICP Hessian. Point-to-point can produce misleading covariance / confidence estimates.

Relevance:

- The current validated configuration uses `point_to_point`.
- The code already exposes `point_to_line`, `point_to_line_2p5d`, and `ndt_2d` A/B switches.
- This supports testing point-to-line or 2.5D objectives specifically for yaw reliability.

#### LP-ICP

**Paper:** LP-ICP: General Localizability-Aware Point Cloud Registration for Robust Localization in Extreme Environments  
**Link:** <https://arxiv.org/abs/2501.02580>  
**Code status:** The GitHub page says the authors do not currently plan to release the code: <https://github.com/xuqingyuan2000/lp-icp>

LP-ICP combines point-to-line and point-to-plane ICP and applies localizability-aware constraints. Even without code, the paper supports the same design principle: do not trust all pose DOFs equally.

---

### 4.2 ICP uncertainty / posterior estimation

#### CELLO-3D

**Paper:** CELLO-3D: Estimating the Covariance of ICP in the Real World  
**Link:** <https://arxiv.org/abs/1909.05722>

CELLO-3D focuses on predicting ICP uncertainty from real data. Its key relevance is that ICP uncertainty includes:

- sensor noise
- underconstrained geometry
- wrong convergence basin

For this project, the most useful lesson is not necessarily the neural architecture. It is the framing:

> ICP should not output only a pose and scalar confidence. It should output a pose plus uncertainty, especially along yaw.

#### Brossard et al. ICP covariance

**Paper:** A New Approach to 3D ICP Covariance Estimation  
**Link:** <https://arxiv.org/abs/1810.01470>

This work emphasizes that ICP covariance depends on initialization uncertainty and the basin of convergence, not only final residuals. This directly matches Mode 3, where final residuals look excellent but the pose is wrong.

Recommended adaptation:

```text
Do not trust final overlap/residual alone.
Estimate the yaw score landscape across initializations.
Use peak sharpness, entropy, and second-best ratio as bearing uncertainty.
```

---

### 4.3 Scan Context and yaw-candidate methods

#### Scan Context

**Paper:** Scan Context: Egocentric Spatial Descriptor for Place Recognition within 3D Point Cloud Map  
**Link:** <https://gisbi-kim.github.io/publications/gkim-2018-iros.pdf>

Scan Context represents a LiDAR scan as a polar grid and handles yaw rotation by circular column shift. It is directly relevant because this project already implements a 2D/2.5D Scan Context variant.

Current project implementation already includes:

- max-height-per-cell encoding instead of binary occupancy
- column-shift yaw search
- largest connected agreement region
- connectivity-aware shift selection

Recommended use:

- Use Scan Context not as a full replacement for ICP, but as an independent yaw-candidate generator and yaw-consistency signal.
- Compare ICP yaw with Scan Context yaw; if they strongly disagree, mark bearing unreliable.

#### Scan Context++

**Paper:** Scan Context++: Structural Place Recognition Robust to Rotation and Lateral Variations in Urban Environments  
**Link:** <https://arxiv.org/abs/2109.13494>

Scan Context++ improves robustness to rotation and lateral shifts. It has public implementations and may be useful as a reference for improving the current Scan Context module.

Recommended use:

- Borrow structural / lateral-robust scoring ideas.
- Use as a coarse yaw prior before ICP.
- Use as a second opinion for yaw reliability.

#### OverlapNet

**Project:** OverlapNet: Loop Closing for LiDAR-based SLAM  
**Link:** <https://github.com/PRBonn/OverlapNet>

OverlapNet predicts overlap and relative yaw between LiDAR range images using a Siamese network.

Relevance:

- Directly addresses relative yaw between scans.
- But trained primarily for autonomous driving LiDAR domains.
- Domain mismatch with Matterport / Go2 / indoor local-map point clouds is likely.

Recommended use:

- Do not use it as a drop-in relocalizer.
- Consider training a small yaw-reliability or yaw-bin model on the captured replay dataset if a learning-based extension becomes acceptable.

#### OverlapTransformer / LCDNet / LoGG3D-Net

Useful as medium-term references for learned overlap, place recognition, and relative pose estimation.

Example links:

- OverlapTransformer: <https://arxiv.org/abs/2203.03397>
- LCDNet: <https://arxiv.org/abs/2105.11344>

Recommended use:

- Not first-step fixes.
- Potential future modules if enough replay data is available for domain-specific training.

---

### 4.4 Robust / global registration and geometric verification

#### TEASER++

**Project:** TEASER++  
**Link:** <https://github.com/MIT-SPARK/TEASER-plusplus>  
**Paper:** <https://arxiv.org/abs/2001.07715>

TEASER++ is certifiably robust to extreme outlier rates. It is useful for global registration when reliable correspondences exist.

Recommended use:

- Do not run every relocalization attempt.
- Use as offline oracle diagnostic for bad anchors.
- Use as rare fallback for high-risk anchor groups if feature correspondences become available.

#### PointDSC

**Paper:** PointDSC: Robust Point Cloud Registration using Deep Spatial Consistency  
**Link:** <https://arxiv.org/abs/2103.05465>

PointDSC uses spatial consistency to reject bad correspondences.

Relevance:

- Conceptually supports the current `largest_connected_agreement_region` idea.
- Wrong matches often produce scattered agreement rather than a coherent spatially connected structure.

Recommended use:

- Borrow the idea of spatial-consistency scoring.
- Do not necessarily import the full deep model.

#### SC²-PCR

**Paper:** SC²-PCR: A Second Order Spatial Compatibility for Efficient and Robust Point Cloud Registration  
**Link:** <https://arxiv.org/abs/2203.14453>

SC²-PCR uses second-order spatial compatibility to distinguish true correspondences from outliers early.

Relevance:

- Useful inspiration for correspondence-level consistency checking.
- Could support an offline diagnostic to determine whether Mode 3 is caused by coherent but wrong self-similarity or by scattered nearest-neighbor artifacts.

#### SpectralGV

**Paper:** Spectral Geometric Verification for Point Cloud Retrieval  
**Link:** <https://arxiv.org/abs/2210.04432>

SpectralGV re-ranks point-cloud retrieval candidates by geometric consistency. It is relevant because the project needs to distinguish truly aligned geometry from superficially high-overlap but structurally wrong matches.

Recommended use:

- Consider spectral / graph compatibility as a diagnostic signal for high-risk anchors.
- Probably too heavy for every live attempt.

#### Go-ICP

**Project:** Go-ICP  
**Link:** <https://github.com/yangjiaolong/Go-ICP>

Go-ICP performs globally optimal ICP via branch-and-bound. It can help answer whether Mode 3 is due to local ICP basin selection or true geometric ambiguity.

Recommended use:

- Offline only.
- Run on bad anchors such as `ep187 anchor14` and `ep680 anchor7` to determine whether a global search finds a better yaw or confirms true ambiguity.

---

### 4.5 RGB-D / feature / semantic second opinion

The project already has feature-depth, LoFTR-depth, and fused relocalization paths. These are useful because RGB texture can disambiguate geometric symmetry that LiDAR alone cannot.

Relevant ideas:

- Multi-channel ICP / color ICP / semantic ICP
- LoFTR or SIFT depth matching as independent pose evidence
- RGB-D verification of top-k LiDAR yaw hypotheses

Recommended use:

```text
LiDAR ICP / yaw posterior proposes top-k yaw candidates.
RGB-D / LoFTR verifies which yaw is visually consistent.
If RGB-D and LiDAR disagree, suppress bearing rather than forcing a choice.
```

This should be considered P2, not P0, because front/rear view availability and reverse-path viewpoint changes make it more complex.

---

## 5. Recommended Solution Design

## 5.1 Bearing Reliability Layer

Add a small module around the current relocalization output:

```text
BearingReliabilityLayer
```

It should not replace `sequential_pair_anchor_relocalization`. It should consume its output and diagnostics, then decide whether the bearing should be trusted.

### Inputs

```text
AnchorRelocalization candidate
ICP diagnostics:
  - match_class
  - icp_basin_count
  - icp_near_tie_basin_count
  - overlap_ratio
  - confidence
  - median_residual_m
  - inlier_count
  - localizability eigenvalues
  - height consistency
Anchor priors:
  - cross-anchor alias_score
  - rotational_alias_score
Optional consistency signals:
  - sequential-pair closure disagreement
  - Scan Context yaw disagreement
  - RGB-D / LoFTR yaw disagreement
```

### Outputs

```text
anchor_dx_m
anchor_dy_m
distance_to_anchor_m
bearing_to_anchor_deg
anchor_heading_reliable: bool
bearing_uncertainty_deg: float
bearing_failure_reason: enum
```

Possible `bearing_failure_reason` values:

```text
near_tie_yaw
localizability_yaw_degenerate
height_inconsistent
rotational_self_alias
yaw_posterior_multimodal
closure_disagreement
scan_context_disagreement
rgbd_lidar_disagreement
```

### Behavior

If bearing is reliable:

```text
Use normal anchor bearing in the route hint.
```

If bearing is unreliable:

```text
Keep distance / translation if usable.
Suppress or weaken bearing.
Use route tangent, current-next segment direction, or conservative continuation hint instead.
```

This is important because the project data suggests translation can still be useful when yaw is unreliable.

---

## 5.2 Immediate diagnostic-to-bearing suppression

This is the cheapest first step.

Current diagnostic signals should be promoted from logging-only to active bearing reliability gating:

```text
if match_class in {ambiguous_high_confidence, partial_pose_degenerate}
   or icp_near_tie_basin_count > 0
   or localizability says yaw is weak
   or height_consistency is poor:
       anchor_heading_reliable = False
       keep distance if translation quality is acceptable
```

This should catch much of Mode 1 and Mode 2.

It will not catch Mode 3 by itself.

---

## 5.3 Per-attempt yaw posterior / score landscape

This is the most important new module.

Instead of relying only on 24 ICP seeds and post-hoc basin clustering, explicitly evaluate the yaw energy landscape.

### Proposed algorithm

For an anchor-current pair:

```text
for yaw in 0..360 degrees with step 3-5 degrees:
    rotate anchor points by yaw
    estimate translation only, or run very short ICP
    compute score(yaw): overlap * residual_score * connected_region_score * height_score

Find peaks in score(yaw).
Compute:
    best_score
    second_best_score
    best_to_second_ratio
    peak_width_deg
    yaw_entropy
    circular_variance
```

Then:

```text
if second_best_score / best_score is high:
    bearing unreliable
if yaw_entropy is high:
    bearing unreliable
if peak_width is too broad:
    bearing unreliable
if 90/180-degree alias peak is high:
    bearing unreliable
```

Why this matters:

- Existing basin clustering observes where ICP converges after initialization.
- A yaw posterior actively asks whether multiple yaw values explain the geometry.
- This can catch Mode 3, where ICP converges confidently into one wrong basin but the underlying score landscape may still be ambiguous.

---

## 5.4 Anchor-level rotational self-alias precompute

This is the static version of yaw posterior and should be cheap enough to compute after outbound finalization.

### Proposed algorithm

For each anchor `A`:

```text
P = A.local_map_points_xyz
for yaw in [15, 30, ..., 345] degrees:
    P_rot = rotate(P, yaw)
    score[yaw] = self_similarity(P, P_rot)

rotational_alias_score = max(score[yaw] outside near-zero yaw)
rotational_alias_yaws = yaws with high score
```

Potential self-similarity metrics:

- ICP overlap after fixed yaw + translation refinement
- Scan Context shifted similarity
- largest connected agreement region
- height-consistent connected agreement

Store on each `RouteAnchor`:

```python
rotational_alias_score: Optional[float]
rotational_alias_yaws_deg: list[float]
yaw_observability_prior: float
```

Live use:

```text
if anchor.rotational_alias_score is high:
    require stronger yaw posterior margin
    or mark bearing unreliable unless closure/RGB-D agrees
```

This directly targets anchors such as `ep680 anchor7`, which appear stably wrong by almost 180 degrees.

---

## 5.5 Sequential-pair closure as bearing cross-check

The code already supports sequential-pair closure:

```bash
--sequential_pair_closure_check \
--sequential_pair_closure_mode=belief
```

The idea is that the independent fits against `current` and `next` anchors should be geometrically consistent with the known anchor-to-anchor edge. If the two fits disagree, at least one bearing estimate is suspicious.

Recommended use:

- Activate it in offline replay first.
- Evaluate bearing error, not only anchor identity / route success.
- Use it as a confidence discount, not necessarily as a hard reject.

Limitations:

- It cannot catch cases where both anchors are wrong in a correlated way.
- It does not help when only one anchor is available.
- It is still worth testing because it is nearly free and already implemented.

---

## 5.6 Point-to-line / 2.5D A/B test

The literature suggests point-to-plane / point-to-line objectives expose observability better than point-to-point.

The current code already exposes:

```text
--route_local_map_icp_objective=point_to_point
--route_local_map_icp_objective=point_to_line
--route_local_map_icp_objective=point_to_line_2p5d
--route_local_map_icp_objective=ndt_2d
```

Recommended A/B:

```text
baseline: point_to_point, 0.10m voxel, 512 points
point_to_line
point_to_line_2p5d + height consistency
ndt_2d
dense profile: 0.05m voxel, 2048 points
```

Evaluate:

- mean / median / p90 bearing error
- fraction >90 deg
- bad-anchor recall
- good-anchor false suppression
- effect on route-level VLM behavior

---

## 6. Minimal Experimental Plan

### Experiment 1: Baseline reproduction

Use the existing offline replay data and reproduce the current bearing table.

Metrics:

```text
median bearing error
mean bearing error
p90 / p95 / p99
frac >90 deg
per-anchor mean error
error mass contribution by anchor
```

Purpose:

- Ensure all future experiments compare against the same raw data.

---

### Experiment 2: Diagnostics-active bearing suppression

Use existing diagnostics only:

```text
match_class
near_tie_basin_count
localizability
height_consistency
```

Suppress bearing when any warning fires.

Metrics:

```text
bad-reading recall
bad-anchor recall
good-reading false positive rate
remaining bearing error among trusted readings
coverage: fraction of readings still trusted
```

Expected outcome:

- Strong improvement for Mode 1 and Mode 2.
- Weak or no improvement for Mode 3.

---

### Experiment 3: Closure-check A/B

Run offline replay with:

```bash
--sequential_pair_closure_check \
--sequential_pair_closure_mode=belief
```

Metrics:

```text
bearing error before/after closure
closure disagreement vs bearing error correlation
cases where closure catches high-bearing-error readings
cases where closure misses Mode 3
```

Expected outcome:

- Should catch some single-anchor bad fits.
- Should not be treated as a complete solution.

---

### Experiment 4: Yaw posterior prototype

For the top bad anchors and matched good anchors, compute `score(yaw)` curves.

Suggested anchor sets:

```text
bad examples:
  ep680 anchor7
  ep368 anchor12
  ep5 anchor11
  ep994 anchor2
  ep368 anchor5
  ep187 anchor14

good controls:
  anchors with mean bearing error <10 deg and sufficient accepted readings
```

Plot / log:

```text
score(yaw)
best yaw
true yaw
second-best yaw
peak width
entropy
best/second ratio
```

Most important test:

> Does `ep187 anchor14` show yaw posterior ambiguity even though current diagnostics say `clean_full_pose`?

If yes, yaw posterior is likely the correct missing signal.

---

### Experiment 5: Rotational self-alias precompute

For every anchor, compute self-rotation similarity.

Metrics:

```text
rotational_alias_score vs mean_bearing_err_deg
rotational_alias_score vs frac >90 deg
rotational_alias_yaw proximity to observed wrong yaw
bad-anchor recall at different thresholds
false positive rate on good anchors
```

Expected outcome:

- If high correlation exists, this becomes a cheap route-level prior.
- If correlation is weak, keep it as a risk prior but rely more on per-attempt yaw posterior.

---

### Experiment 6: ICP objective and density A/B

Run:

```text
point_to_point / 512 pts / 0.10m
point_to_line / 512 pts / 0.10m
point_to_line_2p5d / 512 pts / 0.10m
ndt_2d / 512 pts / 0.10m
dense point_to_line_2p5d / 2048 pts / 0.05m
```

Metrics:

```text
trusted bearing accuracy
untrusted bearing coverage
runtime
bad-anchor suppression recall
good-anchor false suppression
```

---

## 7. Implementation Sketch

### 7.1 Add diagnostic fields to `AnchorRelocalization`

Possible additions:

```python
@dataclass
class AnchorRelocalization:
    ...
    anchor_heading_reliable: bool = True
    bearing_uncertainty_deg: Optional[float] = None
    bearing_failure_reason: Optional[str] = None
    yaw_posterior_entropy: Optional[float] = None
    yaw_second_peak_ratio: Optional[float] = None
    yaw_peak_width_deg: Optional[float] = None
```

### 7.2 Add rotational alias fields to `RouteAnchor`

```python
@dataclass
class RouteAnchor:
    ...
    rotational_alias_score: Optional[float] = None
    rotational_alias_yaws_deg: list[float] = field(default_factory=list)
```

### 7.3 Bearing reliability decision function

```python
def assess_bearing_reliability(
    estimate,
    diagnostics,
    anchor,
    closure=None,
    yaw_posterior=None,
):
    reasons = []

    if diagnostics.match_class in {"ambiguous_high_confidence", "partial_pose_degenerate"}:
        reasons.append(diagnostics.match_class)

    if diagnostics.icp_near_tie_basin_count > 0:
        reasons.append("near_tie_yaw")

    if diagnostics.yaw_localizability_weak:
        reasons.append("localizability_yaw_degenerate")

    if anchor.rotational_alias_score is not None and anchor.rotational_alias_score > threshold:
        reasons.append("rotational_self_alias")

    if yaw_posterior is not None:
        if yaw_posterior.second_peak_ratio > ratio_threshold:
            reasons.append("yaw_posterior_multimodal")
        if yaw_posterior.entropy > entropy_threshold:
            reasons.append("yaw_posterior_high_entropy")

    if closure is not None and closure.disagreement_z > closure_threshold:
        reasons.append("closure_disagreement")

    reliable = len(reasons) == 0
    return reliable, reasons
```

### 7.4 Route hint behavior

If bearing is trusted:

```text
Return hint: next anchor is 2.3m away at bearing -35 degrees.
```

If bearing is not trusted:

```text
Return hint: next anchor is about 2.3m away along the reverse route. Bearing estimate is unreliable; follow the route direction / continue toward the next route segment.
```

This prevents the VLM from being confidently steered by a wrong yaw.

---

## 8. What Not to Do First

### Do not replace ICP with a learned model immediately

OverlapNet, LCDNet, OverlapTransformer, and LoGG3D-Net are useful references, but their public models are mostly trained on outdoor driving LiDAR. Domain mismatch is likely severe.

Use them as architectural inspiration, not as immediate replacements.

### Do not run global registration every attempt

TEASER++, Go-ICP, PointDSC, SC²-PCR, and SpectralGV are useful but too heavy or too correspondence-dependent for every live return update.

Use them for:

- offline oracle diagnostics
- rare fallback on high-risk anchors
- validation of whether Mode 3 is true ambiguity or ICP local minimum

### Do not reintroduce unbounded temporal accumulation

The project has already seen permanent-lock failure modes from unbounded accumulation. Any temporal consistency should be:

```text
bounded
per-anchor
short-window
discarded after promotion
bearing-specific rather than identity-controlling
```

---

## 9. Final Recommendation

The best near-term plan is:

### P0: Immediate low-risk change

Promote existing diagnostics into active bearing suppression:

```text
match_class != clean_full_pose
or near_tie_basin_count > 0
or yaw localizability weak
or height consistency poor
=> anchor_heading_reliable = False
```

Do not hard reject the full relocalization unless translation is also unreliable.

### P1: Core missing signal

Implement per-attempt yaw posterior / score landscape.

This is the most likely method to catch Mode 3, because it asks whether the yaw dimension itself is ambiguous rather than trusting final ICP residuals.

### P1: Cheap anchor prior

Implement anchor-level rotational self-alias precompute.

This mirrors the already successful cross-anchor `alias_score`, but targets rotational ambiguity within a single anchor.

### P1/P2: Existing closure check

Run offline replay with:

```bash
--sequential_pair_closure_check \
--sequential_pair_closure_mode=belief
```

Evaluate bearing error specifically.

### P2: Objective / sensor second opinions

A/B test:

```text
point_to_line
point_to_line_2p5d
Scan Context yaw agreement
RGB-D / LoFTR verification of top-k yaw hypotheses
```

---

## 10. One-Sentence Conclusion

The project should stop treating ICP bearing as a single confident scalar and instead treat it as a **yaw reliability estimation problem**: keep using the current local-map relocalizer, but add rotational self-alias priors, yaw posterior scoring, and bearing-only suppression so that translation can still help route memory while unreliable yaw no longer misleads the VLM.
