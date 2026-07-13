#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/no_fusion_loftr_bearing_ep368_20260713_master.log"

cd "${BENCH}" || exit 99

# Variant 1 (main version, per user's decision) re-run with the extended
# _loftr_rear_yaw_check that now also reports LoFTR-rear's own translation
# (loftr_rear_dx_m/dy_m/bearing_to_anchor_deg), not just rotation -- lets us
# check whether LoFTR-rear's own BEARING is also more accurate than ICP's,
# now that fusion-corruption is out of the picture (Variant 1: no
# --sequential_pair_closure_check, --sequential_pair_disable_temporal_smoothing).
COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter"
COMMON_EXTRA+=" --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend"

COMMON_EXTRA+=" --route_local_map_icp_objective=point_to_point"
COMMON_EXTRA+=" --route_local_map_voxel_size_m=0.10"
COMMON_EXTRA+=" --route_local_map_max_points=512"
COMMON_EXTRA+=" --route_local_map_profile=default"
COMMON_EXTRA+=" --route_local_map_quality_policy=diagnostic"

COMMON_EXTRA+=" --sequential_pair_promotion_mode=bounded_evidence"
COMMON_EXTRA+=" --sequential_pair_promotion_window=5"
COMMON_EXTRA+=" --sequential_pair_promotion_min_votes=3"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_aware"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_threshold=0.6"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_window=8"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_min_votes=5"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_stall_attempts=200"

COMMON_EXTRA+=" --sequential_pair_promotion_use_pre_closure_estimates"

COMMON_EXTRA+=" --sequential_pair_short_baseline_disambiguation"
COMMON_EXTRA+=" --sequential_pair_short_baseline_min_travel_m=0.3"
COMMON_EXTRA+=" --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"

COMMON_EXTRA+=" --sequential_pair_loftr_rear_yaw_check"
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"

{
  echo "[master] started $(date -Is)"
  echo "[master] VARIANT 1 (main version) + extended LoFTR-rear translation check"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] pilot episode: 368 only (ONLY_EPISODES=368)"

  RUN_TAG=no_fusion_loftr_bearing_ep368_20260713_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=oracle \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  ONLY_EPISODES="368" \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] ep368 finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
