#!/usr/bin/env bash
set -u

ROOT="/mnt/SSD4T/teambruce/projects/navila-isaac"
BENCH="${ROOT}/NaVILA-Bench"
ISAACLAB="${ROOT}/IsaacLab/isaaclab.sh"
CONDA="/home/teambruce/miniconda3/bin/conda"
ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
LOG_DIR="${BENCH}/batch_logs/loftr_depth_hard_batch_20260628"
SUMMARY="${LOG_DIR}/summary.tsv"

mkdir -p "${LOG_DIR}"

cat > "${SUMMARY}" <<'EOF'
episode_idx	episode_id	scene	neighbor_idx	neighbor_episode_id	matched_waypoints	mean_distance	start_time	end_time	exit_code	result_suffix	log_file
EOF

run_episode() {
  local ep_idx="$1"
  local ep_id="$2"
  local scene="$3"
  local neighbor_idx="$4"
  local neighbor_ep_id="$5"
  local matched="$6"
  local mean_distance="$7"
  local suffix="loftr_depth_hard_20260628_ep${ep_idx}"
  local log_file="${LOG_DIR}/ep${ep_idx}.log"
  local start_time
  local end_time
  local exit_code

  start_time="$(date -Is)"
  echo "[$start_time] starting episode ${ep_idx} (${scene})" | tee -a "${log_file}"

  cd "${BENCH}" || return 99
  TERM=xterm OMNI_KIT_ACCEPT_EULA=YES "${CONDA}" run \
    --prefix "${ENV}" \
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
    --episode_idx="${ep_idx}" \
    --result_suffix="${suffix}" \
    --route_memory \
    --route_hint_mode=compact \
    --route_relocalization_backend=loftr_depth \
    >> "${log_file}" 2>&1
  exit_code="$?"

  end_time="$(date -Is)"
  echo "[$end_time] finished episode ${ep_idx} exit_code=${exit_code}" | tee -a "${log_file}"
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
    "${matched}" "${mean_distance}" "${start_time}" "${end_time}" "${exit_code}" \
    "${suffix}" "${log_file}" >> "${SUMMARY}"
}

main() {
  echo "Batch started at $(date -Is)" | tee "${LOG_DIR}/batch.log"
  echo "Starting LoFTR route-memory hard episodes; assumes VLM server is listening on localhost:54321" | tee -a "${LOG_DIR}/batch.log"

  run_episode 4 8 x8F5xyUWy9e 354 583 5 0.000
  run_episode 5 9 x8F5xyUWy9e 354 583 5 0.000
  run_episode 134 195 2azQ1b91cZZ 756 1288 7 0.258
  run_episode 187 281 EU6Fwq7SyZv 447 754 6 0.433
  run_episode 367 602 X7HyMhZNoso 1038 1759 7 0.000
  run_episode 368 603 X7HyMhZNoso 1038 1759 7 0.000
  run_episode 408 682 oLBMNvg9in8 522 907 4 0.761
  run_episode 678 1165 zsNo4HB9uLZ 612 1069 7 0.000
  run_episode 680 1167 zsNo4HB9uLZ 612 1069 7 0.000
  run_episode 994 1700 QUCTc6BB5sX 105 151 7 0.000
  run_episode 1040 1761 X7HyMhZNoso 366 601 7 0.000

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
