# hint_action_arbiter: turn overrides wrongly gated by forward clear-path check

Date: 2026-08-15
Status: **direction agreed, NOT YET IMPLEMENTED** — to land together with
[investigations/2026-08-15-v11-quarantine-veto](../2026-08-15-v11-quarantine-veto/FINDINGS.md)
as part of this session's Line-2 follow-up batch.

## Decision

Two changes to `hint_action_arbiter.py`, both opt-in/default-off per this
project's established pattern:

1. **Bug fix**: the local-map clear-path check (`local_map.py`'s
   `local_map_clear_path` / `_point_cloud_clear_path` /
   `_occupancy_grid_clear_path`, reason string `occupied_in_local_map_path`)
   currently gates ALL overrides — including pure in-place rotations
   (`desired_kind in ("left", "right")`, which `_replacement_output` renders as
   `"turn left/right {turn_step_deg} degree"`, a rotation-only command with no
   translation). The check tests whether the **straight-line path toward the
   anchor** is obstacle-free — a real question for a `forward` override, but
   physically meaningless for a turn-in-place command, which requires zero
   forward clearance. Fix: skip the clear-path gate entirely when
   `desired_kind` is `left`/`right`; keep it for `forward`.
2. **One-shot full-angle turn**: when a turn override does fire, execute the
   complete needed rotation (bearing-derived angle) in one command instead of
   the current fixed `turn_step_deg` (~15°) increment that requires
   `hint_action_arbiter` to be re-gated and re-approved on every subsequent
   VLM query to complete a large correction. `forward` overrides are
   deliberately left unchanged (see risk discussion below) — keep the existing
   small-increment, re-checked-every-query cadence.

## Why (evidence)

Root-caused via real per-step data (`trajectories/*.jsonl` ground truth vs
`[hint_arbiter]`/`[stop_gate]` log lines) on batch
`line2_closure_off_cooldown_kdtree_100ep_20260815`:

- `ep646`: hint's reported bearing to the needed anchor was verified against
  ground truth (robot's real position + yaw vs anchor's real position) —
  accurate to within 0.6-12° at every checked step (119° reported vs 130.8°
  true at the first override; 149.4° vs 148.8° true four VLM-queries later).
  The hint was never wrong. `hint_action_arbiter` forced the turn exactly
  once (`step=1351, override=True`), then for the next ~125 steps repeatedly
  declined (`occupied_in_local_map_path`) while confidence was still 1.0
  (verified against the real per-attempt `inlier_count`/`confidence` in the
  episode's own measurement JSON — stayed ~420 inliers / conf=1.0 through
  step ~1510, well past the occupied-blocked window). The robot never turned,
  drifted the wrong direction for the whole window, and confidence only
  degraded LATER (a real, gradual inlier-count decay from ~step 1515 onward)
  as a downstream CONSEQUENCE of the uncorrected drift — not the original
  trigger.
- `ep889`: same shape — one `override=True` (~123° turn), then confidence
  collapse on the very next check. No occupied-gate phase this time, but the
  same underlying problem: one small (15°) forced step was not enough to
  complete a ~120° correction, and there was no second chance.

## Scope check across all 22 candidate episodes (2026-08-15 continuation)

Classified early `[hint_arbiter]` sequences for the original 10 "V1.1 can't
rescue" episodes plus the 12 episodes later found to share the same
current-pinning mechanism via cumulative small jumps (see
[investigations/2026-08-15-v11-quarantine-veto](../2026-08-15-v11-quarantine-veto/FINDINGS.md)).
**This fix only matches 5-6 of the 22**: `ep646, ep889, ep1062, ep829, ep806`
(occupied/override on a large bearing, never completed), `ep366` (partial,
mid-episode). It is NOT the dominant failure pattern. Two other patterns
account for more episodes and are NOT fixed by this change — see the
companion document
[investigations/2026-08-15-hint-confidence-collapse-patterns](../2026-08-15-hint-confidence-collapse-patterns/FINDINGS.md)
(in progress as of this commit) for those.

## Decision rationale (why land this now regardless)

- Real, verified benefit: rescues an estimated 4-5 return failures on this
  batch with a mechanistically clean explanation (not a guess).
- No observed downside in this session's investigation: turning in place
  cannot collide (no translation), so removing the clear-path gate for
  rotation-only overrides introduces no new physical risk. `forward`
  overrides — the ones that actually carry collision risk if executed
  open-loop — are explicitly left on the existing small-increment,
  re-checked-every-VLM-query cadence; this fix does not touch them.
- Small, targeted, reversible (opt-in flag), consistent with this project's
  established pattern of shipping narrow fixes rather than broad
  architecture changes.

## Explicitly NOT adopted (considered and scoped down)

The user's original proposal was broader: replace `hint_action_arbiter`'s
short single-step takeover model entirely with a long-horizon takeover that
completes ALL control needed to reach the next anchor in one gated approval
(not just turns). Scoped down to turns only, because:

- A `forward` open-loop takeover removes VLM's frame-by-frame visual
  obstacle-avoidance for the whole traveled distance — real collision risk,
  unlike a turn.
- This session's own measurements put "confidently bad but high-confidence"
  ICP readings at 32-40% even at the strict end (see the V1.1 investigation's
  60-68% precision ceiling on the "confidently bad" bucket) — a single
  trusted-enough-to-override reading is not reliable enough to commit to a
  long blind forward maneuver without any intermediate re-check.

## Implementation sketch (not yet built)

- New opt-in flag on `HintActionArbiterConfig`, e.g.
  `turn_override_completes_full_angle: bool = False`, default off.
- In `check()`, when `desired_kind in ("left", "right")`: skip the
  `local_map_clear_path`/`_topdown_clear_path` block entirely (or gate it
  behind `not turn_override_completes_full_angle` for a safe rollback path);
  when the flag is on, compute the full turn angle from `bearing_deg` instead
  of the fixed `cfg.turn_step_deg` when building `_replacement_output`.
- No change to the `forward` branch.
