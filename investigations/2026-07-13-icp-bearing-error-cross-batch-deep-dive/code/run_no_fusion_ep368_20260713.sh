#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/no_fusion_ep368_20260713_master.log"

cd "${BENCH}" || exit 99

# Variant 1 (2026-07-13, user-requested): completely remove fusion.
# --sequential_pair_closure_check is OMITTED (closure-check/belief-fusion/
# trust_aware_guard never runs) AND --sequential_pair_disable_temporal_smoothing
# skips _temporally_smooth_relocalization too -- every accepted attempt reports
# its raw selected (dx,dy,dtheta), completely unmodified. Plus
# --sequential_pair_loftr_rear_yaw_check for the same RGB cross-check as the
# loftr_rear_yaw_check_20260713 pilot. Otherwise identical to that pilot's config.
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

# The two flags this run adds -- NOTE: --sequential_pair_closure_check is
# deliberately NOT passed (closure-check/belief-fusion/trust_aware_guard off).
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"

{
  echo "[master] started $(date -Is)"
  echo "[master] VARIANT 1: no fusion at all (closure_check omitted + temporal smoothing disabled)"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] pilot episode: 368 only (ONLY_EPISODES=368)"

  RUN_TAG=no_fusion_ep368_20260713_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=oracle \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  ONLY_EPISODES="368" \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] ep368 (no fusion) finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
