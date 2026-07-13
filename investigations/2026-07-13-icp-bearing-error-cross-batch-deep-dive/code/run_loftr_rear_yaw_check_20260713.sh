#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/loftr_rear_yaw_check_20260713_master.log"

cd "${BENCH}" || exit 99

# Identical config to short_baseline_hard11_20260712_accumulated (the current
# best-validated live batch), plus only the new --sequential_pair_loftr_rear_yaw_check
# diagnostic (2026-07-13, per user's proposal -- see relocalization.py's
# _loftr_rear_yaw_check docstring and investigations/2026-07-13-.../
# CORRELATIVE_VERIFIER_CHECK.md for the full rationale: RGB+LoFTR is a
# genuinely different sensing MODALITY from the LiDAR ICP/occupancy-grid
# checks already tried and found not to help). Diagnostic-only, off by
# default, does not change navigation/promotion behavior.
#
# Pilot: ep368 only (ONLY_EPISODES), the clearest genuinely-independent
# cross-run-reproducible hard anchor found in
# investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/FINDINGS.md
# section 7 (anchor12: 60.4deg mean error 2026-07-10, 134.9deg 2026-07-12 --
# real, not a duplicate-trajectory artifact like ep367's).
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

# The one new flag this run adds.
COMMON_EXTRA+=" --sequential_pair_loftr_rear_yaw_check"

{
  echo "[master] started $(date -Is)"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] code state: relocalization.py/route_memory_agent.py include steps 1,2,4,5 plus the new loftr_rear_yaw_check diagnostic (2026-07-13)"
  echo "[master] pilot episode: 368 only (ONLY_EPISODES=368)"

  RUN_TAG=loftr_rear_yaw_check_20260713_ep368_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=oracle \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  ONLY_EPISODES="368" \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] ep368 pilot finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
