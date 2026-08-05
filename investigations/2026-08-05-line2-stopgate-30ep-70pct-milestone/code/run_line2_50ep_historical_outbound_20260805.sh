#!/usr/bin/env bash
set -u
# 2026-08-05 -- Route 1 50ep validation batch, same stop_gate/route_memory_agent
# config as line2_stopgate_redesign_30ep_20260804.sh (COMMON_EXTRA below is byte-
# identical to that script, cross-checked against the canonical published copy at
# investigations/2026-08-04-stopgate-redesign-and-line2-30ep-retrospective/code/
# on GitHub -- confirmed identical via diff), but with a NEW episode_idx set.
#
# Why a new episode set: line2_stopgate_redesign_30ep_20260804's own result (see
# investigations/2026-08-04.../FINDINGS.md and this session's 20260805 follow-up
# analysis) found that 8 of that batch's 13 non-round-trip episodes never reached
# the return phase at all -- they hit a per-scene outbound step cap. Cross-checking
# those against every historical batch_logs/*/summary.tsv in this project (185
# files, 279 distinct episode_idx, aggregated 20260805) confirmed several of
# reliable30v3's episodes have a LONG history of near-zero outbound success
# (e.g. ep381/409: 0% across 10 historical attempts each; ep974/1058: 0% across
# 6-8 attempts) -- i.e. reliable30v3 was never actually selected for outbound
# reliability. This batch's 50 episode_idx values are instead the top 50 by
# historical outbound_success rate (>=0.667, most at 0.85-1.00) among episodes
# with >=3 historical attempts, so the return-phase/stop_gate mechanisms actually
# get tested on episodes that reliably reach the return phase. Deliberately keeps
# ep367/368/671/1040 (this session's return-phase-failure deep-dive subjects,
# 91-100% historical outbound success) and ep678 (fix #2's motivating case, 67%
# historical outbound success) for continuity.
#
# Also picks up two 20260805 infra fixes made earlier this session:
#   - run_promotion_shadow_reliable30v3_driver_20260731.sh: retry loop around
#     the post-episode measurement glob (fixes the race that lost ep1038's real
#     success in the 08-04 batch)
#   - NaVILA-Bench/scripts/round_trip_eval.py: additive [LOOP_EXIT] /
#     [MEASUREMENT_WRITE_OK|FAILED] diagnostic logging around episode finalization

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

RUN_TAG="${RUN_TAG:-line2_50ep_historical_outbound_20260805}" \
PORT_BASE=66000 \
ONLY_EPISODES="${ONLY_EPISODES:-4 5 19 87 88 89 93 95 123 187 205 214 264 268 276 295 310 319 344 351 355 366 367 368 427 484 489 490 498 539 579 581 646 647 658 669 671 678 680 688 784 815 844 888 961 962 994 1008 1038 1040}" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
bash "${DRIVER}"
