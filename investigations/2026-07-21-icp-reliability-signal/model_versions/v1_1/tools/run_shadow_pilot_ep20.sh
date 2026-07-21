#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/teambruce/navila-reliability-v1"
DRIVER="${ROOT}/candidate/scripts/run_reliability_shadow_pilot_20260721.sh"
ARTIFACT="${ROOT}/artifacts/reliability_v1_portable.json"

COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --max_return_seconds=20"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter"
COMMON_EXTRA+=" --hint_arbiter_min_relocalization_confidence=0.90"
COMMON_EXTRA+=" --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend"
COMMON_EXTRA+=" --route_local_map_icp_objective=point_to_point"
COMMON_EXTRA+=" --route_local_map_voxel_size_m=0.10 --route_local_map_max_points=512"
COMMON_EXTRA+=" --route_local_map_profile=default --route_local_map_quality_policy=diagnostic"
COMMON_EXTRA+=" --sequential_pair_promotion_mode=bounded_evidence"
COMMON_EXTRA+=" --sequential_pair_promotion_window=5 --sequential_pair_promotion_min_votes=3"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_aware --sequential_pair_promotion_alias_threshold=0.6"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_window=8 --sequential_pair_promotion_alias_min_votes=5"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_stall_attempts=200"
COMMON_EXTRA+=" --sequential_pair_promotion_use_pre_closure_estimates"
COMMON_EXTRA+=" --sequential_pair_short_baseline_disambiguation"
COMMON_EXTRA+=" --sequential_pair_short_baseline_min_travel_m=0.3"
COMMON_EXTRA+=" --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"
COMMON_EXTRA+=" --sequential_pair_closure_check --sequential_pair_closure_reconciliation_signal=bearing"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor --sequential_pair_report_next_anchor_suppress_if_stale"
COMMON_EXTRA+=" --stop_gate_anchor_corroboration --stop_gate_forced_anchor_confirm_steps=2"
COMMON_EXTRA+=" --sequential_pair_anchor_geometry_source=accumulated"
COMMON_EXTRA+=" --reliability_model_path=${ARTIFACT} --reliability_mode=shadow"
COMMON_EXTRA+=" --reliability_pose_high_risk_threshold=0.7 --reliability_high_risk_consecutive=10"
COMMON_EXTRA+=" --reliability_release_after_attempts=200"

RUN_TAG="reliability_v1_shadow_smoke_ep20_overlay_20260721" \
PORT_BASE=56000 \
ONLY_EPISODES=20 \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
RELIABILITY_ISOLATED_OVERLAY=1 \
bwrap \
  --bind / / \
  --dev-bind /dev /dev \
  --proc /proc \
  --ro-bind "${ROOT}/candidate/scripts" \
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts" \
  -- bash "${DRIVER}"
