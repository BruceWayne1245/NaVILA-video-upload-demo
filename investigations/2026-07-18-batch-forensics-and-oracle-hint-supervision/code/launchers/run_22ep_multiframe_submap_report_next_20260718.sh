#!/usr/bin/env bash
set -u

echo "[master] started $(date -Is)"
echo "[master] RESTART (2026-07-18) of shadow_multiframe_submap_22ep_20260716, killed at ep368 (~3h in) after"
echo "[master] discovering the injected hint has always reported 'current' (backward-looking, last-confirmed"
echo "[master] anchor) instead of 'next' (forward-looking, upcoming candidate) -- see"
echo "[master] investigations/2026-07-18-batch-forensics-and-oracle-hint-supervision/ and the same-day"
echo "[master] current-vs-next follow-up. User's explicit call: testing any mechanism on top of the old"
echo "[master] current-reporting hint has no analytical value, so this reruns from scratch with"
echo "[master] --sequential_pair_report_next_anchor added, rather than letting the old run finish."
echo "[master] Re-running the 22 outbound-success episodes from shadow_hint_swap_50ep_20260714_accumulated"
echo "[master] with the new opt-in real motion-integrated multi-frame submap (2026-07-16) -- symmetric"
echo "[master] backward+forward anchor-side accumulation AND a new return-side live frame buffer -- added on"
echo "[master] top of the identical Variant-1 config (current_confidence_ambiguity_gate, quarantine_next_quality,"
echo "[master] and sequential_pair_short_baseline_require_resolution all left OFF per the isolated"
echo "[master] single-variable-A/B convention -- report_next_anchor is the ONE new variable vs. the 07-14"
echo "[master] baseline stacked with multiframe_submap), to see whether it recovers any of the 8 known"
echo "[master] return-failures (134,367,994,319,708,498,354,214) without regressing any of the 14 known successes."

export RUN_TAG="shadow_multiframe_submap_report_next_22ep_20260718"
export ROUTE_HINT_SOURCE="integrated"
export ROUTE_RELOCALIZATION_BACKEND="sequential_pair"
export ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT="1"
export ONLY_EPISODES="4 5 134 187 367 368 408 994 1040 89 647 1038 430 500 295 268 488 319 708 498 354 214"
export EXTRA_ISAAC_ARGS="--route_relocalization_interval_updates=5 --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90 --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10 --route_local_map_max_points=512 --route_local_map_profile=default --route_local_map_quality_policy=diagnostic --sequential_pair_promotion_mode=bounded_evidence --sequential_pair_promotion_window=5 --sequential_pair_promotion_min_votes=3 --sequential_pair_promotion_alias_aware --sequential_pair_promotion_alias_threshold=0.6 --sequential_pair_promotion_alias_window=8 --sequential_pair_promotion_alias_min_votes=5 --sequential_pair_promotion_alias_stall_attempts=200 --sequential_pair_promotion_use_pre_closure_estimates --sequential_pair_disable_temporal_smoothing --sequential_pair_anchor_geometry_source=accumulated --route_memory_multiframe_anchor_symmetric_enabled --route_memory_multiframe_anchor_backward_distance_m=1.5 --route_memory_multiframe_anchor_forward_distance_m=1.5 --route_memory_multiframe_anchor_forward_stall_updates=300 --route_memory_return_frame_buffer_enabled --route_memory_return_frame_buffer_window_m=1.0 --route_memory_return_frame_buffer_max_frames=400 --sequential_pair_report_next_anchor"

bash /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_oracle_anchor_50ep_batch_20260714.sh

echo "[master] batch finished $(date -Is)"
