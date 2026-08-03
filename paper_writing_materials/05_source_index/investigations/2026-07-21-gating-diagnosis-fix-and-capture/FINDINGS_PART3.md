# 2026-07-21 — Part 3: live integration, smoke validation, and the fix-ON 100ep launch

Continues [`FINDINGS_PART2.md`](FINDINGS_PART2.md) (registrability, threshold calibration,
Injection A/B/C implementation). Part 3 is the operational step: merging the validated fix
into live, smoke-testing it in real Isaac, and launching the evaluation run.

---

## 1. Reviewed integration (candidate → live)

The Injection A/B/C changes (isolated in `navila-gating-ab-v1/candidate/`) were merged into
the live scripts (`NaVILA-Bench/scripts/{route_memory_agent.py, stop_gate.py,
round_trip_eval.py}`). Pre-merge safety:

- Live was byte-identical to the candidate's `upstream_snapshot/` (no drift since the
  snapshot), so the merge is exactly the reviewed diff — nothing else changed.
- Backups kept: `navila-gating-ab-v1/live_prelaunch_backup_20260721_223423/` and the
  `upstream_snapshot/` itself (revert = copy either back).
- **Post-merge validation against live: 286 existing tests + 22 new reliability tests pass,
  zero regressions.** All eight new CLI flags registered.

All three flags remain default-OFF, so any run that does not pass them keeps canonical
byte-behaviour.

## 2. Smoke test (ep680, fix-ON) — the fix works in the live loop

One episode (ep680, the Injection-C target: batch2 vetoed 258 correct within-radius stops
on its pinned current) run in real Isaac with A+B+C on. Result:

- Ran to completion (~18 min, normal timing), `exit_code=0`, clean Isaac shutdown; produced
  measurement + trajectory + a 951 MB `icp_replay_dataset`. The four reliability flags were
  accepted by argparse in the real Isaac env.
- **Injection C fired end-to-end** (`data/08_smoke_ep680_stopgate_evidence.txt`): at step
  4326 `stop_gate decision=vetoed conf=0.596`, then at step 4336 `decision=deferred
  conf=0.200` — the reliability distrust capped the reported confidence to exactly
  `reliability_low_confidence_floor=0.2` and flipped a veto into a defer, i.e. it stopped
  the gate from suppressing the VLM's stop on an untrusted distance. This is the ep680
  mechanism working live, not just in unit tests.
- Single-episode outcome is VLM-noisy and not the point (this run: `return_success=False`,
  and `distance_to_start_m=None` from the already-documented intermittent measurement-field
  corruption — trajectory intact, so recoverable offline). The smoke's job — "does the
  merged fix run cleanly and does the mechanism activate" — passed.

## 3. Launched: fix-ON 100ep, success-first

Decision (with the user): run **only the fix-ON arm over the full 100 episodes now**, and
decide whether/which episodes to run fix-OFF *after* seeing these results. Rationale:

- VLM non-determinism is large (this project already saw identical-config reruns flip
  episodes, e.g. ep367 success→fail), so restricting to the ~21 known-affected episodes
  could yield far fewer than 21 outbound-successes; the full 100 gives a proper
  outbound-success sample.
- **batch2** (`canonical_report_next_stopgate_100ep_20260720`) already exists as a fix-OFF
  reference on the same 100 episodes / same config, with per-episode ground truth.
- The paired fresh fix-OFF arm (the clean A/B) is deferred, not abandoned — it is the
  proper way to get an attributable return-rate delta and to check "do no harm", and will
  be run (likely on the outbound-success subset, ~26×2) if the fix-ON results warrant it.

**Ordering optimisation:** batch2's 27 outbound-success episodes run FIRST, the other 73
last (`code/run_reliability_fixon_100ep_successfirst_20260721.sh`, two same-tag phases). So
even if the ~35 h run is interrupted overnight, the ~27 episodes that actually reach the
return phase (the only ones the fix can affect) are done first and analysable in the
morning. Set math verified (27 + 73 = 100, union == the driver's list).

- Config: byte-identical to batch2 + `--capture_icp_replay_dataset` (Route-2 dataset: point
  clouds + poses in both would-be arms; capture identical so it cannot confound a later
  delta — RGBD deliberately NOT captured, deferred until the vision decision) + the fix:
  `--sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5
  --sequential_pair_reliability_demote_current --sequential_pair_reliability_distrust_downstream`.
- Output tag: `reliability_fixon_100ep_20260721_accumulated`. Master log:
  `run_reliability_fixon_100ep_successfirst_20260721_master.log`.

## 4. What to analyse from the run

1. **The 27 outbound-success episodes** (finish first): `return_success` vs batch2 ground
   truth — how many recovered, and critically whether any batch2 *successes* regressed
   (the "do no harm" direction; new gating can false-quarantine).
2. **Mechanism-firing counts** (VLM-noise-robust, more diagnostic than pass/fail):
   per-episode `stop_gate` deferred/vetoed/forced (Injection C), which `next` anchors the
   reliability quarantine skipped (A), whether current was demoted (B).
3. The known veto-stop targets (ep680/ep498/ep5): did the fix convert "reached home but no
   valid stop" into a registered stop.

**Expected ceiling (from Part 2 §2):** the fix can only help the ~half of pins that are
U-detectable; the confidently-wrong half is the vision residual. So a partial recovery,
with zero regressions, is the success criterion — not a full fix.

## 5. Status

| Item | Status |
|---|---|
| Merge A/B/C → live + re-validate (308 tests, 0 regressions) | ✅ done |
| ep680 smoke (fix runs live, Injection C fires) | ✅ done |
| fix-ON 100ep launched (success-first, capture on) | ⏳ running (~35 h; 27 success eps first ≈ 9 h) |
| Analyse fix-ON vs batch2 + mechanism firings | ⬜ next (morning) |
| Paired fix-OFF on outbound-success subset (if warranted) | ⬜ decide from fix-ON results |
