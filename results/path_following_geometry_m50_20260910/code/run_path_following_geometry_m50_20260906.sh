#!/usr/bin/env bash
set -u

ROOT="/mnt/SSD4T/teambruce/projects/navila-isaac"
BENCH="${ROOT}/NaVILA-Bench"
ISAACLAB="${ROOT}/IsaacLab/isaaclab.sh"
CONDA="/home/teambruce/miniconda3/bin/conda"
VLM_ENV="/mnt/SSD4T/teambruce/conda_envs/navila-vlm"
ISAAC_ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
MODEL_PATH="${ROOT}/checkpoints/navila-llama3-8b-8f"
PORT_BASE="${PORT_BASE:-54321}"
PORT="${PORT:-54321}"
RUN_TAG="${RUN_TAG:-path_following_geometry_m50_20260906}"
EVAL_SCRIPT="/home/teambruce/navila_path_following_geometry_m50_20260906/policy_v2_live_candidate/scripts/round_trip_eval.py"
RUNTIME_ROOT="/home/teambruce/navila_path_following_geometry_m50_20260906"
START_AT="${START_AT:-0}"
ONLY_EPISODES="${ONLY_EPISODES:-}"
EPISODE_TIMEOUT_SECONDS="${EPISODE_TIMEOUT_SECONDS:-7200}"
EPISODE_TIMEOUT_KILL_AFTER_SECONDS="${EPISODE_TIMEOUT_KILL_AFTER_SECONDS:-300}"
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"
SUMMARY="${LOG_DIR}/summary.tsv"

mkdir -p "${LOG_DIR}"

if [[ ! -f "${SUMMARY}" ]]; then
  cat > "${SUMMARY}" <<'EOF'
episode_idx	episode_id	scene	neighbor_idx	neighbor_episode_id	matched_waypoints	mean_distance	baseline_distance_to_start	vlm_port	start_time	end_time	exit_code	result_suffix	vlm_log	eval_log	measurement_file	outbound_success	return_success	round_trip_success	distance_to_start	outbound_stop_distance_to_goal	trajectory_record_count
EOF
fi

kill_process_group() {
  local pid="$1"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
    sleep 5
  fi
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill -9 -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
    sleep 2
  fi
}

port_is_listening() {
  ss -tln 2>/dev/null | grep -q ":${PORT} "
}

wait_for_port_open() {
  local deadline=$((SECONDS + 900))
  while (( SECONDS < deadline )); do
    if port_is_listening; then
      return 0
    fi
    if [[ -n "${VLM_PID:-}" ]] && ! kill -0 "${VLM_PID}" 2>/dev/null; then
      return 1
    fi
    sleep 2
  done
  return 1
}

wait_for_port_closed() {
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    if ! port_is_listening; then
      return 0
    fi
    sleep 2
  done
  return 1
}

stop_existing_vlm_server() {
  local pids
  pids="$(pgrep -f "scripts/vlm_server.py.*--port ${PORT}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping pre-existing vlm_server.py on port ${PORT}: ${pids}" | tee -a "${LOG_DIR}/batch.log"
    while read -r pid; do
      [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
    done <<< "${pids}"
    sleep 10
  fi
}

start_vlm_server() {
  local vlm_log="$1"
  stop_existing_vlm_server
  if port_is_listening; then
    echo "Port ${PORT} is still busy before VLM startup; refusing to reuse an existing server." | tee -a "${vlm_log}"
    return 1
  fi

  cd "${BENCH}" || return 99
  setsid "${CONDA}" run \
    --prefix "${VLM_ENV}" \
    python "${BENCH}/scripts/vlm_server.py" \
    --model_path "${MODEL_PATH}" \
    --port "${PORT}" \
    --load_8bit \
    >> "${vlm_log}" 2>&1 &
  VLM_PID="$!"

  if ! wait_for_port_open; then
    echo "Timed out waiting for VLM server on port ${PORT}" | tee -a "${vlm_log}"
    kill_process_group "${VLM_PID}"
    return 1
  fi
  echo "VLM server ready on port ${PORT}, pid=${VLM_PID}" | tee -a "${vlm_log}"
  return 0
}

extract_measurement_summary() {
  local suffix="$1"
  python3 - "${BENCH}" "${suffix}" <<'PY'
import glob
import json
import os
import sys

bench, suffix = sys.argv[1], sys.argv[2]
pattern = os.path.join(
    bench,
    "eval_results",
    f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{suffix}",
    "measurements",
    "*.json",
)
matches = sorted(glob.glob(pattern), key=os.path.getmtime)
if not matches:
    print("\t".join(["", "", "", "", "", "", ""]))
    raise SystemExit(0)

path = matches[-1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
rt = data.get("round_trip", {})
print("\t".join([
    path,
    str(rt.get("outbound_success", "")),
    str(rt.get("return_success", "")),
    str(rt.get("round_trip_success", "")),
    str(rt.get("distance_to_start", "")),
    str(rt.get("outbound_stop_distance_to_goal", "")),
    str(rt.get("trajectory_record_count", "")),
]))
PY
}

run_episode() {
  local ep_idx="$1"
  local ep_id="$2"
  local scene="$3"
  local neighbor_idx="$4"
  local neighbor_ep_id="$5"
  local matched="$6"
  local mean_distance="$7"
  local baseline_distance="$8"
  local suffix="${RUN_TAG}_ep${ep_idx}"
  local vlm_log="${LOG_DIR}/ep${ep_idx}_vlm.log"
  local eval_log="${LOG_DIR}/ep${ep_idx}_eval.log"
  local start_time
  local end_time
  local exit_code
  local eval_pid=""
  local parsed

  if (( ep_idx < START_AT )); then
    echo "Skipping episode ${ep_idx}; START_AT=${START_AT}" | tee -a "${LOG_DIR}/batch.log"
    return 0
  fi
  if [[ -n "${ONLY_EPISODES}" && " ${ONLY_EPISODES} " != *" ${ep_idx} "* ]]; then
    echo "Skipping episode ${ep_idx}; ONLY_EPISODES=${ONLY_EPISODES}" | tee -a "${LOG_DIR}/batch.log"
    return 0
  fi

  PORT="$((PORT_BASE + ep_idx))"
  VLM_PID=""
  start_time="$(date -Is)"
  echo "[$start_time] starting episode ${ep_idx} (${scene}), port=${PORT}, suffix=${suffix}" | tee -a "${LOG_DIR}/batch.log"

  if start_vlm_server "${vlm_log}"; then
    cd "${BENCH}" || exit_code=99
    if [[ -z "${exit_code:-}" ]]; then
      setsid timeout --kill-after="${EPISODE_TIMEOUT_KILL_AFTER_SECONDS}s" "${EPISODE_TIMEOUT_SECONDS}s" \
        env TERM=xterm OMNI_KIT_ACCEPT_EULA=YES "${CONDA}" run \
        --no-capture-output \
        --prefix "${ISAAC_ENV}" \
        "${ISAACLAB}" -p \
        "${EVAL_SCRIPT}" \
        --task=go2_matterport_vision \
        --num_envs=1 \
        --history_length=9 \
        --load_run=2024-09-25_23-22-02 \
        --headless \
        --enable_cameras \
        --round_trip_mode=phase_prompt \
        --instruction_rewriter_provider=cache_only \
        --vlm_port="${PORT}" \
        --episode_idx="${ep_idx}" \
        --result_suffix="${suffix}" \
        --route_memory \
        --route_hint_mode=none \
        --route_hint_source=integrated \
        --route_relocalization_backend=sequential_pair \
        --route_relocalization_interval_updates=5 \
        --oracle_align_return_yaw_to_anchor_segment \
        --deterministic_path_following_return \
        --path_following_lookahead_m=0.65 \
        --path_following_turn_enter_deg=28 \
        --path_following_turn_exit_deg=12 \
        --path_following_stop_distance_m=0.35 \
        --path_following_command_duration_s=0.5 \
        --stop_gate \
        --stop_gate_r_in=3.0 \
        --stop_gate_r_out=3.0 \
        --stop_gate_confirm_steps=3 \
        --stop_gate_min_confidence=0.5 \
        --stop_gate_anchor_corroboration \
        --stop_gate_forced_anchor_confirm_steps=2 \
        --topdown_route_map \
        --sequential_pair_quarantine \
        --sequential_pair_quarantine_mode=trend \
        --route_local_map_icp_objective=point_to_point \
        --route_local_map_voxel_size_m=0.10 \
        --route_local_map_max_points=512 \
        --route_local_map_profile=default \
        --route_local_map_quality_policy=diagnostic \
        --sequential_pair_promotion_mode=bounded_evidence \
        --sequential_pair_promotion_window=5 \
        --sequential_pair_promotion_min_votes=3 \
        --sequential_pair_promotion_alias_aware \
        --sequential_pair_promotion_alias_threshold=0.6 \
        --sequential_pair_promotion_alias_window=8 \
        --sequential_pair_promotion_alias_min_votes=5 \
        --sequential_pair_promotion_alias_stall_attempts=200 \
        --sequential_pair_promotion_use_pre_closure_estimates \
        --sequential_pair_short_baseline_disambiguation \
        --sequential_pair_short_baseline_min_travel_m=0.3 \
        --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0 \
        --sequential_pair_disable_temporal_smoothing \
        --sequential_pair_closure_check \
        --sequential_pair_closure_reconciliation_signal=bearing \
        --sequential_pair_report_next_anchor \
        --sequential_pair_report_next_anchor_suppress_if_stale \
        --sequential_pair_anchor_geometry_source=accumulated \
        --sequential_pair_reliability_quarantine \
        --reliability_quarantine_threshold=2.5 \
        --sequential_pair_reliability_demote_current \
        --sequential_pair_reliability_distrust_downstream \
        --reliability_quarantine_shared_trend_budget \
        --reliability_v11_online_shadow \
        --reliability_v11_runtime_root="${RUNTIME_ROOT}" \
        --reliability_v11_portable_artifact="${RUNTIME_ROOT}/artifacts/reliability_v1_1_portable_shadow.json" \
        --reliability_v11_decision_shadow \
        --reliability_v11_decision_policy="${RUNTIME_ROOT}/configs/v11_decision_shadow_v1.json" \
        --reliability_v11_consumer_policy_v2="${RUNTIME_ROOT}/configs/v11_consumer_policy_v2_active50_20260725.json" \
        --reliability_v11_consumer_mode=active \
        --low_level_policy_log_root="${BENCH}/logs/rsl_rl" \
        >> "${eval_log}" 2>&1 &
      eval_pid="$!"
      wait "${eval_pid}"
      exit_code="$?"
      kill_process_group "${eval_pid}"
      if [[ "${exit_code}" == "124" || "${exit_code}" == "137" ]]; then
        echo "Episode ${ep_idx} timed out after ${EPISODE_TIMEOUT_SECONDS}s; continuing to next episode." | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
      fi
    fi
  else
    exit_code=98
  fi

  kill_process_group "${eval_pid}"
  kill_process_group "${VLM_PID}"
  wait_for_port_closed || echo "Warning: port ${PORT} still appears busy after episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log"
  sleep 15

  end_time="$(date -Is)"
  parsed="$(extract_measurement_summary "${suffix}")"
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
    "${matched}" "${mean_distance}" "${baseline_distance}" "${PORT}" "${start_time}" \
    "${end_time}" "${exit_code}" "${suffix}" "${vlm_log}" "${eval_log}" "${parsed}" \
    >> "${SUMMARY}"
  echo "[$end_time] finished episode ${ep_idx}, exit_code=${exit_code}" | tee -a "${LOG_DIR}/batch.log"
  unset exit_code
}

main() {
  echo "Batch started at $(date -Is)" | tee "${LOG_DIR}/batch.log"
  echo "Each episode uses a fresh 8-bit VLM server and a fresh Isaac evaluation process." | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a unique VLM port: PORT_BASE(${PORT_BASE}) + episode_idx." | tee -a "${LOG_DIR}/batch.log"
  if [[ -n "${ONLY_EPISODES}" ]]; then
    echo "Running only episodes: ${ONLY_EPISODES}" | tee -a "${LOG_DIR}/batch.log"
  fi
  echo "Path-following geometry M50: outbound+confirm use NaVILA exactly as the online comparator; return actions use non-oracle accumulated breadcrumbs + sequential-pair ICP + deterministic controller. No return VLM query, route hint, hint/action arbiter, or stuck-recovery policy. The paper comparator's 3.0 m ReturnStopGate remains enabled." | tee -a "${LOG_DIR}/batch.log"
  echo "Evaluator copy: ${EVAL_SCRIPT}" | tee -a "${LOG_DIR}/batch.log"
  echo "Episode timeout: ${EPISODE_TIMEOUT_SECONDS}s (kill-after ${EPISODE_TIMEOUT_KILL_AFTER_SECONDS}s)" | tee -a "${LOG_DIR}/batch.log"

  # Exact 50 episodes, in the exact order, as the first 50 rows (by start_time) of
  # policy_v2_active50_replay_on_highsuccess100ep_20260816's summary.tsv -- copied
  # directly from that file so this batch is row-for-row comparable to the data
  # already pushed to final_data/ on GitHub.
  run_episode 806 1368 TbHJrupSAjP 966 1648 5 0.702683 8.977993
  run_episode 470 798 QUCTc6BB5sX 546 943 5 0.662972 10.232210
  run_episode 646 1118 x8F5xyUWy9e 354 583 4 0.475011 8.570651
  run_episode 889 1517 EU6Fwq7SyZv 276 442 4 1.213044 8.345141
  run_episode 517 899 zsNo4HB9uLZ 726 1240 4 0.684778 7.519623
  run_episode 95 141 2azQ1b91cZZ 579 1006 5 0.000000 13.368412
  run_episode 324 523 TbHJrupSAjP 615 1075 4 1.103096 10.936766
  run_episode 961 1643 TbHJrupSAjP 291 472 4 0.315807 6.949306
  run_episode 962 1644 TbHJrupSAjP 291 472 4 0.315807 6.949306
  run_episode 844 1439 zsNo4HB9uLZ 882 1501 5 0.000000 6.517529
  run_episode 555 958 2azQ1b91cZZ 177 262 5 0.151484 7.823619
  run_episode 669 1153 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 670 1154 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 367 602 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 579 1006 2azQ1b91cZZ 93 139 5 0.000000 13.760632
  run_episode 484 827 zsNo4HB9uLZ 810 1375 4 0.000000 7.025259
  run_episode 5 9 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 696 1189 2azQ1b91cZZ 120 166 5 0.333557 10.149185
  run_episode 88 128 EU6Fwq7SyZv 288 460 5 1.348777 2.292637
  run_episode 534 922 zsNo4HB9uLZ 840 1435 5 0.750029 4.674335
  run_episode 647 1119 x8F5xyUWy9e 354 583 4 0.475000 8.374983
  run_episode 89 129 EU6Fwq7SyZv 288 460 5 1.349000 2.292637
  run_episode 268 422 QUCTc6BB5sX 435 739 6 0.000000 8.807060
  run_episode 1038 1759 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 205 314 2azQ1b91cZZ 807 1372 0 0.000000 0.000000
  run_episode 671 1155 X7HyMhZNoso 681 1168 0 0.000000 0.000000
  run_episode 688 1178 X7HyMhZNoso 783 1336 4 0.000000 5.328553
  run_episode 319 512 2azQ1b91cZZ 429 721 4 0.000000 2.920037
  run_episode 264 418 zsNo4HB9uLZ 639 1108 6 0.000000 12.458867
  run_episode 658 1139 QUCTc6BB5sX 660 1141 5 0.000000 7.587837
  run_episode 310 500 QUCTc6BB5sX 792 1351 5 0.368796 9.363973
  run_episode 351 577 QUCTc6BB5sX 105 151 5 0.000000 14.125214
  run_episode 539 930 TbHJrupSAjP 198 307 7 1.519046 7.633810
  run_episode 581 1008 2azQ1b91cZZ 93 139 5 0.000000 13.760632
  run_episode 366 601 X7HyMhZNoso 1038 1759 7 0.000000 9.774121
  run_episode 490 854 X7HyMhZNoso 1038 1759 6 0.190970 8.881821
  run_episode 888 1516 EU6Fwq7SyZv 276 442 4 1.213044 8.710791
  run_episode 815 1380 x8F5xyUWy9e 951 1633 4 0.830905 5.487870
  run_episode 20 33 x8F5xyUWy9e 135 199 4 1.070148 4.718646
  run_episode 813 1378 x8F5xyUWy9e 951 1633 4 0.830905 4.214828
  run_episode 189 286 2azQ1b91cZZ 696 1189 4 0.000000 6.937679
  run_episode 783 1336 X7HyMhZNoso 687 1177 4 0.960138 7.436316
  run_episode 784 1337 X7HyMhZNoso 687 1177 4 0.960138 7.972808
  run_episode 785 1338 X7HyMhZNoso 687 1177 4 0.960138 7.768569
  run_episode 1004 1713 TbHJrupSAjP 585 1018 4 0.315807 4.023420
  run_episode 1062 1801 2azQ1b91cZZ 930 1579 5 0.278728 9.902829
  run_episode 86 126 zsNo4HB9uLZ 942 1612 5 0.215112 12.411028
  run_episode 271 428 QUCTc6BB5sX 66 94 6 0.244698 15.260509
  run_episode 479 810 2azQ1b91cZZ 816 1381 5 0.918991 7.632172
  run_episode 656 1137 zsNo4HB9uLZ 984 1681 6 0.000000 10.837272

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
