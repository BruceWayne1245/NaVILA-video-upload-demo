#!/usr/bin/env bash
set -u

# =====================================================================================
# 2026-07-26 -- master for the Route1 vision_disagreement_mode A/B (diagnostic baseline
# vs downgrade) on the same 50-episode "outbound most likely to succeed" set Route2
# selected 2026-07-25. Waits for the currently-running Route2 5ep canary
# (stage32_active_5ep, PID recorded below) to finish before starting, since both share
# the same single GPU / VLM port. Two full 50-episode phases, back-to-back, same driver.
#
# Launch (detached, survives disconnect -- see below for the actual systemd-run
# invocation used):
#   systemd-run --user --unit=navila-vision-disagreement-ab-50ep-20260726 \
#     --description="Route1 vision_disagreement_mode A/B, 50ep, waits for stage32_active_5ep" \
#     bash /home/teambruce/run_vision_disagreement_ab_50ep_master_20260726.sh
# =====================================================================================

DRIVER="/home/teambruce/run_vision_disagreement_ab_50ep_driver_20260726.sh"
MASTER_LOG="/home/teambruce/run_vision_disagreement_ab_50ep_master_20260726.log"
# Process-name based, not PID-based: PID 1785553 (the run_batch.sh wrapper) never
# carries the "stage32_active_5ep" string in its OWN cmdline (only its Isaac child's
# --result_suffix does) -- an earlier version of this check keyed on that PID's cmdline
# directly and wrongly concluded the job had already finished on its first poll. Keying
# on the actual GPU-consuming process names is robust to PID reuse and doesn't depend on
# which shell layer happens to carry which substring.
WAIT_PATTERNS=(
  "policy_v2_live_candidate/scripts/round_trip_eval.py"
  "vlm_server.py.*--port 63005"
  "v2-integrated-promotion-shadow-canary/run_batch.sh"
  "run_stage32_active_5ep.sh"
)

log() {
  echo "[$(date -Is)] $*" | tee -a "${MASTER_LOG}"
}

any_wait_pattern_running() {
  local pat
  for pat in "${WAIT_PATTERNS[@]}"; do
    if pgrep -f "${pat}" > /dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

wait_for_current_5ep_job() {
  log "Waiting for Route2's currently-running 5ep job to finish (polling process names: ${WAIT_PATTERNS[*]})..."
  local ticks=0
  while true; do
    while any_wait_pattern_running; do
      if (( ticks % 20 == 0 )); then
        log "Still waiting (Route2 process(es) still running)... [$((ticks * 30 / 60)) min elapsed]"
      fi
      ticks=$((ticks + 1))
      sleep 30
    done
    log "No Route2 process matching any wait pattern detected. Confirming with a 60s settle window..."
    sleep 60
    if ! any_wait_pattern_running; then
      log "Confirmed clear after 60s settle. Proceeding."
      return 0
    fi
    log "Route2 process reappeared during the settle window (likely between episodes within the same batch) -- resuming wait."
  done
}

wait_for_current_5ep_job

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
# the 2026-07-21 fix (A+B+C) -- same as the best-documented 63%% (12/19) result,
# reliability_fixon_100ep_20260721_accumulated
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current"
COMMON_EXTRA+=" --sequential_pair_reliability_distrust_downstream"
COMMON_EXTRA+=" --reliability_quarantine_shared_trend_budget"
COMMON_EXTRA+=" --stuck_recovery"
# both arms pay the same LoFTR/GPU overhead -- only vision_disagreement_mode differs,
# so a difference in outcome can't be attributed to the extra compute itself.
COMMON_EXTRA+=" --sequential_pair_loftr_rear_yaw_check"

log "===== Route1 vision_disagreement_mode A/B (50ep) starting ====="

# 2026-07-26 reorder (B/A instead of A/B), per user request: run downgrade FIRST so the
# new mechanism's data is available by tomorrow morning without waiting on the baseline
# arm too. Same two phases, same flags, just swapped.
log "----- Phase 1/2: downgrade (vision_disagreement_mode=downgrade, penalty=0.3) -----"
RUN_TAG="vision_disagreement_ab_50ep_20260726_downgrade" \
PORT_BASE=59200 \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_vision_disagreement_mode=downgrade --sequential_pair_vision_disagreement_confidence_penalty=0.3" \
bash "${DRIVER}" 2>&1 | tee -a "${MASTER_LOG}"
log "----- Phase 1/2 (downgrade) finished -----"

log "----- Phase 2/2: diagnostic (baseline, no behavior change) -----"
RUN_TAG="vision_disagreement_ab_50ep_20260726_diagnostic" \
PORT_BASE=59000 \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_vision_disagreement_mode=diagnostic" \
bash "${DRIVER}" 2>&1 | tee -a "${MASTER_LOG}"
log "----- Phase 2/2 (diagnostic) finished -----"

log "===== Route1 vision_disagreement_mode A/B (50ep) FINISHED ====="
