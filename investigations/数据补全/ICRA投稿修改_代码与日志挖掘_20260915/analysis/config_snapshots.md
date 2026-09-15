# Actual matched-M50 configuration snapshots

Source of truth is each batch's `batch.log` plus the literal `Passing the following args to the base kit application` line in every `ep*_eval.log` under `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/<run>/`.

| name | run tag | actual feature flags (episode-specific ids/ports omitted) |
|---|---|---|
| L | `pure_baseline_highsuccess100ep_chronological_first50_20260818` | `--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only`; explicitly no route memory, hint, arbiter, stop gate or stuck recovery |
| OH | `pure_oracle_hint_highsuccess100ep_20260811` | `--route_memory --route_hint_mode=compact --route_hint_source=oracle --route_relocalization_backend=sequential_pair --oracle_align_return_yaw_to_anchor_segment` |
| OHA | `pure_oracle_hint_action_highsuccess100ep_20260812` | OH plus `--topdown_route_map --hint_action_arbiter` |
| FO | `pure_oracle_hint_action_stopgate_highsuccess100ep_20260813` | OHA plus `--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --stop_gate_anchor_corroboration --stop_gate_forced_anchor_confirm_steps=2` |
| ON | `policy_v2_active50_replay_on_highsuccess100ep_20260816` | Full literal string is preserved in `final_data2/policy_v2_active50_replay_on_highsuccess100ep_20260816_code/README.md`, lines 55–75. It includes integrated sequential-pair memory, arbiter confidence `0.90`, terminal verifier, Policy V2 active consumer, and `--stuck_recovery`. |
| GEO | `path_following_geometry_m50_20260910` | integrated sequential-pair memory with `--route_hint_mode=none --deterministic_path_following_return`, terminal verifier and Policy V2 active consumer; no `--stuck_recovery` |

All six literal invocations share `--task=go2_matterport_vision --num_envs=1 --history_length=9 --load_run=2024-09-25_23-22-02 --headless --enable_cameras --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only`. No invocation contains a seed flag. The additional OH/OHA/FO/ON/GEO controller flags are read only after the outbound-to-return transition except route-memory recording; route-memory records outbound anchors but does not modify outbound commands.

