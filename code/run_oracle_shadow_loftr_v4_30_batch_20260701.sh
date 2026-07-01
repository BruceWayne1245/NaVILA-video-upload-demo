#!/usr/bin/env bash
# Oracle-guided 30-episode v4 baseline set with non-oracle LoFTR shadow telemetry.
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
RUN_TAG="${RUN_TAG:-oracle_shadow_loftr_v4_30_20260701}"
START_AT="${START_AT:-0}"
ONLY_EPISODES="${ONLY_EPISODES:-}"
EXTRA_ISAAC_ARGS="${EXTRA_ISAAC_ARGS:-} \
  --route_memory \
  --route_hint_mode=compact \
  --route_hint_source=oracle \
  --route_relocalization_backend=loftr_depth \
  --route_relocalization_interval_updates=25 \
  --oracle_align_return_yaw_to_anchor_segment \
  --stop_gate \
  --stop_gate_r_in=3.0 \
  --stop_gate_r_out=3.0 \
  --topdown_route_map \
  --hint_action_arbiter"
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
      TERM=xterm OMNI_KIT_ACCEPT_EULA=YES "${CONDA}" run \
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
        ${EXTRA_ISAAC_ARGS} \
        >> "${eval_log}" 2>&1
      exit_code="$?"
    fi
  else
    exit_code=98
  fi

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
  echo "30-episode v4 baseline set with oracle hints and non-oracle LoFTR shadow telemetry." | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a fresh 8-bit VLM server and a fresh Isaac evaluation process." | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a unique VLM port: PORT_BASE(${PORT_BASE}) + episode_idx." | tee -a "${LOG_DIR}/batch.log"
  if [[ -n "${ONLY_EPISODES}" ]]; then
    echo "Running only episodes: ${ONLY_EPISODES}" | tee -a "${LOG_DIR}/batch.log"
  fi
  echo "Extra Isaac args: ${EXTRA_ISAAC_ARGS}" | tee -a "${LOG_DIR}/batch.log"

  run_episode 106 152 QUCTc6BB5sX 993 1699 7 0.000 0.000
  run_episode 367 602 X7HyMhZNoso 1038 1759 7 0.000 5.793
  run_episode 613 1070 zsNo4HB9uLZ 678 1165 7 0.000 1.996
  run_episode 133 194 2azQ1b91cZZ 756 1288 7 0.258 6.199
  run_episode 198 307 TbHJrupSAjP 537 928 7 1.519 0.550
  run_episode 186 280 EU6Fwq7SyZv 447 754 6 0.433 3.561
  run_episode 4 8 x8F5xyUWy9e 354 583 5 0.000 10.151
  run_episode 336 547 Z6MFQCViBuw 651 1132 4 0.000 12.322
  run_episode 408 682 oLBMNvg9in8 522 907 4 0.761 6.884
  run_episode 107 153 QUCTc6BB5sX 993 1699 7 0.000 12.227
  run_episode 368 603 X7HyMhZNoso 1038 1759 7 0.000 6.826
  run_episode 614 1071 zsNo4HB9uLZ 678 1165 7 0.000 0.761
  run_episode 993 1699 QUCTc6BB5sX 105 151 7 0.000 1.994
  run_episode 134 195 2azQ1b91cZZ 756 1288 7 0.258 6.223
  run_episode 199 308 TbHJrupSAjP 537 928 7 1.519 0.589
  run_episode 187 281 EU6Fwq7SyZv 447 754 6 0.433 11.813
  run_episode 5 9 x8F5xyUWy9e 354 583 5 0.000 8.598
  run_episode 337 548 Z6MFQCViBuw 651 1132 4 0.000 4.622
  run_episode 409 683 oLBMNvg9in8 522 907 4 0.761 2.125
  run_episode 678 1165 zsNo4HB9uLZ 612 1069 7 0.000 3.782
  run_episode 679 1166 zsNo4HB9uLZ 612 1069 7 0.000 1.995
  run_episode 680 1167 zsNo4HB9uLZ 612 1069 7 0.000 3.710
  run_episode 994 1700 QUCTc6BB5sX 105 151 7 0.000 4.522
  run_episode 995 1701 QUCTc6BB5sX 105 151 7 0.000 11.760
  run_episode 1038 1759 X7HyMhZNoso 366 601 7 0.000 1.998
  run_episode 1039 1760 X7HyMhZNoso 366 601 7 0.000 3.748
  run_episode 1040 1761 X7HyMhZNoso 366 601 7 0.000 2.415
  run_episode 465 793 QUCTc6BB5sX 600 1042 7 0.216 0.000
  run_episode 466 794 QUCTc6BB5sX 600 1042 7 0.216 3.630
  run_episode 467 795 QUCTc6BB5sX 600 1042 7 0.216 4.176

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
