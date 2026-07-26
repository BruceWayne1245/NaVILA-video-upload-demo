#!/usr/bin/env bash
set -u

# =====================================================================================
# 2026-07-26 -- Route 1 (this session's, non-model geometry/vision cross-check) live
# round-trip driver for the vision_disagreement_mode A/B, adapted directly from
# scripts/run_oracle_anchor_100ep_batch_20260720.sh (same VLM-server-per-episode /
# timeout-wrapping / summary-logging machinery, unchanged) -- only the episode manifest
# and the two callers differ. Runs the SAME 50-episode "outbound most likely to succeed"
# set Route 2 (Codex, model-based ICP-trust track) selected for its 2026-07-25 active-50ep
# run (experiments/2026-07-25-policy-v2-active-50ep/episodes.tsv in
# /home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725), read directly from
# the LIVE Route1 code path (NaVILA-Bench/scripts/round_trip_eval.py), not any isolated
# candidate. Two arms, driven by env vars ARM_RUN_TAG / EXTRA_ISAAC_ARGS set by the master
# script that sources this file twice (diagnostic baseline, then downgrade).
# =====================================================================================

ROOT="/mnt/SSD4T/teambruce/projects/navila-isaac"
BENCH="${ROOT}/NaVILA-Bench"
ISAACLAB="${ROOT}/IsaacLab/isaaclab.sh"
CONDA="/home/teambruce/miniconda3/bin/conda"
VLM_ENV="/mnt/SSD4T/teambruce/conda_envs/navila-vlm"
ISAAC_ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
MODEL_PATH="${ROOT}/checkpoints/navila-llama3-8b-8f"
PORT_BASE="${PORT_BASE:-59000}"
PORT="${PORT:-59000}"
RUN_TAG="${RUN_TAG:?RUN_TAG must be set by caller}"
ROUTE_HINT_SOURCE="${ROUTE_HINT_SOURCE:-integrated}"
ROUTE_RELOCALIZATION_BACKEND="${ROUTE_RELOCALIZATION_BACKEND:-sequential_pair}"
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT="${ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT:-1}"
EXTRA_ISAAC_ARGS="${EXTRA_ISAAC_ARGS:-}"
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
        scripts/round_trip_eval.py \
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
        --route_hint_mode=compact \
        --route_hint_source="${ROUTE_HINT_SOURCE}" \
        --route_relocalization_backend="${ROUTE_RELOCALIZATION_BACKEND}" \
        ${ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT:+--oracle_align_return_yaw_to_anchor_segment} \
        ${EXTRA_ISAAC_ARGS} \
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
  echo "Batch started at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
  echo "RUN_TAG=${RUN_TAG}" | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a fresh 8-bit VLM server and a fresh Isaac evaluation process." | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a unique VLM port: PORT_BASE(${PORT_BASE}) + episode_idx." | tee -a "${LOG_DIR}/batch.log"
  echo "Route hint config: --route_memory --route_hint_mode=compact --route_hint_source=${ROUTE_HINT_SOURCE} --route_relocalization_backend=${ROUTE_RELOCALIZATION_BACKEND}" | tee -a "${LOG_DIR}/batch.log"
  echo "Episode timeout: ${EPISODE_TIMEOUT_SECONDS}s (kill-after ${EPISODE_TIMEOUT_KILL_AFTER_SECONDS}s)" | tee -a "${LOG_DIR}/batch.log"
  echo "Extra Isaac args: ${EXTRA_ISAAC_ARGS}" | tee -a "${LOG_DIR}/batch.log"

  # 50-episode "outbound most likely to succeed" set -- identical to Route 2's
  # experiments/2026-07-25-policy-v2-active-50ep/episodes.tsv (episode_idx column) in
  # /home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725, copied verbatim so
  # both routes' results are on the same episode cohort. episode_idx episode_id scene
  # neighbor_idx neighbor_episode_id matched_waypoints mean_distance baseline_distance_to_start.
  run_episode 4 8 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 5 9 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 19 32 x8F5xyUWy9e 135 199 4 1.070148 6.361872
  run_episode 87 127 EU6Fwq7SyZv 288 460 5 1.348777 4.614529
  run_episode 88 128 EU6Fwq7SyZv 288 460 5 1.348777 2.292637
  run_episode 89 129 EU6Fwq7SyZv 288 460 5 1.349000 2.292637
  run_episode 93 139 2azQ1b91cZZ 579 1006 5 0.000000 13.368412
  run_episode 95 141 2azQ1b91cZZ 579 1006 5 0.000000 13.368412
  run_episode 196 302 zsNo4HB9uLZ 771 1321 6 0.296615 8.340226
  run_episode 205 314 2azQ1b91cZZ 807 1372 4 1.551582 9.997160
  run_episode 264 418 zsNo4HB9uLZ 639 1108 6 0.000000 12.458867
  run_episode 268 422 QUCTc6BB5sX 435 739 6 0.000000 8.807060
  run_episode 276 442 EU6Fwq7SyZv 888 1516 4 0.261469 11.290769
  run_episode 310 500 QUCTc6BB5sX 792 1351 5 0.368796 9.363973
  run_episode 344 564 X7HyMhZNoso 381 634 4 0.677694 10.897293
  run_episode 351 577 QUCTc6BB5sX 105 151 5 0.000000 14.125214
  run_episode 355 584 x8F5xyUWy9e 3 7 5 0.083086 9.844459
  run_episode 366 601 X7HyMhZNoso 1038 1759 7 0.000000 9.774121
  run_episode 367 602 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 368 603 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 420 712 zsNo4HB9uLZ 612 1069 7 0.225539 14.089020
  run_episode 427 719 2azQ1b91cZZ 756 1288 5 0.853292 5.156441
  run_episode 484 827 zsNo4HB9uLZ 810 1375 4 0.000000 7.025259
  run_episode 489 853 X7HyMhZNoso 1038 1759 6 0.190970 8.881821
  run_episode 490 854 X7HyMhZNoso 1038 1759 6 0.190970 8.881821
  run_episode 491 855 X7HyMhZNoso 1038 1759 6 0.190970 3.666043
  run_episode 500 870 zsNo4HB9uLZ 222 352 4 0.479000 7.425987
  run_episode 539 930 TbHJrupSAjP 198 307 7 1.519046 7.633810
  run_episode 579 1006 2azQ1b91cZZ 93 139 5 0.000000 13.760632
  run_episode 581 1008 2azQ1b91cZZ 93 139 5 0.000000 13.760632
  run_episode 646 1118 x8F5xyUWy9e 354 583 4 0.475011 8.570651
  run_episode 647 1119 x8F5xyUWy9e 354 583 4 0.475000 8.374983
  run_episode 658 1139 QUCTc6BB5sX 660 1141 5 0.000000 7.587837
  run_episode 669 1153 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 671 1155 X7HyMhZNoso 681 1168 5 0.000000 6.450071
  run_episode 680 1167 zsNo4HB9uLZ 612 1069 7 0.000000 12.981381
  run_episode 687 1177 X7HyMhZNoso 783 1336 4 0.000000 5.328553
  run_episode 688 1178 X7HyMhZNoso 783 1336 4 0.000000 5.328553
  run_episode 698 1191 2azQ1b91cZZ 120 166 5 0.333557 10.228483
  run_episode 784 1337 X7HyMhZNoso 687 1177 4 0.960138 7.768569
  run_episode 785 1338 X7HyMhZNoso 687 1177 4 0.960138 7.768569
  run_episode 813 1378 x8F5xyUWy9e 951 1633 4 0.830905 4.214828
  run_episode 815 1380 x8F5xyUWy9e 951 1633 4 0.830905 5.487870
  run_episode 844 1439 zsNo4HB9uLZ 882 1501 5 0.000000 6.517529
  run_episode 888 1516 EU6Fwq7SyZv 276 442 4 1.213044 8.710791
  run_episode 961 1643 TbHJrupSAjP 291 472 4 0.315807 6.949306
  run_episode 962 1644 TbHJrupSAjP 291 472 4 0.315807 6.949306
  run_episode 994 1700 QUCTc6BB5sX 105 151 7 0.000000 12.657429
  run_episode 1038 1759 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 1062 1801 2azQ1b91cZZ 930 1579 5 0.278728 9.902829

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
