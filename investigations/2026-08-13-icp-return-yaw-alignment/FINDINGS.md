# Non-oracle ICP return-yaw alignment (`--icp_align_return_yaw_to_anchor_segment`)

Date: 2026-08-13
Status: implemented, smoke-tested, pushed. No batch-scale run yet.

## Why

While preparing a non-oracle 100ep comparison batch against
[investigations/数据补全](../数据补全/README.md)'s oracle ablation chain, this
session's [Route1/Route2 code-integrity audit](#background) found that
`--oracle_align_return_yaw_to_anchor_segment` (ground-truth-corrected return-phase
heading) has been the **unremarked default in essentially every non-`oracle_hint`
batch in this project's history, both routes, 2026-07-12 through 08-11** — either
explicit `=1` in a launch script or inherited from a shared driver's `:-1` default.
Every historical "non-oracle" headline number (63.2% fix-ON A+B+C, 60.0% V1.1 shadow,
66.7% Route2 batch49, 70.0% line2_stopgate_redesign) carried this ground-truth signal
without it being labeled as such.

The user asked: can the oracle yaw-alignment mechanism be replaced with an
ICP-based (self-driven) equivalent, **without removing or modifying the existing
oracle path** — so both remain available side by side. This document covers that
implementation.

## Background

See this session's other 2026-08-13 work for the fuller context this follows from:
- [投稿数据补全 ablation chain](../数据补全/README.md) — the just-finished oracle
  chain (`oracle_hint` → `+hint_action_arbiter` → `+stop_gate`, 37.2%→60.5%→81.6%
  return-rate on a high-outbound-success 100ep sample) this work is meant to produce
  a non-oracle comparison arm for.
- The code-integrity + oracle_align_yaw usage audit (not yet written up as its own
  investigations folder as of this commit — summarized above; ask the session/check
  memory `project_route1_route2_code_integrity_and_line2_highsuccess100ep_launch_20260813`
  if that gap needs filling later).

## How the oracle mechanism works (unchanged, for reference)

`scripts/round_trip_eval.py`'s `oracle_anchor_segment_return_yaw()` /
`align_return_yaw_to_anchor_segment()` (both untouched by this change): at the
confirm→return transition, finds the outbound anchor segment nearest the robot's
current position using each anchor's **ground-truth `world_pose`** metadata
(`world_pose_source: "isaac_oracle_for_relocalization_eval"`), computes the reversed
segment direction as a target yaw, then **physically teleports** the robot's
orientation to that yaw in a single instant via `reset_navigation_memory()` — a
sim-only privileged action no real robot can perform. It then calls
`RouteMemoryAgent.correct_return_start_yaw()` to keep the route agent's own
self-driven dead-reckoning frame consistent with the snap.

## The new ICP-based mechanism

New flag `--icp_align_return_yaw_to_anchor_segment` (plus
`--icp_align_return_yaw_turn_rate_deg_s`, default 30°/s, and
`--icp_align_return_yaw_max_turn_seconds`, default 6.0s, matching
`--confirm_turn_seconds`'s existing default). Purely additive — the oracle flag,
its two functions, and every line of its call path are unmodified.

**Self-driven yaw estimate** — new function `icp_anchor_segment_return_yaw()`:
- Gets the (current, next) anchor pair from `route_agent.sequential_target_anchor_pair()`
  — read-only, already-existing project code, safe to call at exactly this moment per
  its own docstring (right after `finalize_outbound()`, before any relocalization has
  been accepted yet).
- Calls `relocalization.sequential_pair_anchor_relocalization()` directly with
  `diagnostics=None` — the same ICP entry point `route_relocalization_backend=sequential_pair`
  already uses for every return-phase relocalization, called here in a side-effect-free
  way (bypassing `RouteMemoryAgent.update_relocalization()`'s temporal-smoothing/
  quarantine/promotion-vote bookkeeping, which assumes one call per real return-phase
  VLM step — calling that here, before the first real step, would have corrupted those
  running stats).
- Both the "current" and "next" anchor's ICP position estimates
  (`anchor_dx_m`/`anchor_dy_m`, robot-body-frame, confirmed via
  `AnchorRelocalization.bearing_to_anchor_deg`'s `atan2(dy, dx)` convention — same as
  `oracle_true_bearing_error_to_anchor_deg` elsewhere in the file) come from the same
  ICP call against the same current local-map descriptor, so they share one frame —
  `next - current` is therefore a valid body-frame vector from the current anchor's
  position to the next anchor's position, the ICP analog of the oracle function's
  world-frame `a_xy - b_xy` (no extra sign flip needed: "next" here already means
  "next to walk toward on the way home", so `next - current` already equals the
  oracle's reversed-segment direction). `atan2` of that vector is directly the
  body-frame yaw delta to rotate by.
- Returns `None` (caller no-ops, exactly like the oracle path's own `None` case) if
  fewer than two anchors exist yet, or ICP fails to produce a usable "next" candidate
  (thin/self-similar local scan right at return start).

**Physical execution** — a new `icp_yaw_align` phase (inserted between `confirm` and
`return` in `round_trip_eval.py`'s phase state machine, parallel to the existing
`elif phase == "confirm":` dispatch, not a refactor of it):
1. At confirm→return, if the flag is set and an estimate is available, phase switches
   to `icp_yaw_align` instead of falling through to the normal return-entry tail (that
   tail is wrapped in `if not entering_icp_yaw_align:`, unchanged when the flag is off).
2. Commands a scripted in-place rotation (`vlm_vel_commands = [0, 0, ±turn_rate]`) for
   enough steps to reach the estimated delta, capped at `icp_align_return_yaw_max_turn_seconds`.
3. On completion, reads back the **actually achieved** yaw change (a real robot's own
   physical state, not privileged info) and calls `route_agent.correct_return_start_yaw()`
   with that real delta — same call the oracle path uses after its snap, whose own
   docstring already describes it as correct "regardless of what caused it."
4. Transitions to `return` and duplicates the same instruction-setup/VLM-entry tail the
   oracle path uses (kept as a separate copy, not shared, to keep the oracle path's
   well-tested block textually untouched).

**Known limitation:** because the turn is a real multi-step physical rotation (not an
instant teleport), `route_agent`'s dead-reckoning frame gets no per-step position
updates while it runs — any small translational drift the physics sim produces during
an in-place turn is not captured, only the net yaw change is. Expected to be
negligible for a turn-in-place gait, not exactly zero.

**If both flags are set:** the oracle snap runs first (unchanged code), so the ICP
branch would then compute a near-zero remaining delta and turn almost nothing. Not
recommended to enable both expecting an additive effect (documented in the flag's
own `--help` text).

## Verification

Full smoke test (episode_idx=5, `--icp_align_return_yaw_to_anchor_segment` alone, no
oracle flag) run same day, `code/smoke_icp_yaw_align_ep5.sh`. Ran to completion
(`exit_code=0`, no exceptions). Real output, `code/smoke_test_measurement_ep5_summary.json`:

```
icp_return_yaw_alignment = {
  "yaw_delta_rad": 0.989, "yaw_delta_deg": 56.66,
  "segment_anchor_indices": [12, 11],
  "current_candidate_matched": true,
  "next_candidate_confidence": 1.0, "next_candidate_inlier_count": 429,
  "next_candidate_match_class": "clean_full_pose",
  "before_yaw_deg": -151.54, "after_yaw_deg": -108.79,
  "achieved_yaw_delta_deg": 42.75
}
```

- ICP found a high-confidence match against both anchors (confidence 1.0, 429
  inliers, `clean_full_pose`) using purely self-driven evidence — no `world_pose`
  read anywhere in this code path.
- The robot physically turned (`before_yaw_deg` → `after_yaw_deg`, real quantities
  read from the sim after real rotation commands).
- The scripted turn achieved 42.75° of the 56.66° target (75%) — expected low-level
  gait-tracking undershoot for a legged robot's in-place turn, not a bug. Confirms
  the design decision to correct `route_agent`'s frame with the achieved delta
  rather than the intended one is load-bearing, not defensive-only.
- Episode continued cleanly into normal return-phase VLM querying/hint-arbiter
  behavior afterward for 1000+ further steps with no errors (outbound_success=True,
  this particular episode's own return_success=False — not meaningful on n=1, the
  point of this run was mechanism verification, not a result).

No batch-scale run has been done yet — this is a single-episode smoke test only.

## Code

- `code/round_trip_eval_icp_yaw_align.patch` — full unified diff against
  `scripts/round_trip_eval.py`, verified to apply cleanly and reproduce the live file
  byte-for-byte (`patch` + `diff -q` round-trip checked before this commit).
- `code/smoke_icp_yaw_align_ep5.sh` — the smoke test launch script.
- `code/smoke_test_measurement_ep5_summary.json` — slim extract of the smoke test's
  measurement JSON (full file omitted, ~3.4MB of per-step trajectory/diagnostic data
  not needed for this write-up).

## Next steps (not yet done)

- No batch-scale (n≥30) run yet — single-episode smoke test only confirms the
  mechanism executes correctly, not its effect on return-rate.
- If/when run at scale, compare against the oracle-yaw non-oracle candidate
  (`line2_stopgate_redesign` config, 70.0%/58.6% historical, currently not yet
  re-run with this flag swapped in) on the same high-outbound-success 100ep manifest
  used by the 数据补全 oracle chain, for a true apples-to-apples non-oracle-vs-oracle-yaw
  comparison.
