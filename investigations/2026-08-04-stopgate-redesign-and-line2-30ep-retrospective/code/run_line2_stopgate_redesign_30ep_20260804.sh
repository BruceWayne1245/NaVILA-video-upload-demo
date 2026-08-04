#!/usr/bin/env bash
set -u
# 2026-08-04 -- Route 1 30ep validation batch for today's stop_gate/route_memory_agent
# redesign, following up on line2_phase01_30ep_20260803 (analyzed this session:
# 4/30 round-trip, 3 regressions/1 improvement vs promotion_shadow_reliable30v3_20260731
# on the 20 directly-comparable episodes -- root-cause dig found this was most likely
# ordinary run-to-run noise, NOT caused by any of 08-03's 3 new mechanisms; see
# investigations/2026-08-04-stopgate-redesign-and-line2-30ep-retrospective/FINDINGS.md
# for the full retrospective, the 07-22-through-08-03 stop_gate historical archaeology,
# and the design rationale for each of the 6 flags added below).
#
# Adapted directly from run_line2_phase01_30ep_20260803.sh's COMMON_EXTRA with SIX new
# flags added (all default OFF elsewhere, all explicitly enabled here per this
# session's explicit recommendation -- see FINDINGS.md section 6's flag table):
#   1. --stop_gate_corroboration_overrides_low_reliability   (Mechanism D fix)
#   2. --current_evict_mode=window (+window/min_votes)        (eviction redesign)
#   3. --sequential_pair_promotion_anomaly_gate (+thresholds)  (cheap anomaly gate)
#   4. --sequential_pair_stale_relocalization_distrust AND
#      --sequential_pair_relocalization_uncertainty_mode=growing (+consumer)
#                                                               (frozen-reading fix,
#                                                                both variants combined)
#   5. --stop_gate_blind_budget (+max_attempts)                (bounded blind-budget)
#   6. --stop_gate_require_cross_role_agreement (+max_disagreement) (cross-role check)
#
# Deliberately bundled together rather than single-variable A/B this run (see
# FINDINGS.md section 6 for the explicit reasoning and the acknowledged tradeoff);
# follow-up single-variable A/B runs are the natural next step if this batch's
# aggregate result is surprising in either direction.
#
# Same 30 episode_idx values and PORT_BASE=63000 as promotion_shadow_reliable30v3_20260731
# / line2_phase01_30ep_20260803, deliberately, so this run stays directly comparable to
# both without needing a fresh baseline arm.

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
# --- 2026-08-03 line-2 Phase 0.2 / 1.1 / 1.2 (carried forward unchanged) ---
COMMON_EXTRA+=" --sequential_pair_evict_unreliable_current --current_evict_stall_attempts=30"
COMMON_EXTRA+=" --sequential_pair_promotion_ambiguity_gate --sequential_pair_promotion_min_confidence=0.35"
COMMON_EXTRA+=" --hint_action_arbiter_stop_veto --hint_action_arbiter_stop_veto_min_confidence=0.5"
COMMON_EXTRA+=" --hint_action_arbiter_stop_veto_anchor_remaining_min_m=3.0"
# --- 2026-08-04 stop_gate redesign additions (all 6, see FINDINGS.md section 6) ---
COMMON_EXTRA+=" --stop_gate_corroboration_overrides_low_reliability"
COMMON_EXTRA+=" --current_evict_mode=window --current_evict_window=40 --current_evict_min_votes=30"
COMMON_EXTRA+=" --sequential_pair_promotion_anomaly_gate"
COMMON_EXTRA+=" --sequential_pair_promotion_anomaly_max_bearing_jump_deg=90"
COMMON_EXTRA+=" --sequential_pair_promotion_anomaly_max_collapse_m=1.5"
COMMON_EXTRA+=" --sequential_pair_stale_relocalization_distrust --stale_relocalization_max_attempts=30"
COMMON_EXTRA+=" --sequential_pair_relocalization_uncertainty_mode=growing --stale_uncertainty_base_floor_m=0.35"
COMMON_EXTRA+=" --stop_gate_use_uncertainty_interval"
COMMON_EXTRA+=" --stop_gate_blind_budget --stop_gate_blind_budget_max_attempts=8"
COMMON_EXTRA+=" --stop_gate_require_cross_role_agreement --stop_gate_cross_role_max_disagreement_m=1.5"

RUN_TAG="${RUN_TAG:-line2_stopgate_redesign_30ep_20260804}" \
PORT_BASE=63000 \
ONLY_EPISODES="${ONLY_EPISODES:-4 5 89 134 187 205 268 295 354 367 368 381 408 409 420 430 488 498 500 647 671 678 680 688 708 974 994 1038 1040 1058}" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
bash "${DRIVER}"
