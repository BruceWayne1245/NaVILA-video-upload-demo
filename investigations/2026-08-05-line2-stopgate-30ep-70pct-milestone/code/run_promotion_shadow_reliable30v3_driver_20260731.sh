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
EPISODE_TIMEOUT_SECONDS="${EPISODE_TIMEOUT_SECONDS:-2400}"
EPISODE_TIMEOUT_KILL_AFTER_SECONDS="${EPISODE_TIMEOUT_KILL_AFTER_SECONDS:-300}"
# Stall watchdog: if eval_log stops growing for this long, the episode is
# considered stuck (not just slow) and gets killed immediately instead of
# waiting out the full EPISODE_TIMEOUT_SECONDS wall-clock cap. Set generously
# above normal VLM-call latency (observed ~30-90s/call) to avoid false positives.
EPISODE_STALL_SECONDS="${EPISODE_STALL_SECONDS:-600}"
STALL_CHECK_INTERVAL_SECONDS="${STALL_CHECK_INTERVAL_SECONDS:-30}"
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

# Process-group kill misses descendants that Isaac Sim/Kit has detached into
# their own session (observed 2026-07-31: a round_trip_eval.py worker survived
# timeout+process-group kill and kept running for 2+ hours after its episode
# was already logged as "finished"). This sweeps by cmdline pattern as a
# second pass and force-kills anything still matching this episode.
sweep_kill_stragglers() {
  local ep_idx="$1"
  local suffix="$2"
  local port="$3"
  local pids

  pids="$(pgrep -f -- "--episode_idx=${ep_idx} .*--result_suffix=${suffix}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "sweep_kill_stragglers: found leftover eval pid(s) for ${suffix}: ${pids}" | tee -a "${LOG_DIR}/batch.log"
    while read -r p; do
      [[ -n "${p}" ]] && kill -9 "${p}" 2>/dev/null || true
    done <<< "${pids}"
  fi

  pids="$(pgrep -f -- "vlm_server.py.*--port ${port}( |$)" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "sweep_kill_stragglers: found leftover vlm_server pid(s) on port ${port}: ${pids}" | tee -a "${LOG_DIR}/batch.log"
    while read -r p; do
      [[ "${p}" =~ ^[0-9]+$ ]] || continue
      kill_process_group "${p}"
    done <<< "${pids}"
  fi
}

# The conda wrapper may disappear while its VLM worker is re-parented to PID 1.
# Sweep by the unique port even when the tracked wrapper PID is already gone.
cleanup_batch_vlm() {
  local p
  [[ "${PORT:-}" =~ ^[0-9]+$ ]] || return 0
  while read -r p; do
    [[ "${p}" =~ ^[0-9]+$ ]] || continue
    kill_process_group "${p}"
  done < <(pgrep -f -- "vlm_server.py.*--port ${PORT}( |$)" 2>/dev/null || true)
}

trap 'cleanup_batch_vlm' EXIT
trap 'cleanup_batch_vlm; exit 143' INT TERM

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
      [[ "${pid}" =~ ^[0-9]+$ ]] && kill_process_group "${pid}"
    done <<< "${pids}"
    cleanup_batch_vlm
    sleep 2
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

summary_has_episode() {
  local ep_idx="$1"
  awk -F '\t' -v wanted="${ep_idx}" 'NR > 1 && $1 == wanted { found=1 } END { exit !found }' "${SUMMARY}"
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
  if summary_has_episode "${ep_idx}"; then
    echo "Skipping episode ${ep_idx}; already has a terminal summary row" | tee -a "${LOG_DIR}/batch.log"
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
        env TERM=xterm OMNI_KIT_ACCEPT_EULA=YES DISPLAY="${ISAAC_DISPLAY:-:99}" "${CONDA}" run \
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

      # Stall watchdog: kill as soon as eval_log stops growing for
      # EPISODE_STALL_SECONDS, instead of waiting out the full
      # EPISODE_TIMEOUT_SECONDS wall-clock cap for a process that's silently
      # spinning (not blocked -- observed ~100%+ CPU during the 2026-07-31
      # ep4 stall, so it isn't a driver-level hang, just a dead-end loop).
      (
        last_size=-1
        stall_elapsed=0
        while kill -0 "${eval_pid}" 2>/dev/null; do
          sleep "${STALL_CHECK_INTERVAL_SECONDS}"
          cur_size="$(stat -c %s "${eval_log}" 2>/dev/null || echo -1)"
          if [[ "${cur_size}" == "${last_size}" ]]; then
            stall_elapsed=$((stall_elapsed + STALL_CHECK_INTERVAL_SECONDS))
          else
            stall_elapsed=0
            last_size="${cur_size}"
          fi
          if (( stall_elapsed >= EPISODE_STALL_SECONDS )); then
            echo "Episode ${ep_idx} stalled: no eval_log growth for ${EPISODE_STALL_SECONDS}s; killing early instead of waiting for EPISODE_TIMEOUT_SECONDS." | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
            kill_process_group "${eval_pid}"
            sweep_kill_stragglers "${ep_idx}" "${suffix}" "${PORT}"
            break
          fi
        done
      ) &
      watchdog_pid="$!"

      wait "${eval_pid}"
      exit_code="$?"
      kill "${watchdog_pid}" 2>/dev/null || true
      wait "${watchdog_pid}" 2>/dev/null || true
      kill_process_group "${eval_pid}"
      sweep_kill_stragglers "${ep_idx}" "${suffix}" "${PORT}"
      if [[ "${exit_code}" == "124" || "${exit_code}" == "137" ]]; then
        echo "Episode ${ep_idx} timed out after ${EPISODE_TIMEOUT_SECONDS}s; continuing to next episode." | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
      fi
    fi
  else
    exit_code=98
  fi

  kill_process_group "${eval_pid}"
  kill_process_group "${VLM_PID}"
  sweep_kill_stragglers "${ep_idx}" "${suffix}" "${PORT}"
  cleanup_batch_vlm
  wait_for_port_closed || echo "Warning: port ${PORT} still appears busy after episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log"
  sleep 15

  end_time="$(date -Is)"
  parsed="$(extract_measurement_summary "${suffix}")"
  # 2026-08-05: guard against a filesystem-write-completion race between the
  # episode process exiting and its measurement JSON becoming visible to the
  # glob above (confirmed real via ep1038 in line2_stopgate_redesign_30ep_20260804:
  # a genuine round_trip_success=true measurement file existed on disk but wasn't
  # picked up here, so the batch recorded a blank/lost row for an episode that
  # had actually succeeded). Retry briefly before accepting an empty result.
  measurement_retry=0
  while [[ -z "$(cut -f1 <<<"${parsed}")" && "${measurement_retry}" -lt 10 ]]; do
    sleep 2
    parsed="$(extract_measurement_summary "${suffix}")"
    measurement_retry=$((measurement_retry + 1))
  done
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


  # 2026-07-31 -- "reliable30v3" candidate list. Follow-up to unseen30v2 (17% yield)
  # and reliable100 (killed before completion -- ran out of time budget for a 100ep
  # batch). Per explicit user direction: getting the promotion/quarantine model to
  # Phase 3 (live enforcement) matters more right now than strict held-out/unseen
  # validation, and guaranteed yield of valid return-phase data matters more than
  # episode novelty. These 30 episode ids are NOT restricted to untrained/unseen --
  # they are the top 30 (by count, then ratio) episode_idx values across a scan of all
  # 159 historical batch_logs/*/summary.tsv files (277 distinct episode_idx) for having
  # a populated return_success field (i.e. the episode reliably reaches full return-phase
  # resolution rather than dying silently after 1 relocalization attempt or failing
  # instruction-rewrite at outbound start -- both open, unresolved failure modes).
  # Includes the 11 canonical "hard11" episodes (54-80% historical yield across ~40-68
  # runs each under many different configs) plus 19 more with 7-13 prior runs and
  # similarly high yield. Spans all 8 known-good scenes. 21/30 are NOT in
  # promotion_shadow_30ep_20260728's episode list (9 overlap), so this still adds new
  # sample volume even though it reuses historically-reliable (and likely
  # partially-trained) episodes rather than held-out ones.
  run_episode 4 8 x8F5xyUWy9e 354 583 0 0.000000 0.000000
  run_episode 5 9 x8F5xyUWy9e 354 583 0 0.000000 0.000000
  run_episode 89 129 EU6Fwq7SyZv 288 460 0 0.000000 0.000000
  run_episode 134 195 2azQ1b91cZZ 756 1288 0 0.000000 0.000000
  run_episode 187 281 EU6Fwq7SyZv 447 754 0 0.000000 0.000000
  run_episode 205 314 2azQ1b91cZZ 807 1372 0 0.000000 0.000000
  run_episode 268 422 QUCTc6BB5sX 435 739 0 0.000000 0.000000
  run_episode 295 476 zsNo4HB9uLZ 45 73 0 0.000000 0.000000
  run_episode 354 583 x8F5xyUWy9e 3 7 0 0.000000 0.000000
  run_episode 367 602 X7HyMhZNoso 1038 1759 0 0.000000 0.000000
  run_episode 368 603 X7HyMhZNoso 1038 1759 0 0.000000 0.000000
  run_episode 381 634 X7HyMhZNoso 342 562 0 0.000000 0.000000
  run_episode 408 682 oLBMNvg9in8 522 907 0 0.000000 0.000000
  run_episode 409 683 oLBMNvg9in8 522 907 0 0.000000 0.000000
  run_episode 420 712 zsNo4HB9uLZ 612 1069 0 0.000000 0.000000
  run_episode 430 722 2azQ1b91cZZ 318 511 0 0.000000 0.000000
  run_episode 488 843 QUCTc6BB5sX 834 1420 0 0.000000 0.000000
  run_episode 498 868 zsNo4HB9uLZ 222 352 0 0.000000 0.000000
  run_episode 500 870 zsNo4HB9uLZ 222 352 0 0.000000 0.000000
  run_episode 647 1119 x8F5xyUWy9e 354 583 0 0.000000 0.000000
  run_episode 671 1155 X7HyMhZNoso 681 1168 0 0.000000 0.000000
  run_episode 678 1165 zsNo4HB9uLZ 612 1069 0 0.000000 0.000000
  run_episode 680 1167 zsNo4HB9uLZ 612 1069 0 0.000000 0.000000
  run_episode 688 1178 X7HyMhZNoso 783 1336 0 0.000000 0.000000
  run_episode 708 1201 QUCTc6BB5sX 636 1105 0 0.000000 0.000000
  run_episode 974 1656 TbHJrupSAjP 615 1075 0 0.000000 0.000000
  run_episode 994 1700 QUCTc6BB5sX 105 151 0 0.000000 0.000000
  run_episode 1038 1759 X7HyMhZNoso 366 601 0 0.000000 0.000000
  run_episode 1040 1761 X7HyMhZNoso 366 601 0 0.000000 0.000000
  run_episode 1058 1791 TbHJrupSAjP 615 1075 0 0.000000 0.000000
  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
