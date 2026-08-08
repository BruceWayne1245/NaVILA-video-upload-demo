#!/usr/bin/env bash
# StreamVLN, oracle_hint (NOT hint_action) 30-episode set, same episode list
# and same phase_prompt/route_memory/oracle-hint config as NaVILA's own
# oracle_shadow_loftr_v4_30_return_anchor_fix_20260701 batch, minus
# --hint_action_arbiter (that mechanism is a separate, later test).
set -u

ROOT="/mnt/SSD4T/teambruce/projects/streamvln"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
ISAACLAB="/mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh"
CONDA="/home/teambruce/miniconda3/bin/conda"
STREAMVLN_ENV="/mnt/SSD4T/teambruce/conda_envs/streamvln"
ISAAC_ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
PORT_BASE="${PORT_BASE:-59950}"
RUN_TAG="${RUN_TAG:-streamvln_oracle_hint_30ep_20260808}"
START_AT="${START_AT:-0}"
ONLY_EPISODES="${ONLY_EPISODES:-}"
EXTRA_ISAAC_ARGS="${EXTRA_ISAAC_ARGS:-} \
  --route_memory \
  --route_hint_mode=compact \
  --route_hint_source=oracle \
  --oracle_align_return_yaw_to_anchor_segment \
  --stop_gate \
  --stop_gate_r_in=3.0 \
  --stop_gate_r_out=3.0 \
  --topdown_route_map"
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"
SUMMARY="${LOG_DIR}/summary.tsv"

mkdir -p "${LOG_DIR}"

if [[ ! -f "${SUMMARY}" ]]; then
  cat > "${SUMMARY}" <<'EOF'
episode_idx	scene	port	start_time	end_time	exit_code	result_suffix	server_log	eval_log	measurement_file	outbound_success	return_success	round_trip_success	distance_to_start	outbound_stop_distance_to_goal	trajectory_record_count
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
    if [[ -n "${SERVER_PID:-}" ]] && ! kill -0 "${SERVER_PID}" 2>/dev/null; then
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

stop_existing_server() {
  local pids
  pids="$(pgrep -f "streamvln_server.py --port ${PORT}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping pre-existing streamvln_server.py on port ${PORT}: ${pids}" | tee -a "${LOG_DIR}/batch.log"
    while read -r pid; do
      [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
    done <<< "${pids}"
    sleep 5
  fi
}

start_streamvln_server() {
  local server_log="$1"
  stop_existing_server
  if port_is_listening; then
    echo "Port ${PORT} is still busy before server startup; refusing to reuse an existing server." | tee -a "${server_log}"
    return 1
  fi

  cd "${ROOT}" || return 99
  PYTHONUNBUFFERED=1 setsid "${STREAMVLN_ENV}/bin/python" -u streamvln_server.py \
    --port "${PORT}" \
    >> "${server_log}" 2>&1 &
  SERVER_PID="$!"

  if ! wait_for_port_open; then
    echo "Timed out waiting for streamvln_server on port ${PORT}" | tee -a "${server_log}"
    kill_process_group "${SERVER_PID}"
    return 1
  fi
  echo "streamvln_server ready on port ${PORT}, pid=${SERVER_PID}" | tee -a "${server_log}"
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
  local scene="$2"
  local suffix="${RUN_TAG}_ep${ep_idx}"
  local server_log="${LOG_DIR}/ep${ep_idx}_server.log"
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
  SERVER_PID=""
  start_time="$(date -Is)"
  echo "[$start_time] starting episode ${ep_idx} (${scene}), port=${PORT}, suffix=${suffix}" | tee -a "${LOG_DIR}/batch.log"

  if start_streamvln_server "${server_log}"; then
    cd "${BENCH}" || exit_code=99
    if [[ -z "${exit_code:-}" ]]; then
      timeout --kill-after=120s 1800s env TERM=xterm PYTHONUNBUFFERED=1 OMNI_KIT_ACCEPT_EULA=YES "${CONDA}" run \
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
        ${EXTRA_ISAAC_ARGS} \
        >> "${eval_log}" 2>&1
      exit_code="$?"
    fi
  else
    exit_code=98
  fi

  kill_process_group "${SERVER_PID}"
  wait_for_port_closed || echo "Warning: port ${PORT} still appears busy after episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log"
  sleep 10

  end_time="$(date -Is)"
  parsed="$(extract_measurement_summary "${suffix}")"
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${ep_idx}" "${scene}" "${PORT}" "${start_time}" \
    "${end_time}" "${exit_code}" "${suffix}" "${server_log}" "${eval_log}" "${parsed}" \
    >> "${SUMMARY}"
  echo "[$end_time] finished episode ${ep_idx}, exit_code=${exit_code}" | tee -a "${LOG_DIR}/batch.log"
  unset exit_code
}

main() {
  echo "Batch started at $(date -Is)" | tee "${LOG_DIR}/batch.log"
  echo "StreamVLN oracle_hint (no hint_action_arbiter) 30-episode set, same list as NaVILA's oracle_shadow_loftr_v4_30_return_anchor_fix_20260701." | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a fresh streamvln_server.py process and a fresh Isaac evaluation process (avoids the streaming-memory OOM issue found in single-process reuse testing)." | tee -a "${LOG_DIR}/batch.log"
  if [[ -n "${ONLY_EPISODES}" ]]; then
    echo "Running only episodes: ${ONLY_EPISODES}" | tee -a "${LOG_DIR}/batch.log"
  fi
  echo "Extra Isaac args: ${EXTRA_ISAAC_ARGS}" | tee -a "${LOG_DIR}/batch.log"

  run_episode 106 QUCTc6BB5sX
  run_episode 367 X7HyMhZNoso
  run_episode 613 zsNo4HB9uLZ
  run_episode 133 2azQ1b91cZZ
  run_episode 198 TbHJrupSAjP
  run_episode 186 EU6Fwq7SyZv
  run_episode 4 x8F5xyUWy9e
  run_episode 336 Z6MFQCViBuw
  run_episode 408 oLBMNvg9in8
  run_episode 107 QUCTc6BB5sX
  run_episode 368 X7HyMhZNoso
  run_episode 614 zsNo4HB9uLZ
  run_episode 993 QUCTc6BB5sX
  run_episode 134 2azQ1b91cZZ
  run_episode 199 TbHJrupSAjP
  run_episode 187 EU6Fwq7SyZv
  run_episode 5 x8F5xyUWy9e
  run_episode 337 Z6MFQCViBuw
  run_episode 409 oLBMNvg9in8
  run_episode 678 zsNo4HB9uLZ
  run_episode 679 zsNo4HB9uLZ
  run_episode 680 zsNo4HB9uLZ
  run_episode 994 QUCTc6BB5sX
  run_episode 995 QUCTc6BB5sX
  run_episode 1038 X7HyMhZNoso
  run_episode 1039 X7HyMhZNoso
  run_episode 1040 X7HyMhZNoso
  run_episode 465 QUCTc6BB5sX
  run_episode 466 QUCTc6BB5sX
  run_episode 467 QUCTc6BB5sX

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
