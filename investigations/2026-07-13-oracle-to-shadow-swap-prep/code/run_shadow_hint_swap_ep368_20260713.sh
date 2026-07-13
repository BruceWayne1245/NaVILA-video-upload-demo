#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
MASTER_LOG="/home/teambruce/shadow_hint_swap_ep368_20260713_master.log"

cd "${BENCH}" || exit 99

# Step 4 of the Oracle->Shadow hint-source swap plan (2026-07-13): the FIRST
# real live test where the VLM's actual navigation is driven by the shadow
# (sequential_pair) relocalizer's own hint, not the privileged oracle.
# --route_hint_source is left at its argparse default ("integrated"), which
# already routes through route_agent.progress() -- the real, already-existing
# non-oracle pipeline every prior batch only ever ran in parallel as a
# diagnostic. Config: Variant 1 (no fusion -- --sequential_pair_closure_check
# omitted, --sequential_pair_disable_temporal_smoothing) + the newly
# calibrated --hint_arbiter_min_relocalization_confidence=0.90 (see
# STEP3_CALIBRATION.md: drops only the ~4.8% of readings with ~76deg mean
# ground-truth error, keeps the rest at ~4.8deg mean).
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
  echo "[master] STEP 4: first real shadow-driven navigation test (route_hint_source=integrated, default)"
  echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"
  echo "[master] pilot episode: 368 only (ONLY_EPISODES=368)"

  RUN_TAG=shadow_hint_swap_ep368_20260713_accumulated \
  PORT_BASE=54321 \
  ROUTE_HINT_SOURCE=integrated \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  ONLY_EPISODES="368" \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
  bash scripts/run_oracle_anchor_hard_fresh_batch_20260629.sh
  echo "[master] ep368 finished $(date -Is) exit=$?"

  echo "[master] all done $(date -Is)"
} >> "${MASTER_LOG}" 2>&1
