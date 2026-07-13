# 2026-07-13 (continued 2) — Step 4: the first real Oracle→Shadow hint-source live test — SUCCESS

**This is the first time in this project's history that the shadow (non-oracle) relocalizer has actually driven live navigation**, rather than running in parallel purely for offline evaluation. Every prior batch since this route-memory system's inception used `--route_hint_source=oracle`; this run used the argparse default, `--route_hint_source=integrated`, which routes through `route_agent.progress()` — the real `sequential_pair` relocalization pipeline, now running Variant 1 (no fusion) plus the newly confidence-gated `hint_action_arbiter` (threshold 0.90, calibrated in `STEP3_CALIBRATION.md`).

## Config

Identical to the `no_fusion_ep368_20260713` Variant 1 run, minus `--sequential_pair_loftr_rear_yaw_check` (not needed for a real navigation test), plus:
- `ROUTE_HINT_SOURCE=integrated` (was `oracle` in every prior batch)
- `--hint_arbiter_min_relocalization_confidence=0.90` (new, calibrated in step 3)

## Result: round trip succeeded

| | value |
|---|---|
| `outbound_success` | True |
| `return_success` | True |
| `round_trip_success` | **True** |
| `distance_to_start` | 1.91m (success radius: 3.0m) |
| `success_requires_stop` | True (satisfied) |

For comparison, the same episode under oracle-driven navigation (today's other `ep368` runs, Variant 1 config) landed at 1.56-1.82m — slightly better, but this shadow-driven run is a clear, real success by the project's own success criteria, not a near-miss.

## `hint_action_arbiter` behavior — the new confidence gate engaged substantially, not just theoretically

| outcome | n | % of 2276 checks |
|---|---|---|
| `vlm_action_consistent` (no correction needed) | 1175 | 51.6% |
| **`low_relocalization_confidence` (new gate blocked an override)** | **375** | **16.5%** |
| `vlm_conflicts_with_clear_hint` → **override fired** | 300 | 13.2% |
| `occupied_in_local_map_path` (pre-existing clear-path check) | 201 | 8.8% |
| `target_too_close` (pre-existing distance gate) | 225 | 9.9% |

The new confidence gate fired on 16.5% of all checks — substantially more than the ~4.8% dropped-reading rate from step 3's per-attempt calibration, because the arbiter checks every step while the underlying relocalization estimate only updates every 5 steps (`--route_relocalization_interval_updates=5`), so a single low-confidence reading gets checked (and correctly blocked) repeatedly until the next update. This confirms the gate is doing real, substantial work in a live run, not a rarely-triggered theoretical safeguard — and the round trip still succeeded with 300 real corrections firing alongside it.

## Caveats — one success, one episode, not yet a validated default

- This is a single episode (`ep368`), the one the user chose specifically because Variant 1 was already validated well on it and it contains the hardest known anchor (anchor12) — a reasonable first test, not a representative sample.
- The confidence threshold (0.90) was calibrated on this same episode's own prior run's data (step 3) — some risk of being over-fit to `ep368` specifically; needs checking against other episodes before wider rollout.
- No failure mode was observed this run, so nothing is yet known about how gracefully this configuration handles a genuinely bad shadow reading in a live setting (only offline ground-truth-checked data has been examined so far).

## Next steps

Per the agreed plan's step 5: decide scope for a wider batch based on this result. Given a clean first success, a natural next step is testing on 2-3 more episodes (mixing an "easy" one where ICP was already accurate and one with different known characteristics) before committing to a full hard-11 shadow-driven batch.

## Reproducibility

Launcher: `code/run_shadow_hint_swap_ep368_20260713.sh` in this folder.
