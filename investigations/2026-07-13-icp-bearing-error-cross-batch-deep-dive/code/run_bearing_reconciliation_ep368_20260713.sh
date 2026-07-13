#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/bearing_reconciliation_ep368_20260713_master.log"

cd "${BENCH}" || exit 99

# Variant 2 (2026-07-13, user-requested): fusion/temporal-smoothing kept ON
# (closure_check + trust_aware_guard + temporal smoothing all active, same as
# the loftr_rear_yaw_check_20260713 pilot baseline) but the reconciliation
# SIGNAL switches from dtheta to bearing
# (--sequential_pair_closure_reconciliation_signal=bearing): disagreement/trust
# is judged by bearing (direction-to-anchor) instead of rotation, and dtheta is
# never blended via circular_weighted_mean in either mechanism -- it is simply
# carried through unchanged from whichever side is dominant/freshest. Plus
# --sequential_pair_loftr_rear_yaw_check for the same RGB cross-check.
# Otherwise identical to the loftr_rear_yaw_check_20260713 pilot's config.
COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter"
COMMON_EXTRA+=" --sequential_pair_closure_check --sequential_pair_closure_mode=belief"
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

COMMON_EXTRA+=" --sequential_pair_closure_belief_trust_aware_guard"
COMMON_EXTRA+=" --sequential_pair_closure_belief_large_position_disagreement_m=1.5"
COMMON_EXTRA+=" --sequential_pair_closure_belief_large_heading_disagreement_deg=90.0"

COMMON_EXTRA+=" --sequential_pair_promotion_use_pre_closure_estimates"

COMMON_EXTRA+=" --sequential_pair_short_baseline_disambiguation"
COMMON_EXTRA+=" --sequential_pair_short_baseline_min_travel_m=0.3"
COMMON_EXTRA+=" --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"

COMMON_EXTRA+=" --sequential_pair_loftr_rear_yaw_check"

# The one flag this run adds.
COMMON_EXTRA+=" --sequential_pair_closure_reconciliation_signal=bearing"

{
  echo "[master] started $(date -Is)"
  echo "[master] VARIANT 2: fusion reconciliation signal switched from dtheta to bearing"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] pilot episode: 368 only (ONLY_EPISODES=368)"

  RUN_TAG=bearing_reconciliation_ep368_20260713_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=oracle \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  ONLY_EPISODES="368" \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] ep368 (bearing reconciliation) finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
