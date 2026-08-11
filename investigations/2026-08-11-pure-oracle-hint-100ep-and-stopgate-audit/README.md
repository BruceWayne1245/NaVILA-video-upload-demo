# 2026-08-11 — Pure oracle_hint 100ep Launch, stop_gate Auto-Success Audit, and Hint-Text Comparison

**Read this first if picking this up cold.** Accurate as of **2026-08-11 16:01 BST** (batch still running — check `systemctl --user status navila-oracle-hint-100ep-20260811.service` and `batch_logs/pure_oracle_hint_100ep_20260811/summary.tsv` for current state before trusting any number below).

## Why this session happened

Prep for filling in remaining paper data: a full inventory of existing baseline/oracle_hint/oracle_hint_action/non-oracle>55% batches (see `2026-08-05-paper-data-return-success-summary/` and the pure-baseline 100ep result in `final_data/`) found that **oracle_hint (no arbiter) has never been tested at scale** — only the June hard-11 set exists (n=28 pooled across 3 small batches). The user asked to run it on the same 100-episode canonical manifest as the baseline, but first to verify the run wouldn't be contaminated by an active auto-success mechanism.

## stop_gate audit — the mechanism exists, but is opt-in

`scripts/stop_gate.py`'s `ReturnStopGate` has a `FORCED` decision path: once distance is within `r_in` (default 3.0m) for `confirm_steps` (default 3) consecutive VLM-query attempts, it terminates and declares return success **even if the VLM itself never issued a stop**. `_extract_d_and_conf()` additionally forces confidence to `1.0` whenever `"oracle" in source` — so with `--stop_gate` on, any oracle-sourced run trivially satisfies the high-confidence gate, making FORCED fire very easily.

`--stop_gate` is **off by default**, gated by `if getattr(args_cli, "stop_gate", False):` in `round_trip_eval.py` — not wired automatically into `--route_hint_source=oracle`. Two of the three original June oracle-hint batches did explicitly turn it on (`stop_gate_oracle_hard_fresh_20260629`, `stop_gate_r3_oracle_hard_20260630`); a third (`direct_oracle_hard_fresh_20260629`) did not. Also excluded: `--oracle_align_return_yaw_to_anchor_segment` (checked at `round_trip_eval.py:4117` — calls `align_return_yaw_to_anchor_segment()`, which actively corrects the robot's return-phase yaw using ground truth; a second oracle intervention beyond hint-giving, used by a different June batch).

**Chosen config** reproduces `direct_oracle_hard_fresh_20260629`'s flags exactly (verified against that batch's own `eval_log` argv):
```
--route_memory --route_hint_mode=compact --route_hint_source=oracle --route_relocalization_backend=none
```
No `--stop_gate`, no `--oracle_align_return_yaw_to_anchor_segment`, no `--hint_action_arbiter` (that's the separate oracle_hint_action condition). Everything else (task/num_envs/history_length/round_trip_mode/instruction_rewriter_provider/etc.) is byte-identical to `run_pure_baseline_100ep_20260810.sh`, and the 100-episode `run_episode` list was diffed against that script — 100/100 match, same canonical manifest.

## Launch

New runner: `scripts/run_pure_oracle_hint_100ep_20260811.sh` (copy: `code/run_pure_oracle_hint_100ep_20260811.sh`). `RUN_TAG=pure_oracle_hint_100ep_20260811`.

**Blocker found and resolved before launch:** an unrelated, unexplained full re-run of the pure baseline was already consuming the GPU — `navila-pure-baseline-100ep-20260811.service` (running the original `run_pure_baseline_100ep_20260810.sh` under a fresh `RUN_TAG=pure_navila_baseline_100ep_20260811`, started 14:58, only 8/100 done) plus its `navila-gpu-watchdog-20260811.service`. Purpose/origin unclear — possibly a leftover post-panic confirmation re-run. Stopped both (by explicit user instruction) to free the single RTX 4090 (was at 18GB/24GB used). Its partial `batch_logs/pure_navila_baseline_100ep_20260811/` (8 rows) is abandoned/incomplete and not authoritative — the real finalized baseline number is in `final_data/` (`pure_navila_baseline_100ep_20260810`, 7/39=17.9%).

Launched via the verified linger + `systemd-run --user` procedure:
```
loginctl enable-linger teambruce   # was already enabled
XDG_RUNTIME_DIR=/run/user/1006 systemd-run --user --unit=navila-oracle-hint-100ep-20260811 \
  bash -c 'exec bash /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_pure_oracle_hint_100ep_20260811.sh > /home/teambruce/run_pure_oracle_hint_100ep_20260811_master.log 2>&1'
```
Cgroup confirmed at `/user.slice/user-1006.slice/user@1006.service/app.slice/navila-oracle-hint-100ep-20260811.service` (not a `session-*.scope`) — survives SSH disconnect / closed conversation. Episode 4's actual launched argv was checked in `ep4_eval.log` and matches the intended flags exactly.

## Status as of 2026-08-11 16:01 BST

9 episodes attempted (`code/summary_snapshot_20260811_1601.tsv`), currently on episode 680 (10th). One transient infra failure so far: ep368's VLM server failed to load (`ValueError: too many values to unpack (expected 0)` inside `accelerate`'s `find_tied_parameters`, exit_code=98) — a known-flaky library issue unrelated to the oracle_hint config, batch continued normally to the next episode. At baseline's observed pace (~2.5–5 min/episode) expect ~5–8h total.

## Hint-text mechanism, confirmed via real production data

Extracted directly from `eval_results/.../measurements/*.json` → `round_trip.phase_events`, filtered to `event == "route_memory_hint"` (the `hint` field is verbatim what gets prepended to the VLM instruction as `f"{hint}\n{base_instruction}"`; generated by `route_memory_agent.py`'s `make_hint()` → `_make_anchor_hint()`).

**oracle_hint real sample** (ep4, step 1526, compact mode):
```
[System Hint: route anchor A8 is 1.74 m away, 116 deg to your left; estimated remaining route via anchor is 9.80 m; next-anchor vector dx=-0.77 m, dy=1.56 m.]
```
21 hint events total in ep4, all in the return phase (none during outbound — confirmed `--route_hint_source` only affects return-stage hints per its own argparse help text). ep134 (outbound failed) had 0 hint events — return phase never started, expected, not a bug.

**Compared against the 6 existing round-trip >55% non-oracle batches** (`canonical_report_next_stopgate_50ep_20260719_accumulated`, `reliability_fixon_100ep_20260721_accumulated`, `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`, the 07-26 Route2 Anchor V2 active batch — real `RUN_TAG=reliability_v11_policy_v2_active_50ep_outbound_top_20260725`, run from Route2's own isolated tree `/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725/`, not `NaVILA-Bench/batch_logs/` directly — `anchor_v2_full_active_batch49_20260802`, `line2_stopgate_redesign_30ep_20260804`): **all 6 use `route_hint_source="integrated"` / `route_relocalization_backend="sequential_pair"` and go through the exact same `_make_anchor_hint()` function** — including Route2's Anchor V2/V3, whose controller only decides promote/quarantine/rollback on top of this same relocalization pipeline, it does not replace the hint-text mechanism.

Sample (format is identical across all 6):
```
[System Hint: route anchor A10 is 0.58 m away, ahead; estimated remaining route via anchor is 10.66 m; next-anchor vector dx=0.58 m, dy=0.02 m.]
```

**Real difference is where the numbers come from, not the template:**
- oracle_hint: `direct_oracle_route_anchor_progress()` reads the anchor's exact simulator world-pose directly, `relocalization_confidence` hardcoded to `1.0`, `filter_std_m` always `None` — zero estimation error, ever.
- the 6 non-oracle batches: each return-phase query re-runs LiDAR/ICP registration of the robot's current local map against the "current"/"next" candidate anchors' stored point-cloud descriptors — a noisy estimate that goes through closure-check/promotion-voting/belief-fusion before being reported. Observed directly in the real data: `relocalization_confidence` drifting from 1.0 down to 0.2 within a single episode, `filter_std_m` climbing from ~1.0 up to the 10.0 cap. This ICP pipeline is the subject of the project's own "confidently-wrong ICP" line of investigation (see `2026-07-24-confidently-wrong-reanalysis` etc.).
- A `filter_lost` hedge template exists only for non-oracle (`_filter_lost()` can never trigger when `filter_std_m` is always `None`, i.e. oracle can never hit it):
  ```
  [System Hint: position uncertain (σ≈10.0 m, filter lost lock); route anchor A1 is near but position estimate unreliable; next-anchor vector points ahead. Continue toward the outbound start using the visual instruction — do NOT stop until you visually confirm you are back at the starting location.]
  ```
  Observed firing in 3 of the 6 batches (the earliest, `canonical_report_next_stopgate_50ep_20260719_accumulated`, predates the `distance_authority_low_reliability` field entirely — an even earlier code revision).
- Minor note: `anchor_v2_full_active_batch49_20260802`'s `distance_authority_low_reliability` field reads `None` rather than `False/True` in its records — likely a different code path/flag state for that batch, doesn't affect hint-text format but worth knowing if comparing fields across batches programmatically.

## Hint-trigger-count methodology (for later per-episode statistics)

Confirmed feasible and already spot-checked on the first 3 completed oracle_hint episodes: count of `phase_events` entries with `event=="route_memory_hint"` per episode = number of times the hint was recomputed/injected during return (no staleness-suppression flags are active in this batch, so every return-phase VLM query gets a fresh hint). ep4: 21, ep5: 162 (notably longer/more return-phase queries, still failed), ep134: 0 (outbound failed, return phase never reached). Once the full batch completes, this can be tabulated batch-wide (distribution, correlation with return success) the same way.

## Auto-reboot-on-freeze watchdog (verified working, set up 2026-08-10, unrelated to today's new work but re-confirmed today)

Persisted at `/etc/sysctl.d/99-navila-watchdog.conf`:
```
kernel.panic = 60
kernel.hardlockup_panic = 1
kernel.softlockup_panic = 1
```
Re-verified 2026-08-11 16:0x that live sysctl values match the file exactly, and that the underlying detectors are enabled (`kernel.nmi_watchdog=1`, `kernel.watchdog=1`, `watchdog_thresh=10`) — so the full chain (soft/hard lockup detected → converted to a kernel panic → kernel auto-reboots 60s later instead of hanging forever) is live. This directly targets the confirmed-real kernel panic that killed the original `pure_navila_baseline_100ep_20260810` launch at ep408 (see `2026-08-10-100ep-baseline-batch/README.md` for the full incident writeup). Caveat carried over from that doc: this catches kernel-level hangs, not every conceivable freeze mode (e.g. a GPU that wedges without the CPU ever entering a kernel-space lockup wouldn't trip it) — no second incident has occurred since to confirm it fires in practice.

An unrelated, pre-existing, always-broken distro service was also noticed in passing: `ipmiutil_wdt.service` fails every boot (`Cannot open an IPMI driver` — this consumer board has no real BMC). Not something the user configured; not a substitute for the sysctl fix above; not actionable.

## For a fresh session picking this up

1. Check current batch state: `systemctl --user status navila-oracle-hint-100ep-20260811.service`, `wc -l /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_100ep_20260811/summary.tsv`.
2. If complete: apply the same outbound/return-success merge methodology as `final_data/README.md` did for the baseline (check whether any of the same historical pre-canonical-100 episodes need merging in) to get a final comparable number, then push a `final_data`-style summary.
3. Don't re-derive the stop_gate/hint-text findings above from scratch — they're fully covered here with real data, not hypothesized.
