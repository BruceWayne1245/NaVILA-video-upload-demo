#!/usr/bin/env bash
set -u

# 2026-07-21 single-episode smoke for the reliability A/B fix-ON arm, BEFORE the
# ~70h full 200-episode run. ep680 is the fix-ON target (Injection C's vetoed-
# correct-stop class). Confirms the merged A/B/C code runs in real Isaac without
# crashing / perturbing timing, and that the new flags are accepted. Same config
# as run_reliability_ab_100ep_20260721.sh ARM 2, restricted to ONLY_EPISODES=680.

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

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
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"
COMMON_EXTRA+=" --sequential_pair_closure_check"
COMMON_EXTRA+=" --sequential_pair_closure_reconciliation_signal=bearing"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor_suppress_if_stale"
COMMON_EXTRA+=" --stop_gate_anchor_corroboration --stop_gate_forced_anchor_confirm_steps=2"
COMMON_EXTRA+=" --sequential_pair_anchor_geometry_source=accumulated"
COMMON_EXTRA+=" --capture_icp_replay_dataset"

FIX_ARGS="--sequential_pair_reliability_quarantine"
FIX_ARGS+=" --reliability_quarantine_threshold=2.5"
FIX_ARGS+=" --sequential_pair_reliability_demote_current"
FIX_ARGS+=" --sequential_pair_reliability_distrust_downstream"

echo "[smoke] start $(date -Is)"
echo "[smoke] EXTRA_ISAAC_ARGS = ${COMMON_EXTRA} ${FIX_ARGS}"

RUN_TAG=reliability_ab_smoke_1ep_20260721_accumulated \
PORT_BASE=56321 \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
ONLY_EPISODES="680" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA} ${FIX_ARGS}" \
bash scripts/run_oracle_anchor_100ep_batch_20260720.sh

echo "[smoke] finished $(date -Is)"
