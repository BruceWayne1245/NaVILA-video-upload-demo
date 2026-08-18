# Code for `policy_v2_active50_replay_on_highsuccess100ep_20260816`

The complete code that produced the 100-episode run analyzed in
[`final_data/policy_v2_active50_replay_on_highsuccess100ep_20260816_README.md`](../../final_data/policy_v2_active50_replay_on_highsuccess100ep_20260816_README.md)
(`round_trip_success 42/91 ≈ 46.2%` overall; 55.1% on the first-50-by-execution-order
subset, see [`final_data2/README.md`](../README.md)).

This run has **two code sources**, both captured here exactly as they were at batch
launch (`2026-08-16T17:34:47+01:00`):

## `main_pipeline/` — the episode-execution harness

The actual round-trip navigation/relocalization pipeline that ran every episode. This
is a snapshot of `NaVILA-Bench/scripts/*.py` taken from the **live working tree**, not
a git commit — `round_trip_eval.py`, `route_memory_agent.py`, and `vlm_server.py` had
uncommitted local edits at the time (`git diff` vs the last commit showed ~7000 changed
lines across those three files) that were already in place and unmodified since before
the batch started (file mtimes Aug 14–16, all earlier than the 17:34 launch; no edits
since, confirmed 2026-08-18). Pulling from git HEAD would **not** reproduce this run;
this folder is the only faithful copy.

Files, and why each is included (traced via `round_trip_eval.py`'s local imports,
transitively):
- `round_trip_eval.py` — entry point / main eval loop
- `route_memory_agent.py` — route memory + sequential-pair relocalization core
- `relocalization.py` — relocalization backends (imports `scan_context.py`)
- `scan_context.py` — LiDAR scan-context descriptor, used by `relocalization.py`
- `stop_gate.py` — return stop-decision gate
- `hint_action_arbiter.py` — hint/action arbitration (imports `local_map.py`)
- `local_map.py` — local occupancy map / clear-path check, used by `hint_action_arbiter.py`
- `stuck_recovery.py` — stuck-state recovery controller
- `topdown_route_map.py` — top-down occupancy map capture/diagnostics
- `instruction_rewriter.py` — VLM instruction rewriting
- `cli_args.py` — CLI argument definitions (all `--route_*`/`--stop_gate*`/`--sequential_pair*`/etc. flags below)
- `vlm_server.py` — the separate 8-bit VLM server process each episode launches

## `reliability_v11_runtime/` — the Policy V2 / V1.1 reliability layer

Copied unmodified from the archived, byte-verified `--reliability_v11_runtime_root`
directory (`/home/teambruce/navila_archive/staging_dirs/navila-reliability-v1_1-policy-v2-active50-20260725/`,
no source file touched since 2026-07-25 — see project memory
`reference_policyv2_66pct_archived_code_20260816`), i.e. the same code that produced
Route2's historical-best 55.6%/66% result. This is what `--reliability_v11_online_shadow
--reliability_v11_consumer_mode=active` actually loads at runtime (traced via
`round_trip_eval.py`'s `sys.path` construction around `reliability_v11_runtime_root`):
- `reliability/` — the `reliability.v11_runtime` package (`V11DecisionShadowPolicy`,
  `V11ShadowJsonlSession`), plus its package-init dependencies (`bundle.py`, `policy.py`)
  and relative imports (`schema.py`, `v11_dataset.py`); the rest of the package is
  included for completeness even though not all modules are on this run's import path
- `reliability_v11_portable_runtime.py` — `PortableV11Bundle`, loaded from
  `<runtime_root>/candidate/scripts/` (self-contained, stdlib only)
- `artifacts/reliability_v1_1_portable_shadow.json` — the portable V1.1 bundle
  (`--reliability_v11_portable_artifact`)
- `configs/v11_decision_shadow_v1.json` — decision-shadow policy config
  (`--reliability_v11_decision_policy`)
- `configs/v11_consumer_policy_v2_active50_20260725.json` — Policy V2 consumer config
  (`--reliability_v11_consumer_policy_v2`)

Not included: `reliability_v1_1_development.pkl` / `reliability_v1.pkl` (model
checkpoints — not referenced by any code path reachable from the CLI flags used in
this run, confirmed via grep for `.pkl` in `reliability/`) and the archive's `data/`,
`experiments/`, `candidate/scripts/` Python modules (an older, unused copy — the actual
run only pulled `reliability_v11_portable_runtime.py` from that path), `upstream_snapshot/`,
`reports/` (unrelated to this specific run).

## Exact launch configuration

Full CLI flags as recorded in the batch's own log header
(`NaVILA-Bench/batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816/batch.log`):

```
Route hint config: --route_memory --route_hint_mode=compact --route_hint_source=integrated --route_relocalization_backend=sequential_pair
Return yaw alignment enabled: --oracle_align_return_yaw_to_anchor_segment
Extra Isaac args: --route_relocalization_interval_updates=5 --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90 --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10 --route_local_map_max_points=512 --route_local_map_profile=default --route_local_map_quality_policy=diagnostic --sequential_pair_promotion_mode=bounded_evidence --sequential_pair_promotion_window=5 --sequential_pair_promotion_min_votes=3 --sequential_pair_promotion_alias_aware --sequential_pair_promotion_alias_threshold=0.6 --sequential_pair_promotion_alias_window=8 --sequential_pair_promotion_alias_min_votes=5 --sequential_pair_promotion_alias_stall_attempts=200 --sequential_pair_promotion_use_pre_closure_estimates --sequential_pair_short_baseline_disambiguation --sequential_pair_short_baseline_min_travel_m=0.3 --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0 --sequential_pair_disable_temporal_smoothing --sequential_pair_closure_check --sequential_pair_closure_reconciliation_signal=bearing --sequential_pair_report_next_anchor --sequential_pair_report_next_anchor_suppress_if_stale --stop_gate_anchor_corroboration --stop_gate_forced_anchor_confirm_steps=2 --sequential_pair_anchor_geometry_source=accumulated --capture_icp_replay_dataset --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5 --sequential_pair_reliability_demote_current --sequential_pair_reliability_distrust_downstream --reliability_quarantine_shared_trend_budget --stuck_recovery --reliability_v11_online_shadow --reliability_v11_runtime_root=<archive_dir> --reliability_v11_portable_artifact=<archive_dir>/artifacts/reliability_v1_1_portable_shadow.json --reliability_v11_decision_shadow --reliability_v11_decision_policy=<archive_dir>/configs/v11_decision_shadow_v1.json --reliability_v11_consumer_policy_v2=<archive_dir>/configs/v11_consumer_policy_v2_active50_20260725.json --reliability_v11_consumer_mode=active --low_level_policy_log_root=<...>/logs/rsl_rl
```

(`<archive_dir>` = `reliability_v11_runtime/` in this folder, i.e.
`/home/teambruce/navila_archive/staging_dirs/navila-reliability-v1_1-policy-v2-active50-20260725/`
at run time.)

Route memory / round-trip harness invoked with `--round_trip_mode=phase_prompt` and the
`high_outbound_success_100ep_selection.tsv` manifest (see
`investigations/数据补全/code/high_outbound_success_100ep_selection.tsv` in this repo).
Each episode ran in its own fresh Isaac process against a fresh 8-bit `vlm_server.py`
instance; a 7200s timeout applied per episode.
