#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/short_baseline_hard11_20260712_master.log"

cd "${BENCH}" || exit 99

# Identical config to promotion_use_raw_estimates_hard11_20260710_accumulated /
# step4_scan_context_hard11_20260712_accumulated (the current best-validated
# live batch), plus only --sequential_pair_short_baseline_disambiguation (step
# 5: cross-checks every next-candidate's ICP reading against a second reading
# of the same candidate taken after >=0.3m of real robot motion, NOT gated on
# match_class -- see route_memory_agent.py's _check_short_baseline_yaw_disambiguation
# and round_trip_eval.py's --sequential_pair_short_baseline_disambiguation help
# text for the full rationale). Directly comparable against those existing
# batches as baseline (byte-identical bearing/anchor-selection behavior except
# for anchor_heading_reliable, since this mechanism only ever downgrades a
# reported hint's heading trust, never changes dx/dy/promotion timing).
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

# The one new flag this batch adds.
COMMON_EXTRA+=" --sequential_pair_short_baseline_disambiguation"
COMMON_EXTRA+=" --sequential_pair_short_baseline_min_travel_m=0.3"
COMMON_EXTRA+=" --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"

{
  echo "[master] started $(date -Is)"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] code state: relocalization.py/route_memory_agent.py include steps 1,2,4,5 (yaw_curve, yaw_observability, scan_context_yaw_check, short_baseline_disambiguation)"
  echo "[master] baseline for comparison: promotion_use_raw_estimates_hard11_20260710_accumulated / step4_scan_context_hard11_20260712_accumulated (identical config, no step 5)"

  RUN_TAG=short_baseline_hard11_20260712_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=oracle \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] accumulated finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
