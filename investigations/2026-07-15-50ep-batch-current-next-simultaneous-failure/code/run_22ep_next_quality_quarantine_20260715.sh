#!/usr/bin/env bash
set -u

echo "[master] started $(date -Is)"
echo "[master] Re-running the 22 outbound-success episodes from shadow_hint_swap_50ep_20260714_accumulated"
echo "[master] with the new opt-in --sequential_pair_quarantine_next_quality gate (2026-07-15) added on top"
echo "[master] of the identical Variant-1 config, to see whether it recovers any of the 8 known return-failures"
echo "[master] (134,367,994,319,708,498,354,214) without regressing any of the 14 known successes."

export RUN_TAG="shadow_next_quality_quarantine_22ep_20260715"
export ROUTE_HINT_SOURCE="integrated"
export ROUTE_RELOCALIZATION_BACKEND="sequential_pair"
export ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT="1"
export ONLY_EPISODES="4 5 134 187 367 368 408 994 1040 89 647 1038 430 500 295 268 488 319 708 498 354 214"
export EXTRA_ISAAC_ARGS="--route_relocalization_interval_updates=5 --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90 --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10 --route_local_map_max_points=512 --route_local_map_profile=default --route_local_map_quality_policy=diagnostic --sequential_pair_promotion_mode=bounded_evidence --sequential_pair_promotion_window=5 --sequential_pair_promotion_min_votes=3 --sequential_pair_promotion_alias_aware --sequential_pair_promotion_alias_threshold=0.6 --sequential_pair_promotion_alias_window=8 --sequential_pair_promotion_alias_min_votes=5 --sequential_pair_promotion_alias_stall_attempts=200 --sequential_pair_promotion_use_pre_closure_estimates --sequential_pair_short_baseline_disambiguation --sequential_pair_short_baseline_min_travel_m=0.3 --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0 --sequential_pair_disable_temporal_smoothing --sequential_pair_anchor_geometry_source=accumulated --sequential_pair_quarantine_next_quality --sequential_pair_quarantine_next_quality_threshold=0.75 --sequential_pair_quarantine_next_quality_min_samples=5"

bash /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_oracle_anchor_50ep_batch_20260714.sh

echo "[master] batch finished $(date -Is)"
