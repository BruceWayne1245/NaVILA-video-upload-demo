# 2026-07-22 — Code changes & run record

Operational companion to [`FINDINGS.md`](FINDINGS.md). Records exact flags, files, hashes,
tests, and the launched shadow batch.

## New default-off controller flags

| Flag | File | What it does |
|---|---|---|
| `--reliability_quarantine_shared_trend_budget` | `route_memory_agent.py` | Position-trend quarantine consumes the SAME `_reliability_quarantines_since_promotion` budget as Injection A, so A+trend together ≤ `reliability_quarantine_max_chain` (4) blacklists between promotions. Off ⇒ byte-identical. |
| `--stuck_recovery` (+ `--stuck_recovery_move_min_m=0.15`, `_n_queries=8`, `_belief_far_min_m=5.0`, `_escape_forward_m=0.8`, `_max_queries=16`, `_max_attempts=5`) | `stuck_recovery.py` (new) + `round_trip_eval.py` | Return-phase locomotion supervisor. Detects no-net-progress (net displacement < move_min for ≥ n_queries VLM queries while believed > belief_far from home and VLM not stopping); scripts back-out `reverse_turn → escape_forward → face_next`, with flip-turn-direction if the base can't rotate. Highest-priority action override (after hint_action_arbiter). Never touches relocalization/promotion/quarantine/stop. |

## Merged to live (`NaVILA-Bench/scripts`) 2026-07-22, locked hashes

```
round_trip_eval.py    7941f9a9611c11c16491ac18db9d2baffc5862c98157c6bfd7c204c304172866   (changed)
route_memory_agent.py 1e6af8cef24b2743ea68c9fc525a80ea85e7985a087f1f63309684f6b475fbf8   (changed)
relocalization.py     226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1   (unchanged)
stop_gate.py          0c37014abdc4bc4ad66bf23f167292c3b7ecc21c9a4f09c0d672888bb4f79d0b   (unchanged)
stuck_recovery.py     a23cfc6c18816eb8299b7b75eb7f0882455fb1f81c7c33a609c0ebfaabbb6b72   (new)
```

Pre-merge backup: `navila-gating-ab-v1/live_backup_premerge_20260722_stuckrecovery/`.
Isolation workspace / candidate: `navila-gating-ab-v1/candidate/`.

## Tests
- New unit tests: `test_reliability_gating.py::SharedTrendBudgetTest` (4), `test_stuck_recovery.py` (9, incl. `test_flips_direction_when_cannot_rotate`).
- Full suite against live: **309 pass, 14 pre-existing skips, 0 regressions** (`test_route_memory_agent` + `test_geometry_pipeline` + `test_stop_gate` + `test_reliability_gating` + `test_stuck_recovery`). `py_compile` clean.

## Offline go/no-go results (scripts ad hoc, CPU-only, read `eval_results`)
- Stuck detector: 0 FP on the 9 successes; fires on 5/491/653/994 at `n_queries≥6`, `move_min=0.15`, `belief_far>5.0`.
- Multi-view: AUC 0.737, leaky, inverts on symmetric-corridor anchors → **not built** (needs vision).

## Launched shadow batch
- Tag: `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`
- Runner: `/home/teambruce/navila-v11-shadow-batch/run_batch_template.sh` (rebased from `investigations/2026-07-22-v1_1-prospective-shadow-handoff`); `CONTROLLER_LABEL=claude_ABC_trendbudget_stuckrecovery_20260722`.
- Manifest SHA `60d2adf3…` (100 frozen fresh episodes, no overlap with prior 100); V1.1 artifact SHA `5f23aba4…` frozen, **offline capture-shadow only (no inference, no enforcement)**.
- Preflight PASS on all 6 code hashes + manifest + artifact.
- **Disconnect-safe:** `systemd-run --user --unit=v11_shadow_100ep_20260722`; cgroup verified under `user@1006.service/app.slice/…` (NOT session scope); Linger=yes. Manage: `XDG_RUNTIME_DIR=/run/user/1006 systemctl --user status|stop v11_shadow_100ep_20260722`.
- Logs: master `/home/teambruce/reliability_v11_shadow_100ep_20260722_master.log`; per-ep + provenance + capture under `NaVILA-Bench/batch_logs/reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated/`.

## Housekeeping done
- Killed the prior fix-ON phase-2 (low-value rest episodes) to free GPU.
- Reclassified fix-ON return rate = 12/20 (≈60%); analysis scripts ad hoc in scratch.
