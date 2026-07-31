#!/usr/bin/env bash
set -u
# 2026-07-31 -- FIRST live-enforcement (Phase 3, promote/wait ONLY -- quarantine
# stays shadow-only) run of the promotion controller model. Also serves as the
# smoke test for --sequential_pair_promotion_model_active_promote itself: that
# flag, and the round_trip_eval.py/route_memory_agent.py/
# promotion_controller_runtime.py changes underneath it, were only unit-tested
# offline today (synthetic records, no live Isaac Sim episode) because the GPU
# was occupied by unified_shadow50_retry4 the whole time -- see
# wait_for_unified50_then_run_active_promote_30ep_20260731.sh, which queues
# this behind that job.
#
# Same 30 episode_idx values as promotion_shadow_reliable30v3_20260731
# (deliberately -- lets active-promote be compared directly against that
# batch's shadow-only baseline on identical episodes, same scenes/neighbors,
# only the promote decision mechanism differs). See
# investigations/2026-07-28-promotion-quarantine-controller-model/ and this
# repo's 2026-07-31 reliable30v3 dwell-based re-validation for why promote/wait
# (not quarantine) were judged ready: precision/recall/AUC replicated almost
# exactly across two independent live batches.
#
# quarantine_threshold raised 0.65->0.85 from the 2026-07-31 combined-batch
# (0728+reliable30v3, 13086 rows) threshold sweep -- F1-optimal point
# (precision 0.297->0.560, recall 0.737->0.549). Only affects when the
# model's quarantine call suppresses an active promote (mapped to "wait") and
# what gets logged to promotion_controller_shadow.jsonl -- never touches
# _quarantined_anchor_indices, which stays exclusively heuristic-driven.
#
# Config otherwise identical to promotion_shadow_reliable30v3_20260731 (same
# canonical downgrade-arm flags) -- only the model flags and RUN_TAG/PORT_BASE
# differ.

DRIVER="/home/teambruce/run_promotion_shadow_reliable30v3_driver_20260731.sh"

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
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current"
COMMON_EXTRA+=" --sequential_pair_reliability_distrust_downstream"
COMMON_EXTRA+=" --reliability_quarantine_shared_trend_budget"
COMMON_EXTRA+=" --stuck_recovery"
COMMON_EXTRA+=" --sequential_pair_loftr_rear_yaw_check"
COMMON_EXTRA+=" --sequential_pair_vision_disagreement_mode=downgrade --sequential_pair_vision_disagreement_confidence_penalty=0.3"
COMMON_EXTRA+=" --sequential_pair_promotion_model_shadow=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/models/promotion_controller_v2_2026-07-28_isaacenv.pkl"
COMMON_EXTRA+=" --sequential_pair_promotion_model_quarantine_threshold=0.85"
COMMON_EXTRA+=" --sequential_pair_promotion_model_active_promote"

RUN_TAG="promotion_active_promote_30ep_20260731" \
PORT_BASE=65000 \
ONLY_EPISODES="4 5 89 134 187 205 268 295 354 367 368 381 408 409 420 430 488 498 500 647 671 678 680 688 708 974 994 1038 1040 1058" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
bash "${DRIVER}"
