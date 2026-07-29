#!/usr/bin/env bash
set -u
# 2026-07-28 -- scale-up shadow-mode run for --sequential_pair_promotion_model_shadow,
# following the clean 3ep smoke test (run_promotion_shadow_smoke_3ep_20260728.sh):
# zero exceptions, negligible latency, live promote-call precision 88.3%/100% on the
# two episodes checked against ground truth. 30 episodes selected from the original
# 50ep cohort (run_vision_disagreement_ab_50ep_driver_20260726.sh's manifest) by
# historical outbound_success rate == 1.00 across every available prior batch run
# (aggregated over 16+ batch_logs/*/summary.tsv), ranked by tightest avg
# outbound_stop_distance_to_goal -- maximizes episodes that actually reach the return
# phase and exercise the shadow logic, rather than being lost to outbound failure.
# Same COMMON_EXTRA canonical downgrade-arm config as the smoke test; only ONLY_EPISODES,
# RUN_TAG, and PORT_BASE differ.

DRIVER="/home/teambruce/run_vision_disagreement_ab_50ep_driver_20260726.sh"

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
COMMON_EXTRA+=" --sequential_pair_promotion_model_quarantine_threshold=0.65"

RUN_TAG="promotion_shadow_30ep_20260728" \
PORT_BASE=59600 \
ONLY_EPISODES="669 490 671 5 1062 427 688 581 368 310 351 888 962 658 785 815 264 268 205 961 1038 539 367 88 784 579 646 844 366 647" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
bash "${DRIVER}"
