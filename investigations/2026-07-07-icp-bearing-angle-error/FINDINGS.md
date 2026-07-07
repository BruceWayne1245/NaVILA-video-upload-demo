# ICP Bearing/Rotation Error Investigation (2026-07-07)

## Context

This is a follow-on to `investigations/2026-07-06-anchor-selection-and-icp-aliasing/`, which
diagnosed and fixed the **anchor-identity lead-lock cascade** problem (which anchor gets
promoted to `current`) via `--sequential_pair_promotion_mode=bounded_evidence` and
`--sequential_pair_promotion_alias_aware`. That work is now implemented and validated
offline (see the previous investigation folder and the main README's 2026-07-06 entry).

**This investigation targets a different, still-open axis: once the shadow relocalizer has
picked the (approximately) correct anchor, how accurate is the *bearing* (rotation/yaw) it
reports?** The main README's 2026-07-06 entry already flagged this as a long-tailed,
unsolved problem (median ~7deg but mean ~30deg, 12.6% of readings >90deg off) and explicitly
attributed it to the same underlying mechanism as the identity-aliasing problem
(scene-level self-similarity) but manifesting as *rotational* multi-modality within a
single anchor's own point cloud, rather than cross-anchor identity confusion.

All findings below were derived directly from raw data already captured by the
2026-07-06 session's `--capture_icp_replay_dataset` batch
(`icp_replay_capture_hard11_20260706_accumulated`) and its offline replay
(`code/offline_replay.py`, not yet committed to the main repo, reused here), plus a new
diagnostic re-run script (`code/bearing_root_cause.py`, written this session) that
re-executes `sequential_pair_anchor_relocalization` against the same captured point
clouds with full diagnostics enabled (`match_class`, `icp_basin_count`,
`icp_near_tie_basin_count`, `overlap_ratio`, `confidence`) instead of just the
accept/reject outcome the original replay kept.

**Ground-truth methodology** (same as the rest of this project): bearing error is always
`|angle_wrap(reported_bearing_deg - true_bearing_deg)|`, where `true_bearing_deg` is
computed from the robot's true world pose (`metadata.world_pose`, captured live from the
simulator, never derived from the shadow's own belief) to the true world pose of
**whichever anchor the shadow itself accepted as `target_anchor_index`** at that attempt
-- never a mismatched comparison against the oracle's own target. This matches the
project's established "clean-segment accuracy attribution" methodology from earlier
sessions.

## 1. Reproduced the README's pooled bearing-error numbers directly from raw data

Recomputed pooled bearing error from the 8 usable hard-11 episodes' `*_alias_fixed.json`
replay outputs (`data/icp_replay_raw/`, the final validated config: `point_to_point` +
`bounded_evidence` + `alias_aware`, post quarantine-bug-fix):

| stat | this session (n=2793, 8 episodes) | README 2026-07-06 (n=2412, "7 clean episodes") |
|---|---|---|
| median | 6.63 deg | 6.96 deg |
| mean | 30.28 deg | 30.1 deg |
| p90 | 122.96 deg | 118 deg |
| frac >90 deg | 13.2% | 12.6% |
| frac >135 deg | 8.4% | 8.2% |
| frac <=5 deg | 44.5% | 43.2% |

Close but not identical -- the README's "7 clean episodes" figure excludes one more episode
than this session's 8-episode pull; which episode and why is not documented anywhere found
so far. The close match confirms the underlying raw data and the README's summary are
consistent (not fabricated / not a stale claim).

Full percentile breakdown (not previously published anywhere): p50=6.6, p75=31.4, p90=123.0,
p95=159.7, p99=175.7, p100=179.9 deg. **The jump from p75 (31.4) to p90 (123.0) is a cliff,
not a gradual tail** -- consistent with a discrete wrong-basin-lock failure mode rather than
continuous measurement noise.

## 2. The error is heavily concentrated in a minority of (episode, anchor) pairs, not diffuse

Grouped all 2793 accepted readings by `(episode, target_anchor_index)` -- 101 distinct groups.
Full table: `data/bearing_error_by_anchor.csv` (episode, anchor_index, n_accepted_readings,
mean_bearing_err_deg, stdev_bearing_err_deg, coefficient_of_variation, sorted by total error
mass contribution).

- **28 of 101 anchor-groups (27.7%) have mean bearing error >45 deg**, covering 760 readings
  (27.2% of the data) but a disproportionate share of total error mass. The top 15
  anchor-groups alone account for **63.4%** of total error mass.
- **Excluding those 28 "bad" anchors, the remaining 73 anchors' 2033 readings (72.8% of the
  data) show median 4.0 deg, p90 32.2 deg, mean 12.1 deg** -- genuinely accurate. This means
  the pooled "30 deg mean / 12.6% >90 deg" headline number substantially understates how good
  the *typical* anchor's bearing accuracy already is, and overstates it as a uniform property
  of the pipeline.
- **Critically, this is not "occasional bad readings" scattered across many anchors.** The
  worst offenders show large `n` (dozens to 100+ repeated attempts at the same anchor, since
  an anchor stays "current" for many return-phase steps) with *consistently* elevated error
  the whole time it holds that role -- e.g. `ep5 anchor11`: n=93, mean=88.5 deg;
  `ep680 anchor5`: n=107, mean=58.2 deg; `ep680 anchor7`: n=32, mean=168.3 deg with stdev
  only 28.5 deg (i.e. reliably wrong by ~180 deg every single attempt). This is a
  **structural, anchor-level property**, not per-reading noise.

## 3. Diagnostic re-run reveals (at least) three distinct failure sub-modes, not two

A hypothesis was raised (by the project owner, not yet verified) that bearing error reduces
to two causes: (A) an equally-scoring second ICP solution ("tied" ambiguity) vs (B) the
anchor itself being inherently low-quality/low-confidence. To test this, `bearing_root_cause.py`
re-ran ICP (`sequential_pair_anchor_relocalization`, same `point_to_point`/0.10m/512pt
config as the validated batch) against 6 representative bad anchors spanning the
low-to-high coefficient-of-variation range, this time keeping the full diagnostics record
(`match_class`, `icp_basin_count`, `icp_near_tie_basin_count`, `overlap_ratio`,
`confidence`) that the original replay discarded. Raw output: `data/bearing_diagnostic_rerun_output.txt`.

| anchor | mean err (CV) | match_class distribution | near-tie frac | overlap mean | confidence mean |
|---|---|---|---|---|---|
| ep680 a7 | 168.3 deg (0.17, stable) | degenerate 66% / clean 28% / ambiguous 6% | 6.2% | 0.893 | 1.000 |
| ep368 a12 | 130.8 deg (0.18, stable) | clean 75% / ambiguous 25% | 35.0% | 0.751 | 0.831 |
| ep5 a11 | 88.5 deg (0.75, mid) | clean 80% / ambiguous 19% / degenerate 1% | 28.0% | 0.750 | 0.841 |
| ep994 a2 | 99.7 deg (0.59, mid) | degenerate 78% | 15.2% | 0.627 | 0.663 |
| ep368 a5 | 51.6 deg (1.20, unstable) | clean 72% / ambiguous 28% | 29.0% | 0.957 | 0.915 |
| ep187 a14 | 48.3 deg (1.25, unstable) | **clean 100%** | **0.0%** | 0.854 | 0.977 |

**Mode 1 -- tied/near-tied second solution (confirmed).** `ep368 anchor12` is the cleanest
example: 35% near-tie-basin rate, 25% of attempts self-flagged `ambiguous_high_confidence`,
and very low error variance (CV=0.18) -- the same wrong basin is chosen essentially every
time. `ep368 anchor5` and `ep5 anchor11` show similar near-tie rates (29%, 28%) but higher
CV, i.e. an intermittent tie rather than a single persistent lock.

**Mode 2 -- inherently weak anchor (confirmed, with a caveat).** `ep994 anchor2` fits
cleanly: 78% `partial_pose_degenerate`, and both overlap (0.627) and confidence (0.663) are
markedly lower than every other anchor checked. **But `ep680 anchor7` complicates a simple
two-mode story**: it is also majority `partial_pose_degenerate` (66%), yet its overlap
(0.893) and confidence (1.000, saturated) are as high as the *best* anchors in this table.
The `localizability` eigenvalue-based degeneracy check and the overlap/residual-based
confidence formula disagree here -- overlap/residual look excellent while the
correspondence-Jacobian check correctly flags the fit as under-constrained (most likely in
the rotational DOF specifically, not translation). This anchor is simultaneously "low
localizability" and "high naive confidence."

**Mode 3 -- undetected single-basin wrong lock (not covered by the two-mode hypothesis;
the most concerning finding of this investigation).** `ep187 anchor14` is unambiguous:
**100% of 43 re-processed attempts were classified `clean_full_pose`, zero ever showed a
near-tie basin, overlap averaged 0.854, confidence averaged 0.977 (near-max)** -- every
existing self-diagnostic signal says this match is fine. Yet true bearing error averages
48.3 deg with high variance (CV=1.25, swinging between accurate and very wrong across
attempts). None of the three currently-computed signals (`match_class`,
`icp_basin_count`/`near_tie_basin_count`, `overlap_ratio`/`confidence`) give any warning in
this case. The 24-seed yaw sweep is converging to a single, confident, wrong basin without
ever surfacing a competing candidate close enough to register as a "tie" -- i.e. the
seed-sweep resolution (15 deg steps) or the correspondence-threshold-based basin detection
itself may be missing a competing solution that a finer search or a different signal
(e.g. cross-anchor rotational self-similarity, or cross-validation against a neighboring
anchor's known relative pose) would catch.

## 4. Practical implication for next steps

- **Modes 1 and 2 are, in principle, cheaply actionable today**: `match_class` (`ambiguous_high_confidence`,
  `partial_pose_degenerate`) and `icp_near_tie_basin_count>0` are already computed per
  attempt but only used for hard rejection under `--route_local_map_quality_policy=strict`
  (the validated batches all ran `diagnostic`, i.e. these signals were logged but never
  actually discounted the reported bearing). Using them to *discount/suppress* the
  **bearing** component specifically (not necessarily reject the whole match, since
  translation may still be usable per the `aliasing_candidate` bucket finding from
  2026-07-05: dist err often <5cm even when bearing err is 20-130+ deg) is a low-cost change
  worth prioritizing.
- **Mode 3 cannot be caught from a single ICP attempt's own output, by construction** --
  some external cross-check is required: e.g. (a) `--sequential_pair_closure_check`'s
  existing anchor-to-anchor edge-geometry cross-validation (currently unverified as a
  bearing-error catcher -- this is an explicitly flagged, still-open hypothesis from the
  2026-07-05 README entries), (b) an anchor-level rotational self-similarity precompute
  analogous to `compute_anchor_alias_scores` but comparing each anchor's point cloud
  against yaw-rotated copies of itself rather than against other anchors, or (c) a
  finer/adaptive yaw-seed resolution specifically for anchors already flagged
  identity-alias-prone by the existing `alias_score` mechanism (on the hypothesis that
  identity self-similarity and rotational self-similarity may correlate, not yet checked).
- This session's own recommendation (given directly to the project owner, not yet
  implemented or validated) was, in priority order: (1) verify+activate closure-check as a
  bearing cross-check since it is nearly free and already flagged as an open hypothesis;
  (2) promote `match_class`/`near_tie_basin_count` from diagnostic-only to an active
  bearing-discount signal; (3) add an anchor-level rotational-alias precompute mirroring
  `compute_anchor_alias_scores`; (4) add a bounded (not unbounded) cross-attempt consistency
  check specifically on resolved yaw, mirroring `bounded_evidence`'s philosophy but applied
  to the rotational DOF. None of this has been implemented yet -- this folder is diagnostic
  input for further research/design, same role as the 2026-07-06 investigation folder that
  preceded `bounded_evidence`/`alias_aware`.

## 5. What's included in `code/` and `data/`

Current (2026-07-07) versions of the files most relevant to this investigation, copied from
the live `NaVILA-Bench/scripts/` checkout on the workstation (**not** the GitHub mirror's
`code/` folder, which is known to lag -- see the main README and this repo's git history for
that caveat):

- `relocalization.py`, `route_memory_agent.py`, `round_trip_eval.py` -- same role as in the
  2026-07-06 investigation folder, now including the `bounded_evidence`/`alias_aware`
  promotion logic implemented that session.
- `local_map.py`, `scan_context.py` -- unchanged supporting modules, included for context.
- `offline_replay.py` -- the ad hoc offline (no-Isaac-Sim) replay harness from the
  2026-07-06 session, reused here to regenerate the bearing dataset. Still not committed to
  the main repo.
- `bearing_root_cause.py` -- new this session; re-runs ICP against captured point clouds for
  specific (episode, anchor) pairs with full diagnostics enabled, to distinguish the three
  failure modes above.

`data/`:
- `bearing_error_by_anchor.csv` -- all 101 (episode, anchor) groups with n, mean, stdev, CV,
  sorted by total error-mass contribution.
- `bearing_diagnostic_rerun_output.txt` -- raw stdout of `bearing_root_cause.py`'s 6-anchor
  diagnostic re-run (the source for the table in section 3).
- `icp_replay_raw/*_alias_fixed.json` -- the 8 per-episode offline-replay outputs (final
  validated config) this investigation's bearing statistics were computed from; each
  attempt record has `attempt`, `step`, `target_anchor_index`, `accepted`, `true_dist`,
  `true_bearing_deg`, `reported_dist`, `reported_bearing_deg`. Provided so a fresh analysis
  (e.g. by a different research pass) can reproduce or extend the per-anchor breakdown
  without needing to re-run ICP from scratch.

## Open question for further research

Same overarching constraint as the 2026-07-06 investigation: `sequential_pair` only ever
compares `{current, next}`, live matching must stay cheap (~1-3s/attempt is already the
dominant per-attempt cost), and no unbounded odometry-style accumulator can be reintroduced
(that was the original permanent-lock death spiral's root cause, deliberately deleted).
**Given that finding: what technique would let a single anchor's ICP match reliably self-report
"my rotation estimate is untrustworthy" when the point cloud is rotationally self-similar
enough to produce a single confident wrong basin (Mode 3 above), without a second anchor to
compare against and without unbounded temporal accumulation?** This is the question this
investigation folder is meant to support external research on, as a companion to (not a
replacement for) the identity-aliasing question the 2026-07-06 folder posed.
