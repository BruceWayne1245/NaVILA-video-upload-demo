# 2026-08-05 — line2_stopgate_redesign_30ep_20260804 result: 70% return-rate milestone, 3-episode return-failure root cause, infra-loss fixes, and a historical-outbound-success 50ep batch

**This session analyzed `line2_stopgate_redesign_30ep_20260804` (queued overnight 08-04, finished 04:00 08-05 — the batch that turned on all 5 of 08-04's stop_gate/route_memory_agent fixes, 6 flags total). After correcting a driver bug that had silently dropped a real success, the final result is 7/10 = 70% return success rate — the first time this project has crossed the 70% threshold on this metric, beating the prior best of 63% (2026-07-22, `investigations/2026-07-22-best-result-63pct`). All 13 non-round-trip episodes were root-caused into a taxonomy; the 3 genuine return-phase failures turned out to share one mechanism that 08-04's flagship fix (`--sequential_pair_stale_relocalization_distrust`) structurally cannot catch. Separately, all 11 infra-loss episodes were root-caused, one was fixed outright (recovering the data point that produced the 70% result), and a full historical aggregation across every batch this project has ever run was used to build a materially better episode set for the next batch, now queued behind Route2's currently-running batch.**

---

## 1. Result: 7/10 = 70% return success rate (corrected twice from an initial 20%)

Raw batch outcome from `summary.tsv` (30 episode_idx, same set as `promotion_shadow_reliable30v3_20260731` / `line2_phase01_30ep_20260803`): 6 round-trip successes (ep4, 295, 420, 647, 678, 688), 13 real (non-infra) failures, 11 episodes lost to infra (no measurement data).

**Two corrections were needed to get to the real number, in order:**

1. **Denominator correction.** Round-trip/return success rate must be computed over `outbound_success` count, not total valid or total attempted episodes — this project's own historical milestones use this convention (`investigations/2026-07-22-best-result-63pct`'s "12/19=63%" used 19 as that day's outbound-success count, not the episode total). Of the 19 valid (non-infra) episodes in this batch, 9 had `outbound_success=True`; of those 9, 6 round-tripped → 6/9 = 66.7%, not the naively-computed 6/19=31.6% or 6/30=20%.
2. **Infra-loss recovery.** `ep1038` was misclassified as an infra loss — its measurement file (`measurements/1758.json`) shows `round_trip_success: true, distance_to_start: 2.30`, a genuine success, lost only to a filesystem-write-completion race in the driver's post-episode `glob.glob()` (no retry logic existed). Fixed (see section 3). Recovering it: 20 valid episodes, 10 outbound-success, 7 round-trip-success → **final return rate = 7/10 = 70%**.

## 2. The 13 real failures — taxonomy

Cross-checked every non-round-trip episode's trajectory JSONL (`distance_to_start_m`, `distance_to_outbound_goal_m`, top-level ground truth, not the nested `route_memory` shadow field) against `outbound_success`/`return_success` and raw `[stop_gate]`/`[hint_arbiter]` log lines — not log-text pattern matching.

**Headline: 8 of 13 (ep187, 354, 381, 408, 409, 488, 500, 708) never left the outbound phase** — hit a deterministic per-scene step cap (2502 or 1666 steps) while still navigating to the outbound goal. None of 08-04's 6 fixes are return-phase/stop_gate-scoped, so this is out of scope for that work entirely. Sub-split: 2 "missed by a hair" (ep187: 0.202m short of goal at cutoff, ep708: 0.914m short), 4 "far off" (ep354/381/500/488: 2.3–8.5m short, mostly not converging or drifting back away), 2 "frozen in place" (ep408/409, same scene/neighbor pair: `same_pos_count=1000`, the launcher's own stuck-detector ended them).

**2 episodes (ep974, ep1058) are locomotion/RL policy tip-overs**, unrelated to navigation: `env_step=21`, `terms={bad_orientation=True}` — the robot tips over ~18s in, right after the first VLM turn command.

**3 episodes (ep367, ep671, ep1040) are genuine return-phase, stop_gate-scope failures** — see section 4 for the full root cause. Final `distance_to_start_m`: ep367=7.08m, ep671=4.85m, ep1040=1.89m (this last one especially close, see below).

| Category | Count | Episodes | In scope for 08-04's fixes? |
|---|---|---|---|
| A. Outbound-phase timeout | 8 | 187,354,381,408,409,488,500,708 | No |
| B/C. Return-phase failure (frozen next-anchor) | 3 | 367,671,1040 | Partially — targeted by fix #4, doesn't fire (section 4) |
| D. Locomotion/RL policy tip-over | 2 | 974,1058 | No — different subsystem |

## 3. Infra-loss root cause (11 episodes) and 2 fixes applied

**6/11 transient/environmental, no identifiable code fix.** ep134/498/89/680 share two *byte-identical* Python stdlib tracebacks (`UnboundLocalError` in `posixpath.join()`, `ValueError` in `sre_compile` via `torch._dynamo`) recurring across independent processes hours to days apart, on code paths that should be unreachable. Ruled out stale `.pyc`/NFS (`/mnt/SSD4T` is local ext4, files untouched since June/March). The signature looks like memory-corruption/bit-flip under load rather than a source bug — worth a system-health check (dmesg/ECC around those timestamps), not a Route1 code item. ep205/430 are the driver's own watchdog kills (600s no eval_log growth / 2400s per-episode cap) on genuinely slow/hung episodes (heavy `stuck_recovery` cycling), not obviously fixable by config.

**1/11 fixable — FIXED. `ep1038`'s glob race.** Root cause: `run_promotion_shadow_reliable30v3_driver_20260731.sh`'s `extract_measurement_summary()` does a synchronous `glob.glob()` immediately after the episode subprocess exits, with no retry — a filesystem-write-completion race. **Fix**: added a retry loop (up to 10× at 2s intervals = 20s extra budget) around the call before accepting an empty result. This is the fix that recovered ep1038 as a real success and produced the 70% headline number above.

**4/11 underdiagnosed (ep5, 268, 368, 994).** Clean process exit (`exit_code=0`, Isaac Sim's own "Simulation is stopped" message), no traceback, no timeout marker — yet `measurements/` confirmed empty. Deeper dig on ep368: the eval log shows normal `[stop_gate]`/`[hint_arbiter]` output up to step 6151 (with `stale_attempts=489` — correctly detecting real staleness here, unlike the 3 episodes in section 4), then a ~20-minute gap with zero prints (no periodic `[return] step=...` markers that should appear every 500 steps) before a burst of `omni.hydra`/USD mesh-corruption warnings and shutdown. The main step loop appears to hang mid-iteration (not crash, not driver-watchdog-killed — `exit_code=0` argues against that), most plausibly GPU/render contention from a concurrently-running Route2 batch sharing the same GPU, rather than a code bug. Code-read of `round_trip_eval.py`'s finalization path confirmed the `return_timeout` break condition still falls through to a normal measurement write — hitting it is *not* itself a silent-loss path, so the mystery is specifically why the loop stops advancing at all.

**Diagnostic fix applied (additive, no behavior change) to `NaVILA-Bench/scripts/round_trip_eval.py`:**
```python
# right after the main step loop exits, before building the measurements dict
print(
    f"[LOOP_EXIT] num_steps={num_steps} phase={phase} done={bool(done)} "
    f"is_stop_called={bool(env.is_stop_called)}",
    flush=True,
)
```
```python
# around the measurement JSON write
try:
    atomic_json_dump(measurement_path, measurements, indent=4)
except Exception as exc:
    print(f"[MEASUREMENT_WRITE_FAILED] path={measurement_path} error={exc!r}", flush=True)
    raise
print(f"[MEASUREMENT_WRITE_OK] wrote {measurement_path}", flush=True)
```
Next time this bucket recurs, the log will show whether the loop ever exited at all (vs. hung mid-step) and whether the write itself succeeded, closing the current observability gap.

**Net effect on the 50ep decision:** only 1 of 11 was a clear, cheap, applied fix; the largest bucket (4 stdlib crashes + 2 hang/timeout cases) has no identifiable code-level fix and should be expected to recur proportionally in any future batch regardless of Route1 changes; the 4 silent-no-output episodes now at least leave a diagnostic trace.

## 4. The 3 genuine return-phase failures (ep367, ep671, ep1040) — corrected root cause

Initial hypothesis (later disproven by reading the actual code): fix #4's staleness counter tracks the wrong role (current vs. next). **This was wrong** — `route_memory_agent.py` line ~4103 confirms `_next_stale_attempts`/`_current_stale_attempts` are tracked separately per role.

**Real root cause, confirmed via code read + raw `[stop_gate]` line-by-line check across the full return-phase window in all 3 episodes:**

`anchor_remaining` (the value that looks "frozen") is not a live estimate — it's a static per-anchor constant set once at route-recording time (`anchor.route_remaining_to_start_m = anchor.distance_from_start_m`, `route_memory_agent.py` line 2942). Its constancy is expected by design and only changes when `target_anchor_index` itself advances. Fix #4's staleness counter increments only when `by_anchor.get(idx) is None` this attempt — i.e. it guards "no candidate produced," not "the estimate hasn't materially changed."

`stale_attempts=0` throughout the return phase in all 3 episodes, **and the total reported distance `d` genuinely fluctuates attempt to attempt** — not bit-identical (ep1040: 10.27–11.35m across steps 4351–4521; ep367: 12.02–12.92m; ep671: 7.42–8.74m). This is not a caching/freeze bug: a fresh ICP computation runs every attempt and confidently, consistently lands in the wrong ballpark, because `anchor_idx` (the next-role target) stays pinned to the same no-longer-appropriate anchor for the vast majority of the return phase (ep1040: 83/84 attempts on idx=10; ep367: 69/70 on idx=11; ep671: 69/91 on idx=8) — **promotion never advances the next-anchor pointer forward**, and ICP re-matching against that stale target's point cloud from an increasingly wrong viewpoint produces a persistently-wrong-but-fresh reading. `cross_role_distance` tracks `d` closely throughout in all 3 (both wrong together — e.g. ep1040 conf=0.909–0.969 at a false veto) — the well-documented project-wide "confidently wrong, same poisoned identity agreeing with itself, root cause in the promote layer" pattern (first diagnosed 2026-07-23), not the literal-freeze pattern (2026-07-23 `ep1062`: bearing pinned at exactly 11°, distance at exactly 4.0m, genuinely no fresh computation) fix #4 was actually built to catch.

**Most striking single data point: `ep1040`.** At step 4484 the robot was physically **0.014m from home** (essentially arrived). At that exact moment `stop_gate` read `d=10.27–10.29m` at `conf=0.909–0.969` and correctly (given its poisoned input) vetoed the stop attempt at steps 4501/4511. This was not a safety-layer breach — the veto behaved exactly as designed on the data it was given. The failure is that the underlying next-anchor tracking never recovered, so the one truly correct stop opportunity in the episode was never taken; the episode ended at `distance_to_start=1.89m`, close but not accepted.

**Refined framing (in response to the initial "confidently wrong breaks through defenses at multiple levels" hypothesis):** in this specific 3-episode set there is really only **one** failure point — next-anchor promotion never advances — not several independently-breached layers. The downstream "defenses" (`cross_role_agreement`, `stop_gate` corroboration/veto) aren't defeated by a clever failure mode; they're structurally unable to help because they either consume the same poisoned reading directly, or their "independent" second signal (the other role) is not actually independent when both roles' tracking derives from the same stalled promotion state.

**Fix #4 is solving a real but different problem than what manifests in these 3 failures.** The mechanism that should be relevant — `sequential_pair_promotion_anomaly_gate` (fix #3, meant to catch bearing jumps/distance collapses) — has no visible per-attempt firing log in any of the 3 episodes; no promotion-voting diagnostic log line exists in the codebase at all currently. `alias_stall_attempts=200`'s relief threshold also never kicked in during ep1040's 3300+-step pin, plausibly because this is a one-sided stall (voting never accumulates evidence to advance), not an alias-oscillation case (bouncing between two candidates) that mechanism was built for.

**Conclusion: it is too early to design a targeted fix off 3 episodes.** The next concrete step, once there's more data, is likely adding promotion-voting diagnostic logging (to make "why doesn't it advance" observable at all) rather than tuning fix #4's thresholds, which are structurally the wrong lever for this failure mode.

## 5. Historical outbound-success aggregation — building a better episode set

Motivated by section 2: `reliable30v3`'s 30-episode set, despite its name, was never actually selected for outbound reliability. Several of its episodes have a long, consistent history of near-zero outbound success (e.g. ep381/ep409: 0% across 10 historical attempts each; ep974/ep1058: 0% across 6–8 attempts) — not bad luck this batch, a durable property of those episodes.

Aggregated every `batch_logs/*/summary.tsv` this project has ever produced (185 files, 279 distinct `episode_idx` seen, 84 with ≥3 historical outbound attempts) into a per-episode outbound-success rate. 34 episodes have a **perfect 100% historical outbound success rate** across 3–41 attempts each (e.g. ep368: 41/41, ep5: 40/40, ep367: 36/36); several more sit at 85–98% across large samples (ep4: 55/56, ep994: 45/46, ep680: 43/48, ep1040: 30/33).

**New 50-episode set for the next batch** — the top 50 by historical outbound success rate (all ≥66.7%, most at 85–100%, all with ≥3 historical attempts): `4 5 19 87 88 89 93 95 123 187 205 214 264 268 276 295 310 319 344 351 355 366 367 368 427 484 489 490 498 539 579 581 646 647 658 669 671 678 680 688 784 815 844 888 961 962 994 1008 1038 1040`. Deliberately keeps ep367/368/671/1040 (section 4's subjects, 91–100% historical outbound success — these will still get tested on the return-phase mechanics) and ep678 (fix #2's motivating case, 67% historical outbound success) for continuity with prior analysis.

Config for the new batch is byte-identical to `line2_stopgate_redesign_30ep_20260804`'s `COMMON_EXTRA` (diff-confirmed against the canonical published copy of that script in `investigations/2026-08-04-stopgate-redesign-and-line2-30ep-retrospective/code/`), i.e. all 6 of 08-04's fixes plus the 3 carried-forward 08-03 flags, unchanged — only the episode set and `PORT_BASE` (66000, to avoid colliding with Route2's concurrently-running 56000-series ports) differ. `RUN_TAG=line2_50ep_historical_outbound_20260805`.

**Queued 2026-08-05T11:38 BST** behind Route2's currently-running `anchor_v2_full_active_recoveryfix30_20260805_tail29` batch (29 episodes remaining as of queueing), via `wait_for_route2_recoveryfix30_then_run_line2_50ep_20260805.sh`, a `systemd-run --user` transient service (`navila-route2-recoveryfix30-to-line2-50ep-queue-20260805.service`, confirmed running under the persistent `user@1006.service` cgroup, survives session disconnect) with its own dedicated lock file — mirrors the established GPU-sharing handoff pattern from 08-03/08-04's own queue scripts. Result not yet known as of this writing.

## 6. Files in this folder

- `code/run_line2_50ep_historical_outbound_20260805.sh` — the new 50ep batch launcher (section 5)
- `code/wait_for_route2_recoveryfix30_then_run_line2_50ep_20260805.sh` — the queue worker currently waiting on Route2
- `code/run_promotion_shadow_reliable30v3_driver_20260731.sh` — the shared driver script, now carrying the measurement-glob retry fix (section 3)
- `code/round_trip_eval_diagnostic_logging.patch` — the two additive `[LOOP_EXIT]`/`[MEASUREMENT_WRITE_OK|FAILED]` log lines added to `round_trip_eval.py` (section 3); the full file is too large and already carries a large unrelated pre-existing uncommitted diff, same exclusion prior investigations in this lineage have made — this patch has the exact context needed to relocate and reapply directly.
