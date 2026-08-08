# Anchor V3 — end-of-day summary and next steps (2026-08-08)

Reading order for this folder: `HANDOFF.md` -> `PROGRESS.md` (dataset build,
morning) -> `TRAINING_RESULTS.md` (NaN bug + baseline) ->
`HYSTERESIS_AND_BLIND_RECOVERY_FINDINGS.md` (hysteresis fix + stop_gate
research + V2 comparison) -> `ONLINE_ADAPTER.md` (self-contained inference
adapter). This file is the compressed pointer + the actual TODO list for
whoever picks this up next.

## What shipped today, in one table

| stage | outcome |
|---|---|
| Dataset | 5,691 frames / 140 episodes, scene-disjoint (train 4,128f/94ep, val 1,133f/31ep, test 430f/15ep) |
| NaN training bug | found (`-inf * 0.0` in loss fallback) and fixed; verified across all 717 train+val sequences before retraining |
| Baseline checkpoint | epoch 2, val_total 1.719, test action acc 73.95% (vs 62.8% majority baseline) |
| Hysteresis bug | found via systemic scan (15/46 held-out episodes, 33%, had 3+-frame KEEP/PROMOTE streaks); consistency-loss fix attempt failed (verified); keep-class-weighted fix worked (15/46 -> 4/46 episodes) |
| **Current best checkpoint** | `reports/anchor_v3_keepweighted_checkpoint.pt` (epoch 2, val_total 1.644): action 75.58%, pair 74.87%, belief 73.27%, pair-adjacency 100% |
| stop_gate/blind-recovery | researched, explicitly out of V3's mandate; honest negative finding (53.6% precision using V3 confidence as a trust signal -- not reliable enough, not pursued further) |
| vs. Anchor V2 (previous model) | 4 of 6 of V2's own named failure episodes (4, 95, 658, 680) resolved; 2 (367, 88) still open with a different signature |
| Online adapter | `anchor_v3/online_adapter.py` built, self-contained, touches nothing in `navila-route2-v11-core-20260801`; isolated smoke test passed on real recorded episode 386 (27/27 attempts contract-valid) |

## Still-open items (not fixed, not forgotten)

1. **ep367 / ep88 residual failure mode.** Distinct from the now-fixed
   stable-anchor hysteresis: the model lags (`promote->keep`, i.e. under-
   reacts) when the *true* anchor is changing rapidly across several
   positions in a short span. Only 2/46 held-out episodes show this now, but
   it's the same signature V2's own investigations named for these exact
   two episodes ("pair-lock deadlock") -- worth specifically checking if
   either comes up again in any future live test.
2. **stop_gate blind-recovery: no fix attempted, by design.** V3's raw
   confidence is not reliable enough on its own (53.6% precision, same
   "confidently wrong" pattern documented elsewhere in this project). If
   this is ever revisited, don't reuse the raw confidence output directly --
   would need either a dedicated classifier trained specifically for
   "is this evidence trustworthy" (different objective than current/next
   selection) or a different feature combination. Not blocking V3's actual
   mandate.
3. **Early overfitting signal.** All three training runs (baseline,
   consistency, keep-weighted) bottom out at epoch 2 of 5 and get worse at
   3-4. Never investigated further (more epochs / different LR schedule /
   more data) since epoch-2 checkpointing already handles it correctly, but
   worth knowing this model saturates fast on the current dataset size.
4. **Dataset size ceiling.** 140 replayable episodes came from 872 audited
   directories; the filtering criteria that produced that ~16% yield was
   never revisited today. More data is the most likely lever if accuracy
   needs to go materially higher than the current ~75%.

## Next steps, in the order they should happen

1. **Wire the online adapter into `route_memory_agent.py`.** Not started.
   This crosses the original 08-08 handoff's stated boundary ("no runtime
   integration authorized") and touches a file Route2/Codex actively shares
   -- get an explicit go-ahead before starting, same as the online-adapter
   scope decision earlier today. Should land as a new opt-in flag,
   off-by-default, per this project's established convention for every
   prior mechanism (bounded_evidence, alias_aware, reliability_quarantine,
   etc. were all introduced this way).
2. **Live smoke test** (1-3 episodes): confirm the wiring runs inside the
   real evaluator without crashing and produces sane-shaped decisions --
   not yet a quality check.
3. **Shadow test** (a real batch, e.g. 30-50 episodes): V3 runs alongside
   the existing decision-making and logs its own predictions but does not
   control anything. Compare shadow predictions against real outcomes,
   specifically re-checking whether ep367/ep88-style episodes still show
   the lag pattern live (offline replay and live behavior have diverged
   before elsewhere in this project).
4. **Only after shadow validates:** consider active integration. This
   project has never skipped shadow before going active for any prior
   mechanism (Policy V2, promotion/quarantine controller, etc.) -- no
   reason to start now.

## Safety boundary maintained throughout today

No runtime integration, no EP scheduling, no live episode launched, no
modification of `navila-route2-v11-core-20260801` or the NaVILA conda
environment. The GPU-heavy work done today (training, offline evaluation)
ran in the isolated `/home/teambruce/anchor-v3-20260808/.conda-env`,
alongside but never interfering with concurrently-running NaVILA evaluator
processes (verified via `tools/monitor_training_gpu.sh`, zero unexpected
crashes across the final two training runs).
