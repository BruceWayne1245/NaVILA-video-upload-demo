#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/shadow_hint_swap_hard11_20260713_master.log"

cd "${BENCH}" || exit 99

# Step 5 of the Oracle->Shadow hint-source swap plan (2026-07-13): full
# hard-11 shadow-driven navigation batch, following the single-episode
# success on ep368 (STEP4_FIRST_LIVE_TEST.md). Same config as that run,
# --route_hint_source=integrated (real shadow/sequential_pair navigation,
# not the privileged oracle) + Variant 1 (no fusion) +
# hint_action_arbiter's confidence gate at the step-3-calibrated threshold
# (0.90). No ONLY_EPISODES restriction this time -- runs the full fixed
# hard-11 set (4,5,134,187,367,368,408,678,680,994,1040).
COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter"
COMMON_EXTRA+=" --hint_arbiter_min_relocalization_confidence=0.90"
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

# Variant 1: no fusion at all (closure_check omitted, temporal smoothing off).
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"

{
  echo "[master] started $(date -Is)"
  echo "[master] STEP 5: full hard-11 shadow-driven navigation batch (route_hint_source=integrated, default)"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] baseline for comparison: today's ep368 single-episode success (shadow_hint_swap_ep368_20260713_accumulated) and the various oracle-driven Variant-1 runs"

  RUN_TAG=shadow_hint_swap_hard11_20260713_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=integrated \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] hard11 finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
