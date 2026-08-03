# 2026-07-16 — Short-baseline disambiguation's 0.1%/0% under-triggering root-caused to two promotion-timing races (not just the rare single-attempt bypass); promotion-withholding fix implemented, unit-tested, and offline-validated to raise the raw resolution rate; live batch pending final full validation

**Context**: per explicit user direction, this session stopped trying to leverage existing per-attempt signals (the `current_confidence_ambiguity_gate_enabled` work earlier the same day) and instead went back to `investigations/2026-07-15-50ep-batch-current-next-simultaneous-failure/low_density_lidar_matching_network_investigation.md`'s recommendation to improve the matching primitive itself. That investigation turned out to already be falsified by this project's own prior work: `investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/GLOBAL_REGISTRATION_CHECK.md` (a 360-seed dense search and truth-seeded ICP against real hard-anchor data — the wrong pose is a genuinely *better*-scoring optimum under this project's own ICP metric) and `CORRELATIVE_VERIFIER_CHECK.md` (the survey's own Priority-2 mechanism, a 2D occupancy-grid FFT correlative search, implemented and tested — no reliable improvement, coin-flip level) both concluded the ambiguity is genuine repeated physical structure that fools *any* generic single-frame 2D overlap measure, and recommended shifting priority to why `sequential_pair_short_baseline_disambiguation` (the mechanism actually designed to exploit real parallax — the one thing a single-frame algorithm swap cannot provide) fires on only 0.1% of live events with 0% recall against true bearing errors >45° (`investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/FINDINGS.md`). Per the user's explicit direction (2026-07-16), this document fixes that under-triggering.

## Part 1 — root cause, revised by direct measurement (not just code-reading)

Code-reading initially hypothesized the single-attempt promotion bypass (`gate_current_est is None` at `route_memory_agent.py:1444`) was the dominant trigger, since `2026-07-13-.../FINDINGS.md` §1 confirms `bounded_evidence` was already the live promotion mode in the batch that measured 0.1%/0%. **Direct measurement against that batch's own logged data falsified this as the dominant cause**: walking all 91 real promotions across the 9-episode batch (`route_memory.relocalization_events`, promotion detection via `target_anchor_index` transitions, cross-referenced against `route_relocalization_diagnostics.covisibility_records`):

- Only **4/91 (4.4%)** promotions went through the single-attempt bypass (`candidate_count==1`).
- **18/91 (19.8%)** promotions committed without the anchor having accumulated the required 0.3m of net travel since first being tracked as "next" — and this population is **dominated by promotions going through `bounded_evidence`'s own *normal* multi-vote path**, not the rare bypass. The vote window (default 5 attempts, 3 votes) routinely qualifies and commits faster than 0.3m of travel accumulates, even without ever hitting the bypass condition.

Separately noted (not a target of this fix): `ep5` shows several anchors tracked as "next" for 74-384 attempts while accumulating near-zero net travel (0.003-0.010m) — this is the already-documented "robot physically stops moving" bug (`ep5`/`ep408`, 2026-07-06/07), not a timing race. The release valve (below) lets these promote the same way they do today.

**Combined with the already-known second race**: the pending disambiguation entry for a just-promoted anchor is deleted unconditionally on promotion (`route_memory_agent.py:1468-1470`, `k < next_idx` always drops the just-promoted index) — and since `_yaw_disambiguation_pending` holds at most one entry with monotonically-decreasing anchor indices, this filter wipes the entire pending dict on essentially every promotion in practice.

## Part 2 — the fix

Two new flags, off by default:
- `--sequential_pair_short_baseline_require_resolution` (no-op unless `--sequential_pair_short_baseline_disambiguation` is also on).
- `--sequential_pair_short_baseline_stall_attempts` (default **60** — set just above the worst directly-measured real attempts-to-accumulate-0.3m-travel case (57, `ep408`) across 4 real `icp_replay_dataset` captures, same methodology used for `sequential_pair_promotion_alias_stall_attempts=200`).

When enabled, a "next" candidate's promotion is withheld while its disambiguation entry remains unresolved (created but hasn't accumulated enough travel to confirm or refute), bounded by the stall counter (a release valve — not a permanent block, per this project's "abstain, don't ban" convention, avoiding a repeat of `quarantine_next_quality_enabled`'s 2026-07-15 no-escape-valve cascade). **Revised mid-implementation, per Part 1's measurement**: the withhold applies after *both* the single-attempt-bypass path and `bounded_evidence`'s normal vote path converge on a `promote` decision — not just the bypass branch, since the vote path is where most of the under-resolution actually happens:

```python
if gate_current_est is None or self.sequential_pair_promotion_mode != "bounded_evidence":
    promote = candidate_promote
else:
    promote = self._record_promotion_vote(next_idx, candidate_promote)  # bookkeeping always runs, unmodified
if withhold_for_unresolved_short_baseline:
    promote = False
```

`_record_promotion_vote`'s own vote-history/window/alias-aware-stall bookkeeping always runs unmodified regardless of the new flag — only the final decision is overridden, so nothing about the existing vote mechanics changes.

## Part 3 — offline replay harness fix (prerequisite)

The only existing ICP replay harness (`investigations/2026-07-07-icp-bearing-angle-error/code/offline_replay.py`) never called `update_return_motion()` — it called `update_relocalization()` directly at sampled attempt positions only, so `current_absolute_pose_from_start()` never advanced past `[0,0,0]` for the whole replay, regardless of real captured motion. Any mechanism depending on "how far has the robot moved" (short-baseline disambiguation's entire design) could never resolve under the old harness. This was a known, deferred bug (`investigations/2026-07-12-promotion-fix-live-ab-and-next-behind-decomposition/PROGRESS.md`).

Fixed: the harness now walks every captured step (not just sampled attempts), reconstructs each step's body-frame motion delta from two consecutive real `robot_world_pose` entries (`pose_delta_body`, transcribed from `round_trip_eval.py`'s own implementation since that module can't be imported here — it pulls in Isaac Sim at module scope), and drives that delta through `update_return_motion()` every step (real ICP candidates only computed at the sampled attempt positions). Verified directly: `current_absolute_pose_from_start()` now advances smoothly and realistically (e.g. x: 0 → 0.352m over 55 steps on `ep187`) instead of staying frozen. Also fixed a latent bug this change exposed: the harness used to read `update_relocalization`'s direct return value to determine per-attempt acceptance; since `update_return_motion` doesn't return that value, acceptance is now read from whether `agent.relocalization_events` grew this attempt and its last entry's `accepted` field — avoids stale-truthy `_latest_relocalization` from an earlier attempt being misread as "this attempt accepted."

## Part 4 — validation

**Unit tests**: 8 new tests, `tests/test_route_memory_agent.py::SequentialPairShortBaselineRequireResolutionTest` — default-off, no-op without disambiguation enabled, unresolved pending withholds promotion (even when otherwise close-enough to promote immediately), resolution completing (agreeing or disagreeing) promotes normally with the appropriate `anchor_heading_reliable`, the stall release valve fires after the configured limit with state pruned afterward, and — the trickiest case — confirmed the withhold does **not** add a blanket extra delay to `bounded_evidence`'s normal vote path once a pending entry has already resolved before the vote quota is met (identical promotion timing with the flag on vs off in that scenario). Also renamed the existing `test_pending_history_cleared_on_promotion` → `..._when_require_resolution_off` to make explicit that it documents default/off behavior specifically, not a coincidentally-still-passing assumption. Full suite: **205 tests (197 prior + 8 new), 14 pre-existing skips (unchanged), zero regressions.**

**Offline validation** (using the now-fixed harness, against real `icp_replay_capture_hard11_20260706_accumulated` captures):
- A 60-attempt smoke test on `ep367` reproduced the known baseline almost exactly (`require_resolution=False`: 3 catastrophic >45° errors, 0 flagged, 0% recall) — confirms the validation methodology is sound before trusting any comparison.
- A more sensitive **call-level instrumentation** (every `_check_short_baseline_yaw_disambiguation` invocation's outcome, not just the final reported fire rate — since a 60-attempt sample is too small to expect even one of the rare disagreement events) on 150 attempts of `ep367`: **resolution rate (fraction of calls that resolve at all, agree or disagree) rose from 4.67% (7/150) to 8.0% (12/150)** with `require_resolution=True` — roughly a 71% relative increase, and specifically `resolved_false` (the disagreement case that actually flags `anchor_heading_reliable`) rose from 3 to 4 in this sample. This directly confirms the fix measurably increases how often the mechanism gets a chance to fire, before looking at the rarer final-outcome fire rate.
- A broader validation (200 attempts × `ep367/368/994/1040` × both flag settings, measuring the final accepted-event-level fire rate/precision/recall against ground truth, the same methodology as the original 0.1%/0% measurement) is running; results to be added once complete.

## How to revert

Omit `--sequential_pair_short_baseline_require_resolution` (default off). No other code path is touched when off.

## Pending / next steps

1. Finish the broader offline validation (in progress as of this writing) and report the final fire-rate/precision/recall comparison.
2. If meaningfully improved, launch a live 22-episode batch (same style as the two prior 2026-07-15/16 A/Bs) comparing against the known 14-success/8-failure baseline.
3. Be honest about the ceiling regardless of outcome: this fixes the *triggering* race conditions, not the underlying finding that ~79% of bad anchors show attempt-to-attempt "unstable/spread" error rather than one fixed wrong pose (`2026-07-13-.../FINDINGS.md` §6) — a population this two-vantage-point design may never catch even with perfect triggering. That remains open, explicitly out of scope for this fix per the user's direction.
