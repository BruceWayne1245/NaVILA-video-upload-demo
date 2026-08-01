#!/usr/bin/env bash
set -u
# 2026-08-01 -- follow-up to promotion_active_promote_30ep_20260731. Two code
# changes underneath this run, both in route_memory_agent.py/round_trip_eval.py
# (NaVILA-Bench/scripts, the live-imported copies, verified edited directly):
#
# 1. anchor0 (the true route start) used to be created with descriptor=None
#    in RouteMemoryAgent.__init__ (before the env produces a single sensor
#    frame) -- permanently unmatchable via ICP. investigations/2026-08-01-.../
#    FINDINGS.md found this caused ep498's total relocalization starvation:
#    3 real heuristic trend-quarantines in a row (anchor3, anchor2, anchor1)
#    exhausted every other candidate down to anchor0, which then produced
#    zero candidates for the rest of the episode. Fixed: update_outbound_motion
#    now backfills anchor0's descriptor with the first real one the episode
#    ever produces (identity/pose/distance untouched).
#
# 2. New --sequential_pair_promotion_model_quarantine_veto (off by default,
#    on here). The model does NOT get authority to INITIATE a quarantine
#    (its own quarantine-class precision measured only 0.246-0.327 offline --
#    investigations/2026-07-31-.../FINDINGS.md section 3 -- too weak to trust
#    with an irreversible-within-episode blacklist on its own initiative).
#    It only vetoes an existing heuristic quarantine mechanism
#    (_record_next_anchor_trend/_quality/_reliability/_stability) when the
#    model's own contemporaneous classification is NOT 'quarantine' -- an
#    additional AND-gate that can only lower quarantine's false-positive
#    rate, never raise it. In ep498, the model's classification was 'wait'
#    on all 3 of the real quarantines that led to starvation -- this flag
#    would have blocked all 3.
#
# Same 30 episode_idx values as promotion_active_promote_30ep_20260731 /
# promotion_shadow_reliable30v3_20260731 (deliberately -- three-way comparison
# on identical episodes/scenes/neighbors, isolating these two fixes as the
# only variable). PORT_BASE fixed from 65000 (overflowed to invalid TCP ports
# >65535 for episode_idx>535 last time, silently losing 11/30 episodes,
# including 4 of reliable30v3's known successes -- ep647/671/688/1040) back
# down to 63000, matching reliable30v3's own already-proven-safe value.

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
COMMON_EXTRA+=" --sequential_pair_promotion_model_quarantine_veto"

RUN_TAG="promotion_quarantine_veto_30ep_20260801" \
PORT_BASE=63000 \
ONLY_EPISODES="4 5 89 134 187 205 268 295 354 367 368 381 408 409 420 430 488 498 500 647 671 678 680 688 708 974 994 1038 1040 1058" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
bash "${DRIVER}"
