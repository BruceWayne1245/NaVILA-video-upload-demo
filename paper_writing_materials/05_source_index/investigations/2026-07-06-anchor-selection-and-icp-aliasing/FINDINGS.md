# Anchor-Selection & ICP-Aliasing Investigation (2026-07-06)

## Context

This is the `sequential_pair` relocalization backend used during the return leg of a
round-trip VLN-CE episode (`scripts/round_trip_eval.py` + `route_memory_agent.py` +
`relocalization.py`). Return motion itself is driven entirely by the VLM under
`--route_hint_source=oracle` (the oracle hint is what actually steers the robot); the
`sequential_pair` machinery only runs as a parallel, non-oracle "shadow" pipeline that
tries to figure out where the robot is using LiDAR local-map ICP against a small set of
route anchors recorded on the way out. Because the robot's actual motion is
oracle-controlled, the shadow pipeline's own accuracy has no effect on navigation
success — it's purely a research target in itself (the eventual goal is to replace the
oracle hint with this shadow pipeline).

Earlier sessions (documented in the main project README) found a severe **permanent-lock
death spiral**: the shadow's belief about "which anchor am I at" could freeze forever
once a single bad ICP reading broke an internal odometry-based consistency gate
(`_distance_since_sequence_observation_m` / `expected_s` / `motion_error`, in
`route_memory_agent.py`). This session (continuing from 2026-07-05's diagnosis) deleted
that gate outright, plus the P1/P2 per-candidate ICP gates it depended on, and replaced
promotion (deciding when to advance from the current anchor to the next one) with a
purely ICP-quality/closeness/trend-based rule. A new ICP objective
(`--route_local_map_icp_objective=point_to_line`, "stage 3.1") and matching voxel/point
budget ("stage 4A") were also added this session.

Full raw-data forensic analysis (using `metadata.world_pose` ground truth, never the
oracle's own target anchor, per this project's established methodology) was run against
a fresh 11-episode hard-episode A/B batch (`stage31_4A_hard11_20260705_{accumulated,
oracle}`, `--sequential_pair_anchor_geometry_source={accumulated,oracle}`) and against
the prior day's `belief_trend_hard11_20260705_accumulated` batch (same anchor-selection
logic, old ICP objective) for comparison. Findings below.

## 1. The permanent-lock death spiral is gone

Across all 20 usable episodes in today's batch, `relocalization_events` shows **zero**
explicit rejects (`accepted=False`). The deleted odometer/`expected_s` gate was the
death spiral's root cause; removing it removed the reject/permanent-lock failure mode
entirely, as intended.

A separate, previously-undocumented "silent gap" mechanism was found and traced (see
`code/route_memory_agent.py` `_select_sequential_pair_relocalization` /
`update_relocalization`): when both `current` and `next` candidates' quality lands in
`[0.15, min_relocalization_confidence=0.35)`, the attempt is dropped entirely (no
`relocalization_events` entry at all — not accept, not reject). Root-caused to a genuine
compound cause in one specific episode (`ep994`): a real, moderate, scene-level
covisibility drop (`overlap_ratio` ~0.37 vs. the usual 0.6+, confirmed via the code's own
`confidence = overlap_ratio * (1 - residual/0.45) * 1.5` formula) landing exactly on top
of a structural fragility — anchor 0 (the synthetic route-start anchor,
`descriptor=None`) never produces a covisibility record at all
(`relocalization.py`'s `if anchor is None or not isinstance(anchor.descriptor, dict):
continue`), so once `current` reaches anchor 1 there is no `next` candidate and all of
this project's redundancy mechanisms (closure-check fusion, quarantine) go dark. Neither
cause alone explains the gap; both together do.

## 2. New anchor-selection problem: "lead-lock cascade" (not lag-type death spiral)

Direct ground-truth reconstruction of the raw accepted `target_anchor_index` sequence
(never the smoothed `route_memory_shadow` field, and never cross-referenced against the
oracle's own target — only against the robot's true position via `metadata.world_pose`)
found:

- **100% of deviation is "lead" (current races ahead of the robot's true position),
  0% is "lag"** — the opposite of the previously-documented failure mode. Aggregate:
  off-by-2-or-more anchors in 87-89% of samples across both halves of today's batch.
- **Cascades**: within short windows (≤15 attempts), the raw identity advances by
  3-7 anchor indices while the robot's true position barely moves (net displacement
  often <1.5 m). Concretely traced end-to-end in `ep4` (accumulated-geometry half):
  `current` advanced from anchor 10 to anchor 1 across attempts 1-52 while true
  position moved ~1.3 m net. Every transition had `candidate_count=2` (both `current`
  and `next` genuinely had ICP candidates that attempt — not a "current produced
  nothing" edge case).
- Root mechanism: promotion fires whenever `next_est.distance_to_anchor_m <=
  promotion_close_radius_m` (0.75 m, from `route_memory_agent.py`'s
  `max(0.75, 0.75*anchor_spacing_m)`) **or** `next_quality >= promotion_score_ratio
  (0.85) * current_quality` — both are *relative*/self-reported checks with **no
  ground-truth or motion-plausibility component**. In the traced ep4 cascade, ICP
  repeatedly reported implausibly small distances for anchors that were truly meters
  away (e.g. attempt 45: anchor 3 reported 0.60 m, true distance 5.05 m) — a
  confidently-wrong ICP read, not noise, that happened to clear the 0.75 m bar.
- Why the existing safety nets don't catch this: `_sequential_pair_closure_precheck`
  (cross-validates `current`/`next` via the known anchor-to-anchor edge geometry) runs
  every time both candidates exist, but this batch uses `--sequential_pair_closure_mode=
  belief`, which by design **never hard-rejects** — it only discounts confidence
  smoothly (explicitly to avoid recreating the old death spiral) — and it is
  structurally blind to *correlated* errors (both anchors wrong in a mutually
  self-consistent way, which is exactly what a self-similar scene produces). Quarantine
  (`_record_next_anchor_trend`) needs `quarantine_trend_min_history=6` samples
  accumulated while a candidate sits in the "next" role before it can blacklist
  anything — the cascade promotes anchors faster than that (often 1-6 attempts per
  anchor), so quarantine's evidence window never closes before promotion happens; and
  once promoted to `current`, the code explicitly stops watching that anchor's quality
  at all.

## 3. The new ICP objective (`point_to_line`, stage 3.1/4A) measurably worsened both problems

Config-clean A/B (identical anchor-selection/closure/quarantine logic; only
`--route_local_map_icp_objective` differs: `point_to_point` [yesterday's default] vs.
`point_to_line` [today]), on the 7 episodes present in both batches (4, 5, 367, 368,
678, 680, 1040):

| | yesterday (point_to_point) | today (point_to_line) |
|---|---|---|
| cascade events (7 episodes) | 7 | 18 (2.6x) |
| episodes with ≥1 cascade | 5/7 (71%) | 7/7 (100%) |
| mean severe-error rate (dist err > 1 m, ground-truth) | 58.0% | 75.5% (+17.5 pts, 6/7 episodes worse) |

An explicit "did the death spiral just mask the cascade" hypothesis (i.e. maybe
yesterday's cascades were already this bad but hidden in episodes that got stuck
rejecting) was tested directly and **refuted**: the two yesterday episodes that did
*not* cascade (`ep678`, `ep1040`) had the *lowest* reject-tail fraction of the 7 (32.8%,
37.7%), not the highest; the three worst reject-tail episodes (`ep5` 85.2%, `ep368`
79.5%, `ep367` 78.9%) cascaded anyway in their remaining accepted windows. The two
non-cascading episodes' `accepted` sub-sequence shows almost no promotion activity at
all (`ep678`: one transition across 201 accepts; `ep1040`: one transition across 165) —
unrelated to reject-tail length. Point_to_line is a real, independent aggravating
factor, not merely "what the death spiral was hiding."

## 4. Root-cause audit: corridor geometric degeneracy is *not* the dominant mechanism — scene-level aliasing is

This project's own `corridor_degeneracy_ratio` / `localizability` (eigenvalue-based)
diagnostics were checked against 13,345 ground-truth-labeled candidate records (severe
error >1 m vs. clean ≤1 m) across all usable episodes in both today's and yesterday's
batches:

- `corridor_degeneracy_ratio` median is **higher** (0.756) in the severe-error bucket
  than the clean bucket (0.694) — the opposite of what "corridor degeneracy causes the
  errors" would predict. `weak_direction_count>=1` / `localizability.quality==
  "degenerate"` is *less* common in the severe bucket (5.6%) than the clean bucket
  (22.8%). This reproduces and statistically confirms a weak-signal finding first
  noted on 2026-07-04 (median 0.866 vs 0.784, large overlap) at full-dataset scale.
- Severe-error records have **0%** with `overlap_ratio < 0.3` (a genuinely weak/sparse
  match) and **40.9%** with `overlap_ratio >= 0.6` (a "should look convincing" match).
  By `match_class`: 47.3% `clean_full_pose`, 47.2% `ambiguous_high_confidence`, only
  5.6% `partial_pose_degenerate` — i.e. **94.5% of severe errors are matches the system
  itself considered clean or merely ambiguous, not geometrically degenerate.**
- All 46 detected cascade windows (both batches, all episodes) show
  `corridor_degeneracy_ratio` well above the code's own degeneracy-skip threshold
  (0.15) — typically 0.49-0.89 — while multiple *different*, several-meters-apart
  anchors simultaneously report plausible-to-high overlap (0.5-1.0+) against the same
  single live scan. Example: `ep368` (today), attempts 77-90, 8 different anchor
  indices (3-10) each showing overlap 0.59-1.06 against one scan.

**Verdict**: the dominant failure mechanism, across both the precision problem and the
anchor-selection cascade problem, is **scene-level perceptual self-similarity /
aliasing** (structurally repeated features along a route segment producing convincingly
similar point clouds at genuinely different physical locations) — not classical
corridor geometric under-constraint. Existing corridor-degeneracy instrumentation
cannot detect this because it measures a different thing (local constraint-direction
richness, not cross-location descriptor distinctiveness).

## Open question for further investigation

Given the `sequential_pair` design constraint (only ever compares exactly `{current,
next}`, and per the above, cannot safely reintroduce an *unbounded* odometry-based
motion-consistency accumulator — that specific formulation is what caused the original
death spiral) — **what LiDAR local-map matching / place-recognition technique would
meaningfully increase cross-location descriptor distinctiveness or add temporal/
multi-frame disambiguation at this project's LiDAR density (~500 pts/scan after
downsampling), without requiring an unbounded accumulator or a full return to
brute-force multi-anchor search?** This is the question this investigation folder is
meant to support external research on.

## What's included in `code/`

Current (2026-07-06) versions of the files most relevant to this investigation, copied
from the live `NaVILA-Bench/scripts/` checkout:

- `relocalization.py` — all ICP objectives (`point_to_point`/`point_to_line`/
  `point_to_line_2p5d`/`ndt_2d`), `sequential_pair_anchor_relocalization`, match-class/
  basin/ambiguity diagnostics, `corridor_degeneracy_ratio`/`localizability`.
- `route_memory_agent.py` — `RouteMemoryAgent`, `_select_sequential_pair_relocalization`
  (the promotion logic discussed above), closure-check (`threshold`/`belief` modes),
  quarantine (`window`/`trend` modes), the now-deleted-from-the-live-path odometer
  machinery still present for legacy backends.
- `round_trip_eval.py` — evaluation driver; also where this session's new
  `--capture_icp_replay_dataset` mechanism was added (dumps every anchor's raw local-map
  points + ground-truth pose once, and the robot's raw local-map points + ground-truth
  pose at every return step, to `result_dir/icp_replay_dataset/`; since return motion is
  oracle-controlled regardless of the shadow relocalizer, this dataset should let a new
  ICP/matching method be evaluated offline against the exact same point clouds a live
  rerun would produce, without needing Isaac Sim).
- `scan_context.py`, `local_map.py`, `plot_route_memory_diagnostic_frames.py` — the
  place-recognition-adjacent (Scan Context) code and local-map/plotting utilities
  already in the codebase, included for context on what's already been tried.
