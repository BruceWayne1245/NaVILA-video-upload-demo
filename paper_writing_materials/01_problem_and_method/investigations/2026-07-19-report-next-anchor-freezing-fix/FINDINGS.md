# 2026-07-19: root-caused the report_next_anchor freezing bug, found multiframe_submap makes matching harder, implemented and tested both fixes, root-caused a second unrelated infra bug (crashed episodes hang forever), and re-examined the 07-18 hint-vs-hint_action causal split against the current-vs-next discovery

## 0. Context

Following the 2026-07-18 discovery that the injected hint had always reported "current" (backward-looking, last-confirmed anchor) rather than "next" (forward-looking, unconfirmed candidate) despite the hint text's own "next-anchor vector" label, three live batches were queued to test `--sequential_pair_report_next_anchor`. All three were compromised by a GPU-orphan-process leak cascade (see the same-day batch-forensics entry) and had to be relaunched. This document covers the actual root-cause analysis of the *content* of the fix, done once clean episode data existed from the relaunched `shadow_multiframe_submap_report_next_22ep_20260718` batch (5 usable episodes: 187, 1040, 89, 319, 498 — only `1040` round-tripped).

## 1. The 5-episode result showed a new, previously-invisible failure mode: the hint freezes

Analyzing each episode's `route_memory_hint` phase-event sequence (bearing/distance/confidence to the reported "next" anchor), the 4 failures all showed long streaks of **byte-identical consecutive hint readings** — the same anchor index, bearing, and distance repeated across many consecutive VLM queries, while the robot's true position kept changing:

| episode | round_trip_success | longest consecutive identical-hint run | span (steps) |
|---|---|---|---|
| 187 | False | 3 | 50 |
| 1040 | **True** | 2 | 25 |
| 89 | False | 13 | 900 |
| 319 | False | **19** (83% of all hints in the episode) | 1075 |
| 498 | False | 8 | 425 |

The one success (1040) essentially never freezes; every failure shows substantial freezing.

## 2. Frequency check: is this a mismatch between ICP-attempt rate and VLM-query rate? No.

Measured directly from real trajectory JSONL data (not reasoned about): ICP relocalization actually attempts exactly every 5 environment steps (`--route_relocalization_interval_updates=5`), confirmed via `anchor_dx_m`/`anchor_dy_m` change-points in the per-step trajectory record (gaps are exactly 5, with total regularity) — and this runs unconditionally every environment step regardless of VLM query timing (`update_return_motion` is called outside the `if num_steps == target_steps:` block in `round_trip_eval.py`'s main loop). VLM queries happen far less often and irregularly: 10-301 env steps between queries (mean 46-71 depending on episode), driven by each VLM command's own `time_to_go` duration. So ICP gets roughly **9-14x more attempts than VLM has queries**, on average.

**Direct proof this is not a frequency-mismatch problem**: during `ep319`'s worst frozen stretch (step 1526-2601, 1075 steps), ICP fired **~215 separate attempts** and **zero** produced a change to the reported value, while ~15 VLM queries in that same window all saw the identical stale hint. Attempts were plentiful; the acceptance criteria failed for a long stretch.

## 3. Historical control: the 14/22 baseline (reporting "current," not "next") almost never freezes

Ran the identical longest-consecutive-identical-hint-run methodology across all 34 of the 50 baseline (`shadow_hint_swap_50ep_20260714_accumulated`) episodes with local data:

- Max consecutive identical-hint run across **all 34 episodes**: **3** (one episode, `ep708`, 50-step span).
- 33/34 episodes never repeat a hint at all (max run = 1, mean 1.06).

This is despite the *same underlying mechanism* (see §5 below — both `current`'s and `next`'s cached estimates hold-last-value-on-reject, with zero staleness handling) already being present in the 14/22-era code. It simply never manifested because `current` was refreshed almost every VLM turn in practice.

## 4. Found the freezing is at least partly attributable to `multiframe_submap`/`return_frame_buffer`, not (only) to reporting next instead of current

A clean apples-to-apples check using `covisibility_records` (present by default in the measurement JSON — no `--capture_*` flag needed; logs BOTH current's and next's raw per-attempt ICP output every attempt regardless of what gets reported to the VLM): same episode (`ep319`), same anchor (anchor 3) as a next-candidate, comparing the 14/22 baseline (multiframe off) against the 2026-07-18 multiframe+report_next restart batch (`shadow_multiframe_submap_report_next_22ep_20260718`):

| | 14/22 baseline (multiframe off) | multiframe+report_next batch |
|---|---|---|
| confidence mean | 0.505 | 0.310 |
| overlap_ratio mean | 0.550 | 0.317 |
| match_class | 38 clean_full_pose / 36 ambiguous (n=75) | **0 clean_full_pose / 51 ambiguous (n=51)** |
| dx/dy across attempts | stable, converging | wildly bouncing, no convergence (e.g. one reading -3.49/-1.38 while neighbors are ~2.4-2.7/1.8-2.7) |

Multiframe's accumulated submap appears to make this anchor's point cloud *harder* to match — plausibly because reprojecting several outbound frames captured from different poses into one merged submap introduces real registration noise between those frames that a single instantaneous scan doesn't have. **n=1 anchor/episode — suggestive, not yet a general statistical claim.** Because the freezing-rate comparison in §3 bundles two simultaneous changes (report_next_anchor AND multiframe), it can't alone separate "reporting next is inherently more freeze-prone" from "multiframe made matching harder" — the 2026-07-19 relaunch (§7 below) deliberately runs `report_next_anchor` WITHOUT multiframe, as the clean isolation test.

## 5. Root mechanism, confirmed by direct code inspection (not inference)

`_propagate_latest_relocalization` (`route_memory_agent.py`) dead-reckons `_latest_relocalization` (current's cached pose) forward using real per-step odometry when no fresh correction lands — originally wired into `update_return_motion` on 2026-06-28 per commit `697dc6a` ("Add uncertainty-gated hints, lateral-exclusion odometry, and blackout noise inflation"). It has **zero call sites anywhere in the current, uncommitted workstation checkout** (confirmed via `grep` across the whole repo) — the call was silently dropped, sitting inside a 2241-line-uncommitted diff relative to the repo's last real commit (`3842156`), most likely an unintentional side effect of the 2026-07-16 `return_frame_buffer_enabled` rewrite of that same function (the diff shows the deletion in the exact same hunk as the new frame-buffer code; no comment documents an intentional removal).

**Neither `current`'s nor `next`'s cached estimate has any time/attempt-based staleness handling today** — both freeze completely solid on repeated non-confirmation. `current` historically got away with it only because its own re-confirmation rate was empirically high (it's the already-reached, nearby anchor), not because of any surviving protection mechanism.

## 6. Fix implemented and tested: `--sequential_pair_report_next_anchor_suppress_if_stale`

Per the user's explicit design constraint: **not** an odometry-based propagation/interpolation fix ("里程计很容易导致漂移" — odometry drifts too easily to trust for this), so `_propagate_latest_relocalization` was not revived. Instead:

- New monotonic counter `self._next_candidate_update_seq` increments in `_select_sequential_pair_relocalization` at the exact line that updates `_latest_next_candidate_relocalization` (i.e. only when a fresh `next_est` is accepted this attempt).
- `inject_hint()` (the sole per-VLM-query call site for hint generation) records the counter's value at each call in `self._next_candidate_seq_at_last_hint`; if the counter hasn't advanced since the previous VLM query, returns `base_instruction` completely unmodified (no System Hint line at all, `event=None`) instead of repeating a known-stale hint. The first hint of an episode is never suppressed (no prior reference point).
- New flag `--sequential_pair_report_next_anchor_suppress_if_stale` (off by default, no-op unless `--sequential_pair_report_next_anchor` is also on), wired through `round_trip_eval.py`'s argparse and the `RouteMemoryAgent(...)` constructor call.
- 6 new unit tests in a new `SequentialPairReportNextAnchorSuppressIfStaleTest` class (`tests/test_route_memory_agent.py`): default-off, no-op when `report_next_anchor` is off, first-hint-never-suppressed, suppressed-when-stale, not-suppressed-when-fresh, repeated suppression across several consecutive stale VLM queries. Full suite: 280 tests, zero regressions (up from 266 pre-session).

**Not yet live-batch-validated as of this writing** — that's what the 2026-07-19 relaunch (§7) is for.

## 7. Separate, unrelated infra bug found and fixed while investigating why a batch looked stuck: crashed episodes hang forever instead of exiting

While killing a stuck run, `sequential_pair_report_next_anchor_50ep_20260718`'s `ep4` was found to have crashed almost immediately (~16s in) with `TypeError: 'NoneType' object is not callable` inside numpy's `_wrapreduction`/`np.add.reduce`, called from `_nearest_neighbor_2d` (core ICP code, `relocalization.py:505`) — looks like transient system-level corruption (same class as `ep367`'s `transformers` import crash and `ep368`'s `scan_context.py` TypeError from the earlier batch-3 forensics), not a deterministic logic bug.

**Root-caused why the process then sat hung for 1.5+ hours instead of exiting or being detected as dead**: confirmed directly via `/proc/<pid>/status` and `top` that the crashed python process was in `R` (running) state at 106% CPU with **244 threads** and 3.5GB GPU memory still held, ~100 minutes after the traceback printed. `round_trip_eval.py`'s `if __name__ == "__main__":` block had **zero exception handling around `main()`** (`main(); simulation_app.close()` — no try/except/finally) — when `main()` raises, `simulation_app.close()` (which would shut down Omniverse Kit's ~244 native worker threads for rendering/physics/etc.) is never reached, so the Kit runtime keeps running indefinitely on its own, burning CPU/GPU, until the outer bash `timeout`'s 7200s/SIGKILL eventually arrives — and even then, per the earlier zombie-process finding (same-day batch-forensics entry), the SIGKILL doesn't always cleanly reach every one of Kit's spawned threads/processes.

**This one missing `try/finally` plausibly explains two major recurring infra pathologies documented across this project's history**: (1) any code exception (not just genuine infinite loops) turns into a full 2-hour wasted timeout instead of a fast, clean failure; (2) the eventual forced kill sometimes still leaves GPU-memory-holding orphans.

**Fix implemented**: wrapped `main()` in `try: main() finally: simulation_app.close()` in `round_trip_eval.py`. `py_compile` clean, full suite re-run (280 tests, zero regressions — same run as §6, both fixes landed together).

## 8. Batches killed and relaunched 2026-07-19 with both fixes plus a config discrepancy fixed

Before relaunching, the running `sequential_pair_report_next_anchor_50ep_20260718` batch (whose `ep4` was the hung process from §7) was fully killed per user instruction — the entire Isaac Sim process tree, the VLM server and all ~30 of its worker subprocesses, the top-level orchestrating bash scripts, and the chain script waiting to auto-launch the oracle-supervision follow-up batch. `nvidia-smi` confirmed back to 53MB baseline.

**A config discrepancy was found and fixed before relaunching**: comparing the existing `run_sequential_pair_report_next_anchor_50ep_20260718.sh`/`run_oracle_hint_supervision_50ep_20260718.sh` scripts against `investigations/CANONICAL_CONFIG.md` (see below — this file has since been moved out of a dated subfolder, it's a living reference, not a single day's snapshot) found `--sequential_pair_closure_check` was still off in those scripts, even though `CANONICAL_CONFIG.md` had already been updated (earlier the same day) to recommend it back on. Per explicit user decision, two fresh, dated launcher scripts were written (old 07-18 scripts preserved for history):

- `/home/teambruce/run_canonical_report_next_50ep_20260719.sh` (RUN_TAG `canonical_report_next_50ep_20260719_accumulated`) — the CANONICAL_CONFIG.md config (14/22 baseline + `closure_check` on) plus `--sequential_pair_report_next_anchor` plus `--sequential_pair_report_next_anchor_suppress_if_stale`.
- `/home/teambruce/run_oracle_hint_supervision_canonical_report_next_50ep_20260719.sh` (RUN_TAG `oracle_hint_supervision_canonical_report_next_50ep_20260719_accumulated`) — same base plus `--oracle_hint_supervision`/`--oracle_hint_action_supervision`, chained to auto-launch after the first via a fresh `/home/teambruce/chain_oracle_hint_supervision_after_canonical_report_next_20260719.sh`.

Both launched detached (`PPID=1` confirmed for the batch script, chain script, and the pre-existing orphan-watchdog from the same-day batch-forensics session, which was left running). `ep4` of the first batch finished cleanly (`exit_code=0`) before `ep5` started — the main()-fix and closure_check-re-enable did not break anything obvious in the first real episode.

**How to apply (next session) — this is the true front of the project**: check `/home/teambruce/run_canonical_report_next_50ep_20260719_master.log` for `[master] batch finished`, then re-run this document's §1 methodology (longest consecutive identical-hint run per episode) on the real results to confirm `suppress_if_stale` actually reduces stale-hint exposure, and separately whether round-trip success improves vs. the 14/22=63.6% reference now that `closure_check` is back on and the freeze bug is fixed. The oracle-supervision follow-up batch (`oracle_hint_supervision_canonical_report_next_50ep_20260719_accumulated`) will auto-launch after via the chain script — check `/home/teambruce/run_oracle_hint_supervision_canonical_report_next_50ep_20260719_master.log`.

## 9. Re-examined the 2026-07-18 hint-vs-hint_action causal split against the current-vs-next discovery — partially reframed, not invalidated

The user raised a sharp question: since the hint has always reported "current" (architecturally backward-looking regardless of ICP accuracy), does the 07-18 causal split (`investigations/2026-07-18-batch-forensics-and-oracle-hint-supervision/FINDINGS.md` §6, "Category A" = `ep134,367,319,214`, hint content caused the drift) still hold, or was it confusing "current-vs-next architectural mismatch" with "ICP accuracy"?

**Checked the exact methodology (re-read the original document, not relied on memory alone)**: the "bearing error" cited in that split is `|reported bearing to the anchor − Isaac-oracle ground-truth bearing to that same anchor|` — i.e. it already measures whether ICP was accurate *for whatever it was reporting* (current's true position), a question orthogonal to whether current or next should have been reported at all. `ep319`'s cited example is concrete: hint said "0.58m away," true distance to that same anchor was **6.94m** — a real, ground-truth-verified ICP error, not an artifact of reporting current instead of next.

**But found a real complication, via `ep354` (Category B in the same document)**: its terminal 45-attempt dwell had genuinely *accurate* current-bearing (5.2-5.5° error) and the episode still never recovered (arbiter never overrode once, true distance stuck). This is direct proof that ICP accuracy about current's position is **not sufficient** for the hint to be useful — confirming the user's underlying point that "current" is architecturally compromised regardless of accuracy.

**Reconciling the two**: accuracy and "is current the right thing to report" are separate axes that can both cause harm, in different ways. `ep319`'s specific harm mechanism (a false near-arrival illusion, "0.58m" implying "basically there" when truly 6.94m away) requires the number to be *wrong* — an accurate "6.94m away" would not have triggered anything close to an arrival-adjacent phrasing (`_make_anchor_hint`'s special-casing only kicks in below 0.35m). So `ep319` stands as a genuine, distinct case where ICP inaccuracy contributed real additional harm on top of the current-vs-next issue. **`ep134`/`ep367`/`ep214` (pure bearing-error cases, not proximity-based) were not re-verified this session** — settling whether their *true* (ground-truth) current-bearing was itself already large/unhelpful (which would mean accuracy wouldn't have changed the outcome, per the `ep354` pattern) or genuinely different from what was reported (meaning inaccuracy independently mattered) would require reconstructing each anchor's true world pose at those specific dwell moments — not done this session, flagged as an open question rather than resolved either way.

**How to apply**: don't treat the 07-18 Category A/B split as fully superseded, but don't cite its "hint content caused the drift" framing as if accuracy alone would have fixed those episodes either — `ep354` is direct proof that isn't generally true. `ep319` remains a clean, verified case of ICP inaccuracy causing distinct harm (false-proximity illusion) independent of the current-vs-next architecture. `ep134`/`367`/`214` need the true-bearing reconstruction above before their causal attribution can be considered fully resolved under the current-vs-next framework — this was explicitly deprioritized this session in favor of waiting for real data from the 2026-07-19 relaunch (§8), which is a more direct source of signal than further archaeology on old data.

## 10. Also found this session (tangential): the hint's bearing is not uniformly "backward" even though it always reports current

Pooled across all 50 baseline episodes (1429 hint readings): only 13.4% have `|bearing| > 150°` ("nearly directly behind"); 35.0% are within `0-30°` ("nearly straight ahead") — the single largest bucket. Explained by a "sweep" pattern: right at the moment of promotion, the newly-current anchor is very close to the robot (by construction — promotion requires proximity), so its bearing looks roughly ahead purely by coincidence of timing, not because the hint is genuinely forward-looking; as the robot continues past it without a new promotion, bearing sweeps toward more extreme angles until the next promotion resets it. Measured directly: **55.4%** of the 287 promotion transitions found show `|bearing| ≤ 30°` at the very first reading after promotion (matching the "briefly ahead" model), but **17.4%** are already `>90°` (meaningfully behind) at that very first reading — these are "late" promotions (the `bounded_evidence` vote-accumulation process itself lags behind the robot's true arrival), for which there is no "briefly ahead" phase at all.
