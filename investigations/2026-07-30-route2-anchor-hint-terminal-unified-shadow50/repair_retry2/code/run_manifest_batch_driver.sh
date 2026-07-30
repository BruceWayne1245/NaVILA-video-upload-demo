#!/usr/bin/env bash
set -u

ROOT="/mnt/SSD4T/teambruce/projects/navila-isaac"
BENCH="${ROOT}/NaVILA-Bench"
CONDA="/home/teambruce/miniconda3/bin/conda"
VLM_ENV="/mnt/SSD4T/teambruce/conda_envs/navila-vlm"
ISAAC_ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
MODEL_PATH="${ROOT}/checkpoints/navila-llama3-8b-8f"
PORT_BASE="${PORT_BASE:-54321}"
PORT="${PORT:-54321}"
RUN_TAG="${RUN_TAG:-oracle_anchor_100ep_20260720}"
ROUTE_HINT_SOURCE="${ROUTE_HINT_SOURCE:-integrated}"
ROUTE_RELOCALIZATION_BACKEND="${ROUTE_RELOCALIZATION_BACKEND:-oracle_anchor}"
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT="${ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT:-}"
EXTRA_ISAAC_ARGS="${EXTRA_ISAAC_ARGS:-}"
EVAL_SCRIPT="${EVAL_SCRIPT:-scripts/round_trip_eval.py}"
EPISODE_VALIDATOR="${EPISODE_VALIDATOR:-}"
MANIFEST="${MANIFEST:-}"
START_AT="${START_AT:-0}"
ONLY_EPISODES="${ONLY_EPISODES:-}"
FAIL_FAST="${FAIL_FAST:-0}"
REQUIRE_ALL_EPISODES="${REQUIRE_ALL_EPISODES:-1}"
EPISODE_TIMEOUT_SECONDS="${EPISODE_TIMEOUT_SECONDS:-7200}"
EPISODE_TIMEOUT_KILL_AFTER_SECONDS="${EPISODE_TIMEOUT_KILL_AFTER_SECONDS:-300}"
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"
SUMMARY="${LOG_DIR}/summary.tsv"
RESULT_PREFIX="${BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"

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
  local result_dir="${RESULT_PREFIX}_${suffix}"

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
        "${ISAAC_ENV}/bin/python" \
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

  # Kit shutdown has historically converted a pending Python exception into
  # process exit 0.  Never treat the shell status alone as episode success.
  if [[ "${exit_code}" == "0" ]] && grep -Fq "[fatal_evaluator_exit]" "${eval_log}" 2>/dev/null; then
    echo "[driver_integrity_fail] fatal evaluator marker found for episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
    exit_code=97
  fi
  if [[ "${exit_code}" == "0" ]]; then
    if [[ -z "${EPISODE_VALIDATOR}" || ! -f "${EPISODE_VALIDATOR}" ]]; then
      echo "[driver_integrity_fail] episode validator missing: ${EPISODE_VALIDATOR}" | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
      exit_code=95
    elif ! "${ISAAC_ENV}/bin/python" "${EPISODE_VALIDATOR}" \
      "${result_dir}" "${ep_idx}" >> "${eval_log}" 2>&1; then
      echo "[driver_integrity_fail] incomplete capture for episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
      exit_code=96
    fi
  fi

  end_time="$(date -Is)"
  parsed="$(extract_measurement_summary "${suffix}")"
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
    "${matched}" "${mean_distance}" "${baseline_distance}" "${PORT}" "${start_time}" \
    "${end_time}" "${exit_code}" "${suffix}" "${vlm_log}" "${eval_log}" "${parsed}" \
    >> "${SUMMARY}"
  echo "[$end_time] finished episode ${ep_idx}, exit_code=${exit_code}" | tee -a "${LOG_DIR}/batch.log"
  if [[ "${exit_code}" != "0" ]]; then
    unset exit_code
    return 1
  fi
  unset exit_code
  return 0
}

main() {
  local episode_failures=0
  if [[ -z "${MANIFEST}" || ! -f "${MANIFEST}" ]]; then
    echo "FATAL: MANIFEST is missing or not a file: ${MANIFEST}" >&2
    return 2
  fi
  echo "Batch started at $(date -Is)" | tee "${LOG_DIR}/batch.log"
  echo "Each episode uses a fresh 8-bit VLM server and a fresh Isaac evaluation process." | tee -a "${LOG_DIR}/batch.log"
  echo "Each episode uses a unique VLM port: PORT_BASE(${PORT_BASE}) + episode_idx." | tee -a "${LOG_DIR}/batch.log"
  if [[ -n "${ONLY_EPISODES}" ]]; then
    echo "Running only episodes: ${ONLY_EPISODES}" | tee -a "${LOG_DIR}/batch.log"
  fi
  echo "Route hint config: --route_memory --route_hint_mode=compact --route_hint_source=${ROUTE_HINT_SOURCE} --route_relocalization_backend=${ROUTE_RELOCALIZATION_BACKEND}" | tee -a "${LOG_DIR}/batch.log"
  echo "Episode timeout: ${EPISODE_TIMEOUT_SECONDS}s (kill-after ${EPISODE_TIMEOUT_KILL_AFTER_SECONDS}s)" | tee -a "${LOG_DIR}/batch.log"
  if [[ -n "${ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT}" ]]; then
    echo "Return yaw alignment enabled: --oracle_align_return_yaw_to_anchor_segment" | tee -a "${LOG_DIR}/batch.log"
  fi
  if [[ -n "${EXTRA_ISAAC_ARGS}" ]]; then
    echo "Extra Isaac args: ${EXTRA_ISAAC_ARGS}" | tee -a "${LOG_DIR}/batch.log"
  fi

  while IFS=$'\t' read -r ep_idx ep_id scene neighbor_idx neighbor_ep_id \
    matched mean_distance baseline_distance _length_band _cohort_role \
    _geometry_sha256; do
    if [[ "${ep_idx}" == "episode_idx" || -z "${ep_idx}" ]]; then
      continue
    fi
    if ! run_episode \
      "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
      "${matched}" "${mean_distance}" "${baseline_distance}"; then
      episode_failures=$((episode_failures + 1))
      if [[ "${FAIL_FAST}" == "1" ]]; then
        echo "FATAL: episode integrity failure with FAIL_FAST=1" | tee -a "${LOG_DIR}/batch.log"
        return 2
      fi
    fi
  done < "${MANIFEST}"
  echo "Batch finished at $(date -Is), episode_failures=${episode_failures}" | tee -a "${LOG_DIR}/batch.log"
  if (( episode_failures > 0 )) && [[ "${REQUIRE_ALL_EPISODES}" == "1" ]]; then
    return 2
  fi
  return 0

  # 100-episode set (2026-07-20): the existing 07-14 50-episode set (hard-11 +
  # 39 episodes sampled 20260714) plus 50 NEW episodes sampled 20260720 with
  # the same method -- _find_reverse_path_neighbor over the full 1077-episode
  # pool (646 candidates had a valid reverse-path neighbor), fixed seed
  # 20260720, round-robin-by-scene selection preferring scenes under-
  # represented in the existing 50 (Z6MFQCViBuw 1->6, oLBMNvg9in8 stays at 1 --
  # only 1 valid candidate exists in that scene). Purpose: get a larger (n=100)
  # sample to tell a genuine bug in stop_gate/hint_action/closure_check from a
  # small-sample fluke, before touching any of those gates -- see
  # investigations/2026-07-20-stopgate-batch-8ep-deep-dive/FINDINGS.md's two
  # failure cases (ep680: route-level ICP degradation; ep319: VLM repeatedly
  # disagreeing with the hint's turn direction while the arbiter's own gates
  # decline to intervene about half the time).

  # --- existing 50 (identical to run_oracle_anchor_50ep_batch_20260714.sh) ---
  run_episode 4 8 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 5 9 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 134 195 2azQ1b91cZZ 756 1288 7 0.258000 8.337229
  run_episode 187 281 EU6Fwq7SyZv 447 754 6 0.433000 10.897436
  run_episode 367 602 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 368 603 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 408 682 oLBMNvg9in8 522 907 4 0.761000 5.976311
  run_episode 678 1165 zsNo4HB9uLZ 612 1069 7 0.000000 12.981381
  run_episode 680 1167 zsNo4HB9uLZ 612 1069 7 0.000000 12.981381
  run_episode 994 1700 QUCTc6BB5sX 105 151 7 0.000000 12.657429
  run_episode 1040 1761 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 144 214 2azQ1b91cZZ 474 805 4 0.718000 5.719809
  run_episode 166 251 zsNo4HB9uLZ 162 247 4 0.269000 6.438305
  run_episode 1008 1717 QUCTc6BB5sX 642 1114 5 0.000000 10.165862
  run_episode 1058 1791 TbHJrupSAjP 615 1075 4 0.712000 7.765753
  run_episode 89 129 EU6Fwq7SyZv 288 460 5 1.349000 2.292637
  run_episode 647 1119 x8F5xyUWy9e 354 583 4 0.475000 8.374983
  run_episode 381 634 X7HyMhZNoso 342 562 4 0.499000 6.710190
  run_episode 651 1132 Z6MFQCViBuw 336 547 4 0.000000 7.984009
  run_episode 409 683 oLBMNvg9in8 522 907 4 0.761000 5.976311
  run_episode 639 1108 zsNo4HB9uLZ 264 418 6 0.000000 10.928180
  run_episode 319 512 2azQ1b91cZZ 429 721 4 0.000000 2.920037
  run_episode 49 77 2azQ1b91cZZ 114 160 6 0.000000 6.494152
  run_episode 488 843 QUCTc6BB5sX 834 1420 6 0.000000 11.092296
  run_episode 56 84 QUCTc6BB5sX 237 379 5 0.348000 12.936306
  run_episode 273 439 zsNo4HB9uLZ 882 1501 5 0.361000 2.011883
  run_episode 708 1201 QUCTc6BB5sX 636 1105 5 0.000000 7.917972
  run_episode 486 841 QUCTc6BB5sX 834 1420 6 0.000000 11.092296
  run_episode 1068 1807 zsNo4HB9uLZ 264 418 6 0.301000 15.404894
  run_episode 498 868 zsNo4HB9uLZ 222 352 4 0.479000 7.425987
  run_episode 974 1656 TbHJrupSAjP 615 1075 6 0.568000 6.674971
  run_episode 640 1109 zsNo4HB9uLZ 264 418 6 0.000000 10.928180
  run_episode 1000 1709 TbHJrupSAjP 666 1150 5 0.888000 9.166546
  run_episode 1038 1759 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 500 870 zsNo4HB9uLZ 222 352 4 0.479000 7.425987
  run_episode 1011 1720 zsNo4HB9uLZ 864 1474 5 0.000000 6.161442
  run_episode 589 1022 QUCTc6BB5sX 996 1705 5 0.000000 10.763077
  run_episode 758 1290 2azQ1b91cZZ 132 193 7 0.258000 9.715021
  run_episode 875 1488 TbHJrupSAjP 585 1018 4 0.793000 6.991297
  run_episode 295 476 zsNo4HB9uLZ 45 73 4 0.000000 8.425889
  run_episode 973 1655 TbHJrupSAjP 615 1075 6 0.568000 6.674971
  run_episode 342 562 X7HyMhZNoso 381 634 4 0.678000 9.707796
  run_episode 515 891 QUCTc6BB5sX 564 976 4 0.000000 11.755993
  run_episode 281 447 zsNo4HB9uLZ 981 1678 6 0.000000 11.342166
  run_episode 268 422 QUCTc6BB5sX 435 739 6 0.000000 8.807060
  run_episode 96 142 QUCTc6BB5sX 855 1462 5 0.000000 4.898193
  run_episode 354 583 x8F5xyUWy9e 3 7 5 0.083000 9.835469
  run_episode 347 570 QUCTc6BB5sX 54 82 4 0.000000 10.203632
  run_episode 430 722 2azQ1b91cZZ 318 511 4 0.000000 4.148210
  run_episode 214 335 QUCTc6BB5sX 501 874 6 0.307000 10.043250

  # --- 50 new episodes sampled 20260720 ---
  run_episode 338 549 Z6MFQCViBuw 651 1132 4 0.000000 9.215299
  run_episode 277 443 EU6Fwq7SyZv 888 1516 4 0.261469 10.349057
  run_episode 410 684 oLBMNvg9in8 522 907 4 0.760731 5.976311
  run_episode 137 201 x8F5xyUWy9e 18 31 4 0.000000 4.622848
  run_episode 198 307 TbHJrupSAjP 537 928 7 1.519046 5.982727
  run_episode 189 286 2azQ1b91cZZ 696 1189 4 0.000000 6.937679
  run_episode 491 855 X7HyMhZNoso 1038 1759 6 0.190970 3.666043
  run_episode 963 1645 zsNo4HB9uLZ 117 163 5 0.000000 4.847609
  run_episode 55 83 QUCTc6BB5sX 237 379 5 0.347772 12.936306
  run_episode 337 548 Z6MFQCViBuw 651 1132 4 0.000000 9.215299
  run_episode 289 461 EU6Fwq7SyZv 87 127 5 1.348777 3.093649
  run_episode 813 1378 x8F5xyUWy9e 951 1633 4 0.830905 4.214828
  run_episode 537 928 TbHJrupSAjP 198 307 7 1.519046 4.790441
  run_episode 932 1581 2azQ1b91cZZ 1062 1801 5 0.278728 7.676483
  run_episode 382 635 X7HyMhZNoso 342 562 4 0.498710 6.710190
  run_episode 726 1240 zsNo4HB9uLZ 942 1612 5 0.000000 3.751096
  run_episode 546 943 QUCTc6BB5sX 855 1462 5 0.000000 10.419371
  run_episode 336 547 Z6MFQCViBuw 651 1132 4 0.000000 9.215299
  run_episode 889 1517 EU6Fwq7SyZv 276 442 4 1.213044 8.345141
  run_episode 20 33 x8F5xyUWy9e 135 199 4 1.070148 4.718646
  run_episode 1004 1713 TbHJrupSAjP 585 1018 4 0.315807 4.023420
  run_episode 178 263 2azQ1b91cZZ 36 61 6 0.062588 9.134084
  run_episode 783 1336 X7HyMhZNoso 687 1177 4 0.960138 7.436316
  run_episode 162 247 zsNo4HB9uLZ 810 1375 4 0.000000 7.296314
  run_episode 467 795 QUCTc6BB5sX 600 1042 7 0.216221 8.690815
  run_episode 653 1134 Z6MFQCViBuw 336 547 4 0.000000 7.984009
  run_episode 88 128 EU6Fwq7SyZv 288 460 5 1.348777 2.292637
  run_episode 136 200 x8F5xyUWy9e 18 31 4 0.000000 4.622848
  run_episode 1002 1711 TbHJrupSAjP 585 1018 4 0.315807 4.023420
  run_episode 1035 1756 2azQ1b91cZZ 492 859 5 0.416649 12.094039
  run_episode 669 1153 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 1042 1766 zsNo4HB9uLZ 639 1108 4 0.000000 9.364553
  run_episode 692 1182 QUCTc6BB5sX 396 664 5 0.000000 8.354051
  run_episode 652 1133 Z6MFQCViBuw 336 547 4 0.000000 7.984009
  run_episode 248 390 EU6Fwq7SyZv 186 280 5 0.648125 7.258468
  run_episode 953 1635 x8F5xyUWy9e 813 1378 4 0.183353 2.661269
  run_episode 1001 1710 TbHJrupSAjP 666 1150 5 0.888479 9.166546
  run_episode 696 1189 2azQ1b91cZZ 120 166 5 0.333557 10.149185
  run_episode 1039 1760 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 525 910 zsNo4HB9uLZ 117 163 6 0.000000 7.814394
  run_episode 271 428 QUCTc6BB5sX 66 94 6 0.244698 15.260509
  run_episode 447 754 EU6Fwq7SyZv 186 280 6 0.507529 8.968953
  run_episode 386 642 x8F5xyUWy9e 645 1117 4 0.763060 6.902399
  run_episode 830 1407 TbHJrupSAjP 225 358 5 0.000000 5.166861
  run_episode 122 168 2azQ1b91cZZ 696 1189 5 0.333557 5.982823
  run_episode 670 1154 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 534 922 zsNo4HB9uLZ 840 1435 5 0.750029 4.674335
  run_episode 436 740 QUCTc6BB5sX 267 421 6 0.000000 10.587338
  run_episode 290 462 EU6Fwq7SyZv 87 127 5 1.348777 3.093649
  run_episode 135 199 x8F5xyUWy9e 18 31 4 0.000000 4.622848

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
