# 2026-07-16 — Option 1 implemented: real motion-integrated multi-frame submap (symmetric anchor-side accumulation + new return-side live frame buffer); unit-tested (a real pruning bug found and fixed via the tests); live 22-episode batch chained after the two already-running A/Bs

**Context**: per `investigations/2026-07-16-matching-primitive-strategy/FINDINGS.md`, the 2026-07-15 network survey's recommended single-frame matching-primitive upgrades are already falsified by this project's own prior work — no single-viewpoint 2D overlap measure resolves this environment's genuine repeated-structure aliasing. A follow-up check found the residual problem is better characterized as a **capture-methodology problem**: even anchors sitting at genuine sharp turns (41-49°, confirmed via ground-truth anchor-to-anchor path geometry) show `corridor_degeneracy_ratio` as high as plain corridor stretches (0.787-0.956) in their own single-frame point cloud — the landmark objectively exists nearby (9/10 known-bad anchors have a real turn within 0-5.3m, mostly 0-2m or ~0.00m) but a single instantaneous LiDAR capture, taken at an arbitrary trigger moment, frequently misses it. Per user direction, this document implements the resulting fix: accumulate real motion (genuine parallax across actual robot travel) into both the anchor's reference descriptor (outbound) and the live "current" scan (return).

**Explicitly not a repeat of `multiframe_anchor_window`** (2026-07-08, already tried, rejected): that mechanism was step-count-based (not distance-based, not robust to walking-speed variation) and backward-only (never accumulates frames *past* the anchor-spacing trigger point) — its own tested window (~0.8m) was too short and one-sided to reliably cross a nearby landmark on either side. This design fixes both, and adds a return-side buffer that didn't exist at all before.

## What was implemented

All changes additive, off by default (7 new flags, all opt-in), zero behavior change to `multiframe_anchor_window`'s existing code paths.

### A. Anchor (outbound) side — new, symmetric, distance-based

- New state: `multiframe_anchor_symmetric_enabled`, `multiframe_anchor_backward_distance_m` (default 1.5m), `multiframe_anchor_forward_distance_m` (default 1.5m), `multiframe_anchor_forward_stall_updates` (default 300, release valve). Own buffer (`_outbound_symmetric_frame_buffer`) and pending-anchor state (`_pending_anchor`), entirely separate from `multiframe_anchor_window`'s existing buffer/logic.
- **A genuine flaw was found and fixed before implementation** (via a Plan agent's pressure-test): naively delaying `_append_anchor` to accumulate forward frames would let the anchor's own registered `pose_from_start`/`distance_from_start_m` drift forward by the whole forward-window distance, corrupting `edge_from_previous` (used elsewhere for drift-free short-chain composition) and every downstream consumer of anchor position. Fixed: `_append_anchor` gained optional `anchor_pose`/`anchor_distance_m` overrides (default `None` = unchanged original behavior); the anchor's identity stays pinned to the exact moment the anchor-spacing trigger fires (`_begin_pending_anchor`), only its *descriptor* gets the wider accumulated submap once `_finalize_pending_anchor` runs.
- `_should_save_anchor()` gained a `self._pending_anchor is not None` guard so the trigger can't re-fire mid-accumulation.
- `finalize_outbound()` flushes any pending anchor first (outbound can legitimately end mid-forward-accumulation).
- **A second, real bug was found by the unit tests themselves, not by review**: the symmetric buffer's prune cutoff initially used `current_distance - (backward + forward)`, which over-pruned early backward frames once forward accumulation had progressed partway (the reference point should be the *trigger* distance while a pending anchor exists, not the still-advancing current distance). Fixed to use `pending["trigger_distance_m"] - backward_distance_m` while pending, `current_distance - backward_distance_m` otherwise. Caught by `test_symmetric_window_merges_backward_and_forward_frames_hand_computed` failing with 2 merged points instead of the hand-computed 3.
- **Real-world parameter finding**: live batches use `--route_anchor_spacing_m=1.0` (confirmed in `batch_logs/route_memory_batch_10_20260626/*.log`), not "a few meters" as initially assumed. Since the next anchor's trigger can't fire while the current one accumulates forward, the 1.5m/1.5m default stretches realized anchor cadence to ~3m worst-case (not 10m+, which chasing the single 5.3m outlier would have caused) — a deliberate, documented trade-off, not an overlooked side effect.

### B. Return (live "current") side — genuinely new mechanism

- Confirmed via code reading: a fresh real point cloud is built every single return-phase step already (`local_map_descriptor_from_env`), but `update_relocalization` silently discards it on every non-interval call. `current_absolute_pose_from_start()` already accurately tracks return-phase pose every step — only point-cloud buffering was missing.
- New state: `return_frame_buffer_enabled`, `return_frame_buffer_window_m` (default **1.0m, smaller than the anchor side's 1.5m**), `return_frame_buffer_max_frames` (default 400, count-based safety valve for stationary dwells). The smaller window is deliberate, not just a compute-cost call: reprojection here relies on return-phase dead reckoning, the same integration relocalization exists to correct and that drifts over the return phase — unlike outbound dead reckoning, which this project already treats as comparatively trustworthy.
- `update_return_motion` buffers every real per-step frame (before calling `update_relocalization`, unchanged call); `update_relocalization` swaps in the merged descriptor (`_merge_return_frame_buffer`) right before calling the injected `self.relocalizer`, when enabled. **No changes needed in `round_trip_eval.py` beyond new flags/kwargs** — the `route_relocalizer` closures are descriptor-agnostic; `RouteMemoryAgent` stays the sole owner of what descriptor reaches the matcher.

### C. Shared merge helper

`_merge_outbound_frame_buffer`'s existing SE(2)-reproject-and-concatenate body was refactored into a static `_merge_point_frames(frames, target_pose)`; `_merge_outbound_frame_buffer(anchor_pose)` is now a one-line wrapper. Verified byte-identical behavior by re-running `MultiframeAnchorWindowTest`'s existing scenarios unchanged (all still pass). `_finalize_pending_anchor` and `_merge_return_frame_buffer` both call the shared helper with their own filtered frame lists.

### D. CLI flags (`round_trip_eval.py`)

7 new flags (4 anchor-side, 3 return-side), all opt-in/off-by-default, help text states the motivating 2026-07-16 data and explicit relationship to `multiframe_anchor_window` (which they do not replace). Wired into the `RouteMemoryAgent(...)` construction and the results config-echo block.

## Validation

**11 new unit tests** across two new classes:
- `MultiframeAnchorSymmetricWindowTest` (6 tests): default-off; hand-computed merge of backward+forward frames (the test that caught the pruning bug above); the pinned-pose regression test (anchor's `pose_from_start`/`distance_from_start_m`/`edge_from_previous` equal trigger-time values, not post-accumulation values); `_should_save_anchor` non-refiring while pending; `finalize_outbound` flushing a pending anchor; forward-stall release valve.
- `ReturnFrameBufferTest` (5 tests, using a stub `relocalizer` since `self.relocalizer` is directly injectable): default-off passes the raw descriptor through unchanged (same object, verified via `assertIs`); buffer accumulates and prunes by distance; the merged descriptor (containing points from multiple buffered steps) actually reaches the relocalizer at an ICP-attempt step, with non-interval steps confirmed to skip the relocalizer call entirely; frame-count cap bounds buffer growth during a stationary dwell.

Full suite: **216 tests (205 prior + 11 new: 6 in `MultiframeAnchorSymmetricWindowTest` + 5 in `ReturnFrameBufferTest`), 14 pre-existing skips (unchanged), zero regressions.**

**Real-code sanity check** (not a substitute for the live batch, catches gross implementation bugs cheaply first): drove both mechanisms with realistic random-walk motion and random point clouds (no Isaac Sim). Anchor side: 15 anchors created over ~20m, each merged descriptor holding thousands of accumulated points, anchor spacing showing the expected ~1.0-1.6m cadence stretch (not the nominal 1.0m, per the documented trade-off). Return side: relocalizer called at the expected interval cadence, merged point count growing from a single frame's worth (~92) up to a steady-state plateau (~1700-1900) as the 1.0m window fills, buffer settling at 20 frames spanning 0.95m (correctly bounded near the configured window).

## How to revert

Omit `--route_memory_multiframe_anchor_symmetric_enabled` and `--route_memory_return_frame_buffer_enabled` (both default off). No other code path is touched when both are off.

## Live validation

Per user direction, offline pre-validation was skipped this time (the anchor-side half fundamentally cannot be validated offline — `capture_icp_replay_anchors` only ever saved one single-frame anchor snapshot per anchor, not reconstructable after the fact into "what the new accumulation process would have captured"; the return-side half could be checked offline via the already-fixed `offline_replay.py` harness if wanted later, but isn't a substitute for validating the anchor-side change regardless).

**Live 22-episode batch chained, not run concurrently**, since two other batches from earlier the same day were still active/queued on the same GPU:
- `shadow_current_confidence_gate_22ep_20260716` (already running since 10:42) →
- `shadow_short_baseline_require_resolution_22ep_20260716` (chained after that one) →
- **`shadow_multiframe_submap_22ep_20260716`** (this change) — chained via `/home/teambruce/chain_multiframe_submap_after_short_baseline_20260716.sh` (detached, PPID=1, polls both prior master logs for their `[master] batch finished` markers before launching `/home/teambruce/run_22ep_multiframe_submap_20260716.sh`).

Config: same 22 episodes, same Variant-1 base config as all three A/Bs this week, with `--route_memory_multiframe_anchor_symmetric_enabled --route_memory_multiframe_anchor_backward_distance_m=1.5 --route_memory_multiframe_anchor_forward_distance_m=1.5 --route_memory_multiframe_anchor_forward_stall_updates=300 --route_memory_return_frame_buffer_enabled --route_memory_return_frame_buffer_window_m=1.0 --route_memory_return_frame_buffer_max_frames=400` added — `current_confidence_ambiguity_gate`/`quarantine_next_quality`/`short_baseline_require_resolution` all left off, an isolated single-variable A/B against the same known 14-success/8-failure baseline.

**Housekeeping note**: a stale orphaned process from the confidence-gate batch's `ep187` (timed out, `exit_code=124` already recorded in that batch's own `summary.tsv`, but the process itself hung 2+ hours post-timeout without exiting — the same known "Isaac Sim doesn't exit cleanly after crash" issue documented repeatedly in this project's history) was found and cleaned up mid-session to free GPU resources for the actually-active episode.

**Pending / next steps**: once all three chained batches finish (likely spans into 2026-07-17 given each takes ~6-7h), compare per-episode `round_trip_success` for `shadow_multiframe_submap_22ep_20260716` against the known 14/8 baseline, using the same methodology as the prior two A/Bs this week. Be honest about the ceiling regardless of outcome: `ep214` anchor1 (no nearby landmark found within 7 anchors either side) is an expected residual this mechanism likely cannot fix; the realized anchor-spacing stretch (~1.0-3m vs. nominal 1.0m) is a real, accepted trade-off, not a bug, if it shows up in the results.
