# 2026-07-13 (continued 3) — RGB/LoFTR rear-camera yaw cross-check: implemented live, first pilot result is a clear, consistent win over LiDAR ICP

**Purpose**: `CORRELATIVE_VERIFIER_CHECK.md` in this folder concluded that two structurally different single-viewpoint LiDAR-only approaches (wider ICP search, occupancy-grid correlation) both fail to recover correct yaw for the hard-anchor set, and that the fix needs genuinely new information a single LiDAR frame does not contain. The user independently proposed the same category of fix from a different angle: instead of a second *viewpoint* (short-baseline disambiguation, already implemented but firing on only 0.1% of live events), use a second *sensing modality* — the rear RGB-D camera this project already has configured but currently unused by the live `sequential_pair` backend — and cross-check ICP's rotation estimate against an independent visual estimate.

**This is not a new idea from scratch.** This project already built and validated almost this exact mechanism as the `feature_depth_loftr_3d3d_rear` backend (2026-06-29 through 2026-07-04) — LoFTR feature matching + 3-D RANSAC between a return-phase front-camera view and an anchor's saved rear-camera view, and per-anchor RGB-D + intrinsics + pose capture already happens unconditionally regardless of which backend is active. That backend was previously the *most accurate* one tried (bearing error 3.6–15.8° vs contemporary ICP's 18–107°) before the project pivoted to LiDAR-only `sequential_pair` for architectural reasons (GPU cost of a learned matcher in the loop, LoFTR's own separate "+1 anchor" bias, and a literature-survey-driven roadmap decision) — not because it was inferior.

## Implementation

New diagnostic `_loftr_rear_yaw_check()` in `relocalization.py`, wired into `sequential_pair_anchor_relocalization()` right after ICP produces its own `theta` for each current/next candidate (mirrors `_scan_context_yaw_check`'s call site and convention). Reuses the existing rear-view pipeline unmodified: `build_rear_view_descriptor`, `loftr_match_points`, `backproject_points`, `ransac_rigid_transform`, `camera_rotation_to_body_yaw` — the exact functions `feature_depth_anchor_relocalization`'s rear-view branch already used, just never before as a per-attempt cross-check on `sequential_pair`'s own ICP output. New opt-in flag `--sequential_pair_loftr_rear_yaw_check` (off by default, expensive — a GPU LoFTR call per candidate per attempt — not intended for routine batches). Diagnostic-only: does not gate or reject anything yet. Full existing test suite (180 tests) re-run clean after the change (flag off by default, byte-identical behavior confirmed).

## Pilot: `ep368` (the clearest genuinely-independent cross-run-reproducible hard anchor from `FINDINGS.md` §7 — anchor12, 60.4°→134.9° mean error across the two prior live batches)

Launched fully detached, identical config to the best-validated `short_baseline_hard11_20260712_accumulated` batch plus only the new flag. Completed cleanly in ~11.5 minutes (only slightly slower than the ~10-minute baseline — LoFTR's GPU overhead was small in practice). `loftr_rear_yaw_check` was **available on 628/628 (100%) of covisibility records** — no coverage gap.

### Result: LoFTR-rear beats ICP almost everywhere, not just at the known-hard anchor

| scope | n | ICP mean error | LoFTR-rear mean error | LoFTR beats ICP |
|---|---|---|---|---|
| All anchors pooled | 628 | 52.0° | **24.3°** | 560/628 = 89.2% |
| Anchor12 specifically (the known-hard anchor) | 24 | 95.2° | **59.6°** | 20/24 = 83.3% |

**Per-anchor breakdown — LoFTR-rear's mean error is lower than ICP's on every single anchor in this episode, often dramatically:**

| anchor | n | ICP mean | LoFTR-rear mean |
|---|---|---|---|
| 1 | 37 | 8.0° | 4.3° |
| 2 | 35 | 6.3° | 5.1° |
| 3 | 84 | 94.5° | **26.5°** |
| 4 | 79 | 72.0° | **32.7°** |
| 5 | 36 | 66.3° | **42.6°** |
| 6 | 49 | 19.6° | 10.0° |
| 7 | 53 | 65.9° | **31.8°** |
| 8 | 55 | 12.6° | 6.4° |
| 9 | 57 | 57.3° | **32.3°** |
| 10 | 65 | 38.3° | **18.5°** |
| 11 | 54 | 54.9° | **29.5°** |
| 12 | 24 | 95.2° | **59.6°** |

On the two anchors where ICP was already quite good (1, 2: ~6-8° mean), LoFTR-rear is roughly a wash (not clearly better, not worse) — consistent with there being nothing to fix there. On every anchor where ICP is bad, LoFTR-rear cuts the error substantially, typically to roughly a third to a half of ICP's error.

**LoFTR-rear's own `inlier_count` is a real, cleanly-discriminating quality signal for its own accuracy** — unlike ICP's `confidence`, which is already known (2026-07-05 Finding 3, reconfirmed throughout this project) to saturate near 1.0 even for bad readings:

| `inlier_count` range | n | LoFTR mean error | LoFTR median error |
|---|---|---|---|
| [0, 50) | 58 | 45.7° | 46.4° |
| [50, 150) | 76 | 27.6° | 17.7° |
| [150, 400) | 138 | 22.9° | 20.9° |
| [400, 2000) | 327 | 22.0° | 19.1° |

A clean, monotonic gradient — high-inlier-count LoFTR readings are genuinely more accurate, not just more confident. This is a usable, already-available fusion/trust signal without any new engineering.

## Caveats before over-claiming

- **Single episode, single pilot.** This is the first live data point for this mechanism — it needs confirming on at least the other reproducible hard anchors (`ep367` anchor8, and `ep678` anchor7 if that capture's corruption gets fixed) and ideally a full hard-11 batch before treating it as validated the way steps 1/2/4/5 were.
- **LoFTR-rear at anchor12 is better but still not accurate** (59.6° mean error is a large improvement over ICP's 95.2°, but still far from good) — this specific anchor may need the two sources fused/averaged rather than either alone being trusted outright.
- **Cost**: this is a GPU neural-net call per candidate per attempt, meaningfully more expensive than any LiDAR-only diagnostic tried so far (steps 1/2/4 were all cheap numpy operations). Fine for validation batches; needs a real cost/benefit look before considering it for routine live use (e.g. only running it when ICP's own signal looks weak, not unconditionally every attempt).
- **Rear camera assumption**: this depends on the rear camera's view actually covering the same physical area the front camera sees on return — true by the outbound/return geometry this project already relies on (the robot walks the same corridor backwards), but worth keeping in mind if anchor spacing or route geometry changes.

## Recommendation

This is the first unambiguous positive result in this entire bearing-error investigation line (2026-07-07 through 2026-07-13) — every single-modality LiDAR approach tried (wider ICP search, occupancy-grid correlation, Scan Context) failed to reliably beat ICP; the one approach that uses a genuinely different sensing modality wins clearly and consistently. Next steps, in order:
1. Confirm on the other reproducible hard anchors / a wider episode set (not yet done — this is one episode).
2. Design a fusion strategy (not yet designed) — e.g. prefer LoFTR-rear's estimate when `inlier_count` clears a threshold (150 looks like a reasonable candidate from the table above), fall back to ICP otherwise; or a confidence-weighted blend of the two independent yaw estimates.
3. Only after (1)-(2), consider live-wiring this beyond a diagnostic flag — i.e. actually using LoFTR-rear's yaw (not just cross-checking ICP's) when it looks more trustworthy.

## Reproducibility

Code changes: `relocalization.py` (`_loftr_rear_yaw_check`, new `loftr_rear_yaw_check` parameter on `sequential_pair_anchor_relocalization`), `round_trip_eval.py` (`--sequential_pair_loftr_rear_yaw_check` flag, wired through and logged). Snapshot in this folder's `code/relocalization.py` and `code/round_trip_eval.py` (full files, matching this project's snapshot convention). Launcher: `code/run_loftr_rear_yaw_check_20260713.sh`. Analysis script: `code/analyze_loftr_ep368_20260713.py`.
