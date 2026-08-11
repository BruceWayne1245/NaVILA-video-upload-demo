# 2026-08-11 — anchor_v3_active 30ep batch: multiframe-merge confidence collapse, root cause, fix, and smoke-test result

**Context**: `--anchor_v3_active` (V3 as sole promote/hold/recovery authority, replacing Anchor V2's controller — see `investigations/2026-08-10-anchor-v3-active-integration-and-landmark-v11-reuse/`) had been smoke-tested clean on a single episode (ep386: 394 attempts, 1 real promote, 13 defensive rejects, 0 crashes). A 30-episode batch (`anchor_v3_active_30ep_20260811`, manifest `route2_anchorv2_terminal50.tsv`) was launched the same day to validate at scale. This document covers that batch's failure, the root cause, the fix, and a smoke-test re-validation — all done live in one continuous session with a background monitor watching the batch.

## Part 0 — headline result

10/30 episodes completed before the batch was stopped by the user: **9/10 hit the full 3600s external timeout (exit_code=124); the 1 exception (ep87) ended via its own env-step budget (exit_code=0) but also failed return.** `_evaluate_anchor_v3_active_controller` (the function that makes every promote/hold/recovery decision) was invoked **zero times, in all 10 episodes** — confirmed via `controller-start`/`controller-end` heartbeat log counts. Every episode's anchor pair stayed frozen on a single `(current, next)` value for the entire episode.

## Part 1 — root cause: a confidence floor, not a missing-estimate gate

Initial code reading suggested the controller's own gate (`next_est is not None` in `route_memory_agent.py`'s `_select_sequential_pair_relocalization`) was the blocker. This turned out to be one layer too deep (that gate was in fact never the blocker — `next_est` was fine whenever it was reached at all). The real gate is **upstream**, in `update_relocalization`:

```python
estimates = [
    estimate for estimate in estimates
    if estimate.confidence >= self.min_relocalization_confidence
    and self._anchor_by_index(estimate.anchor_index) is not None
]
if not estimates:
    return None
```

`min_relocalization_confidence` defaults to **0.35** (`--route_min_relocalization_confidence`, unconditionally wired into `RouteMemoryAgent.__init__` regardless of any `--reliability_v11_*`/`--anchor_v3_*` flag — this is baseline `--route_memory` machinery, **not** part of V1.1).

**Offline-replayed real ICP matches** (using the batch's own captured `icp_replay_dataset` point clouds, calling `sequential_pair_anchor_relocalization` directly, no re-simulation needed) against ep579's stuck pair `(11, 10)` across the whole return phase (steps 2150→3074):

| anchor | corridor_degeneracy_ratio | match_class | confidence |
|---|---:|---|---:|
| 11 (current) | 0.93 | ambiguous_high_confidence | 0.22–0.30 |
| 10 (next) | 0.96 | ambiguous_high_confidence / partial_pose_degenerate | 0.21–0.27 |

**Both sides sat permanently below 0.35, every single attempt, for the entire hour.** `update_relocalization` silently returned `None` every time — no estimate, no vote (not even a losing one), no controller invocation. This is a harder failure than anything in prior investigations of this class (see `investigations/2026-07-15-50ep-batch-current-next-simultaneous-failure/FINDINGS.md`, where "current+next simultaneously bad" still produced losing *votes* that at least got recorded).

### Why confidence collapsed: `route_memory_multiframe_anchor_symmetric_enabled`

This flag (added earlier the same week to fix anchor0/landmark recognizability — see `investigations/2026-08-10-anchor0-landmark-v11-reuse-and-anchor-v3-active/`) makes `RouteMemoryAgent._merge_point_frames` concatenate **every raw LiDAR frame** inside a `[trigger − backward_distance_m, trigger + forward_distance_m]` window (~1.5–3m of travel) with **no deduplication**. Measured on ep579's captured anchors:

| anchor | raw point count |
|---|---:|
| 0 (single-frame, unaffected by this flag) | 9,423 |
| 1–11 (symmetric-merged) | 2.1M–3.9M |

At match time, `relocalization.py`'s `voxel_downsample_xyz(..., max_points=512)` subsamples this down to 512 points. A voxel-dedup pass was tried first as the fix (hypothesis: redundant duplicate points were diluting the sample) — **empirically falsified**: deduping the merge output first produced byte-identical downstream confidence/degeneracy numbers, because `voxel_downsample_xyz`'s own `np.unique`-based dedup already neutralizes raw duplicate density. The real problem is that the *symmetric window itself* is genuinely large (13k–14k **unique** 0.10m cells after dedup) — a regular anchor's descriptor ends up spanning several meters of straight corridor, and any 512-point sample of that span is intrinsically self-similar/degenerate. The window size, not point density, is the problem, and it was never supposed to apply to anchors other than anchor 0.

### Cross-validated against two independent historical (pre-flag) batches

| batch | return-phase attempts | both current+next confidence < 0.35 |
|---|---:|---:|
| `line2_stopgate_redesign_30ep_20260804` (13 episodes) | 4,751 | 0 (0.00%) |
| `promotion_shadow_reliable30v3_20260731` (16 episodes) | 5,697 | 1 (0.018%) |

Combined: **1 in 10,448 real attempts, across two batches spanning both successful and failed round-trips.** This confirms the failure mode is specific to this flag's blast radius, not a latent baseline risk that just happened to go unnoticed — the mechanism (silent, total return-None on simultaneous sub-floor confidence) had essentially never fired before this week.

**Structural note (independent of the fix)**: a synthetic unit test directly against `RouteMemoryAgent.update_relocalization` confirms the "both sides low" failure mode is a genuine, pre-existing structural gap that *any* future cause of simultaneous low confidence would still hit — the fix below removes this week's trigger, not the underlying fragility. The gate is also asymmetric: a low-confidence **next** always blocks the controller (baseline promote logic needs `next_est` too), but a low-confidence **current** alone does not — `quality_ok = gate_current_est is None or ...` treats a missing/filtered current as an automatic pass.

## Part 2 — fix

`route_memory_agent.py::update_outbound_motion` used to route every regular anchor placement (1, 2, 3, ... — anchor 0 is never placed here; see `initialize_start_anchor_descriptor`) through the same wide symmetric merge that anchor0_landmark needs:

```python
if self._should_save_anchor():
    if self.multiframe_anchor_symmetric_enabled:
        self._begin_pending_anchor(descriptor=descriptor, metadata=metadata)
    else:
        self._append_anchor(descriptor=descriptor, metadata=metadata)
```

Fixed to always use the single-frame path for regular anchors:

```python
if self._should_save_anchor():
    self._append_anchor(descriptor=descriptor, metadata=metadata)
```

`_outbound_symmetric_frame_buffer` (the shared buffer anchor0_landmark's own, separate merge call in `round_trip_eval.py` reads directly) is still populated unconditionally when the flag is on — this change only stops *regular* anchors from being built via the wide-window merge. Anchor0_landmark's own descriptor-building code path is untouched. Full diff: `code/route_memory_agent_multiframe_scope_fix.patch`.

An earlier attempted fix (voxel-dedup the merge output in `_merge_point_frames`) was implemented, empirically tested, found to have **zero effect** on the actual confidence numbers (see above), and reverted — kept out of the final patch entirely.

## Part 3 — smoke-test result (ep310, post-fix)

Ran episode 310 directly (bypassing the batch driver) with the fix applied. **Confirms the fix resolves the target failure mode:**

- `controller-start`/`controller-end` fired on **every single attempt** (vs. 0/10 episodes pre-fix).
- ICP call duration dropped from ~9–10s to ~1.7–2s per attempt (anchor descriptors back to normal size).
- Anchor pair **actively promoted 7 times**: `(12,11)→(11,10)→(10,9)→(9,8)→(8,7)→(7,6)→(6,5)→(5,4)` — the original batch produced zero promotions across 10 episodes.
- Episode reached a natural terminal decision (`stop_gate decision=safe_fail`) at step 3276, well inside the step/time budget — not an artificial 3600s wall-clock kill.

**This episode still did not round-trip successfully** — it stalled at `(5, 4)` for the final ~650 steps and drifted from 4.08m to 5.95m from home before stop_gate gave up (`safe_fail`, not a wrong-stop or crash). Root cause of *this* secondary failure, traced in code (not yet ground-truth-confirmed against a saved trajectory — see Part 4):

- V3 repeatedly proposed a recovery pair `(3, 4)` (`[anchor-v3-active] WARNING: ignoring direction-inconsistent recovery pair (3, 4) vs local pair (5, 4)`), rejected every time by the controller's own topology/direction-consistency guard (a legitimate, working safety check — not a bug).
- Traced whether this rejection loop could itself be *causing* the drift by silencing navigation guidance (`route_consumers_enabled`, or `current_est` going stale) — **it does not**: `route_consumers_enabled` stays `True` in every branch of `_evaluate_anchor_v3_active_controller` including `direction_mismatch_ignored`, and `_select_sequential_pair_relocalization` keeps returning a fresh `current_est`-based `selected` estimate every attempt even when promotion is rejected. Guidance was not lost/absent during the stall.
- Most likely explanation (code-consistent, not yet ground-truth-verified for this specific run): a confidently-wrong `current` (anchor 5) ICP reading kept feeding the VLM a misleading-but-present hint, while V3's own (correct) attempt to redirect was blocked by the direction-consistency guard — the same "confidently-wrong ICP" pattern documented repeatedly elsewhere in this project (e.g. `investigations/2026-07-24-confidently-wrong-open-problem-summary/`, 96.7% of return failures traced to confidently-wrong ICP), not a new bug introduced by this fix or by `--anchor_v3_active` itself.

## Part 4 — open items / known gaps

1. **This smoke test's measurement JSON was never saved to disk** (searched the whole `NaVILA-Bench` eval_results tree and beyond, found nothing) despite the episode completing cleanly (`[INSTRUMENTED-DONE] is_stop_called=True`, orderly `Simulation App Shutting Down`). The outer launcher wrapper script died with SIGTERM (exit 143) partway through the return phase for an unclear reason — likely a background-task lifetime limit in the harness this session ran under, not an Isaac Sim/eval-script fault (the child eval process kept running and completed on its own after the wrapper died). The full live stdout log was preserved locally during the session but is **not included in this push**. Re-running via a properly detached launch (e.g. `systemd-run --user`, per this project's own established lesson about jobs needing to escape session scope) would both avoid this and produce a real saved measurement file for the anchor-5-drift question in Part 3.
2. **The anchor-5 direction-mismatch stall (Part 3) is unconfirmed against ground truth** — needs a saved trajectory + `route_relocalization_diagnostics` to check the true bearing error of the accepted `current` (anchor 5) estimate during the stall window, the same methodology as `investigations/2026-07-15-50ep-batch-current-next-simultaneous-failure/`.
3. **The structural "current+next simultaneously below floor" gap (Part 1) is not fixed, only its current trigger is.** No mechanism currently detects or recovers from a total, silent `update_relocalization → None` stretch if it recurs from a different cause. Worth deciding whether this needs its own guard (e.g. a stall-detector independent of `min_relocalization_confidence`) given how catastrophic a *sustained* occurrence is (full 3600s timeout, zero data) versus how cheap an *isolated* one is (one skipped update).
4. **Original 30ep batch was stopped mid-run by the user, not completed.** Killing the driver cleanly required `SIGKILL` on the driver PID directly — a plain `SIGTERM` is caught by the driver's own `trap cleanup_current_processes EXIT INT TERM`, which cleans up the in-flight episode but then **continues the loop into the next episode** rather than exiting. Worth fixing in `run_manifest_batch_driver.sh` if a soft-stop-and-exit behavior is ever needed (currently trap-triggered cleanup and script exit are conflated).
5. A recommended next step, not yet done: re-run a clean multi-episode smoke/shadow batch (post-fix) via a properly detached launcher, both to confirm the fix holds beyond one episode and to get a ground-truth-backed answer for Part 3.

## Code

- `code/route_memory_agent_multiframe_scope_fix.patch` — the fix described in Part 2, against `runtime_candidate/scripts/route_memory_agent.py` in the Route2 core runtime (`navila-route2-v11-core-20260801`).
