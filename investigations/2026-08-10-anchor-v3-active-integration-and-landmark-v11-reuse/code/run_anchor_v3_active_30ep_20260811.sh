#!/usr/bin/env bash
set -euo pipefail

# First 30-episode prospective batch for --anchor_v3_active (2026-08-11),
# replacing Anchor V2's full-active controller with Anchor V3's own decision
# as the sole promotion/hold/recovery authority. Also exercises the
# anchor0-landmark shadow mechanism (multiframe merge, real-V1.1-artifact
# reuse, 2.5-3.0m trigger band, 5-step outbound check interval) alongside it,
# entirely in shadow -- it never influences any real decision.
#
# Episode cohort: first 30 of the same 49-episode locked-order manifest used
# by anchor_v2_full_active_batch49_20260802, so results are directly
# comparable to that prior Anchor V2 run on identical episodes/scenes.

ROOT="/home/teambruce/navila-route2-v11-core-20260801"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
DRIVER="${ROOT}/launch/run_manifest_batch_driver.sh"
EVALUATOR="${ROOT}/runtime_candidate/scripts/round_trip_eval.py"
VALIDATOR="${ROOT}/validation/validate_v11_core_episode.py"
V11_ARTIFACT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/artifacts/reliability_v1_1_portable_shadow.json"
CORE_POLICY="${ROOT}/config/v11_consumer_policy_v3_core_active.json"
MANIFEST="${ROOT}/manifest/route2_anchorv2_terminal50.tsv"
RUN_TAG="anchor_v3_active_30ep_20260811"
LOG_ROOT="${BENCH}/batch_logs/${RUN_TAG}"
KILL_SWITCH="/tmp/navila-anchor-v3-active-30ep.kill"
DRIVER_LOCK="/tmp/navila-unified-shadow50-driver.lock"
PORT_BASE=56000

# First 30 of batch49's own locked-order 49-episode list (see
# run_anchor_v2_full_active_batch49_after_resume11.sh) -- same cohort, first
# 30, so this is directly comparable to that Anchor V2 run.
ONLY_EPISODES="87 88 134 310 678 4 187 994 680 579 539 367 5 89 351 264 95 962 1040 647 276 658 484 581 961 1038 646 764 268 844"

log() { echo "[$(date -Is)] $*" | tee -a "${LOG_ROOT}/orchestrator.log"; }

resources_busy() {
  local pid cmd
  for pid in $(ps -e -o pid=); do
    [[ -r "/proc/${pid}/cmdline" ]] || continue
    cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
    [[ "${cmd}" == *"bash -c"* || "${cmd}" == *"pgrep"* || "${cmd}" == *"rg "* ]] && continue
    [[ "${cmd}" == *"round_trip_eval.py"* || "${cmd}" == *"vlm_server.py"* ]] && return 0
  done
  return 1
}

static_preflight() {
  mkdir -p "${LOG_ROOT}"
  [[ -f "${VALIDATOR}" && -f "${MANIFEST}" && -f "${CORE_POLICY}" && -f "${V11_ARTIFACT}" ]] || {
    log "FATAL validator, manifest, core policy, or V1.1 artifact missing"; return 1;
  }
  bash -n "${DRIVER}"
  /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python -m py_compile "${EVALUATOR}" "${VALIDATOR}"
  [[ ! -e "${KILL_SWITCH}" ]] || { log "FATAL kill switch already present: ${KILL_SWITCH}"; return 1; }
  if resources_busy; then
    log "FATAL another evaluator/VLM process is already running"; return 1;
  fi
  log "static preflight PASS"
}

run_batch() {
  rm -f "${KILL_SWITCH}"
  local extra="--route_relocalization_interval_updates=5"
  extra+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
  extra+=" --stop_gate_accept_confirm_steps=2 --stop_gate_verify_queries=2"
  extra+=" --stop_gate_blind_max_queries=8 --stop_gate_pre_stop_blind_trigger_queries=4"
  extra+=" --stop_gate_max_evidence_age_updates=25 --stop_gate_visual_confirm_steps=2"
  extra+=" --stop_gate_home_visual_max_distance_m=1.5 --stop_gate_home_visual_min_confidence=0.45"
  extra+=" --terminal_a0_probe_all_return_queries_shadow"
  extra+=" --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90"
  extra+=" --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10"
  extra+=" --route_local_map_max_points=512 --route_local_map_profile=default --route_local_map_quality_policy=diagnostic"
  extra+=" --sequential_pair_promotion_mode=bounded_evidence --sequential_pair_promotion_window=5"
  extra+=" --sequential_pair_promotion_min_votes=3 --sequential_pair_promotion_alias_aware"
  extra+=" --sequential_pair_promotion_alias_threshold=0.6 --sequential_pair_promotion_alias_window=8"
  extra+=" --sequential_pair_promotion_alias_min_votes=5 --sequential_pair_promotion_alias_stall_attempts=200"
  extra+=" --sequential_pair_promotion_use_pre_closure_estimates --sequential_pair_short_baseline_disambiguation"
  extra+=" --sequential_pair_short_baseline_min_travel_m=0.3 --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"
  extra+=" --sequential_pair_disable_temporal_smoothing --sequential_pair_closure_check"
  extra+=" --sequential_pair_closure_reconciliation_signal=bearing --sequential_pair_report_next_anchor"
  extra+=" --sequential_pair_report_next_anchor_suppress_if_stale --sequential_pair_anchor_geometry_source=accumulated"
  extra+=" --capture_icp_replay_dataset --route_memory_capture_start_anchor_descriptor"
  extra+=" --sequential_pair_reconstructed_confidence_source_one_hop"
  extra+=" --reliability_v11_online --reliability_v11_runtime_root=${ROOT}"
  extra+=" --reliability_v11_portable_artifact=${V11_ARTIFACT}"
  extra+=" --reliability_v11_core_policy=${CORE_POLICY} --reliability_v11_core_mode=active"
  extra+=" --reliability_v11_derived_evidence_mode=active"
  extra+=" --reliability_v11_integrated_promotion_mode=off --reliability_v11_integrated_anchor_state_mode=off"
  extra+=" --reliability_v11_integrated_candidate_selector_mode=off --reliability_v11_integrated_candidate_controller_mode=off"
  extra+=" --reliability_v11_active_scan_plan_mode=off --reliability_v11_anchor_support_recovery_mode=off"
  extra+=" --anchor_transition_guard_mode=off"
  extra+=" --anchor_v3_shadow --anchor_v3_active --anchor_v3_active_armed"
  extra+=" --anchor_transition_guard_kill_switch_path=${KILL_SWITCH}"
  extra+=" --anchor0_landmark_shadow --route_memory_multiframe_anchor_symmetric_enabled"
  extra+=" --low_level_policy_log_root=${BENCH}/logs/rsl_rl"

  env LOCK_FILE="${DRIVER_LOCK}" RUN_TAG="${RUN_TAG}" PORT_BASE="${PORT_BASE}" \
    ONLY_EPISODES="${ONLY_EPISODES}" MANIFEST="${MANIFEST}" EVAL_SCRIPT="${EVALUATOR}" \
    EPISODE_VALIDATOR="${VALIDATOR}" FAIL_FAST=0 REQUIRE_ALL_EPISODES=1 \
    EPISODE_TIMEOUT_SECONDS=3600 EPISODE_TIMEOUT_KILL_AFTER_SECONDS=300 \
    REQUIRE_GPU_CLEAN_BETWEEN_EPISODES=1 EPISODE_CLEANUP_WAIT_SECONDS=300 \
    GPU_FREE_MIN_MIB=22000 \
    ROUTE_HINT_SOURCE=integrated ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
    ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 EXTRA_ISAAC_ARGS="${extra}" \
    bash "${DRIVER}"
}

static_preflight
while true; do
  set +e
  run_batch
  rc=$?
  set -e
  if (( rc == 75 )); then
    log "driver lock is busy (exit 75); waiting 60s and retrying without overlapping batches"
    sleep 60
    continue
  fi
  (( rc == 0 )) || { log "anchor_v3_active_30ep exited rc=${rc}"; exit "${rc}"; }
  log "anchor_v3_active_30ep finished"
  break
done
