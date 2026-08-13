#!/usr/bin/env bash
set -u
ROOT="/mnt/SSD4T/teambruce/projects/navila-isaac"
BENCH="${ROOT}/NaVILA-Bench"
ISAACLAB="${ROOT}/IsaacLab/isaaclab.sh"
CONDA="/home/teambruce/miniconda3/bin/conda"
VLM_ENV="/mnt/SSD4T/teambruce/conda_envs/navila-vlm"
ISAAC_ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
MODEL_PATH="${ROOT}/checkpoints/navila-llama3-8b-8f"
PORT=61005
SUFFIX="smoke_icp_yaw_align_ep5_20260813"
LOG_DIR="${BENCH}/batch_logs/${SUFFIX}"
mkdir -p "${LOG_DIR}"
VLM_LOG="${LOG_DIR}/vlm.log"
EVAL_LOG="${LOG_DIR}/eval.log"

cd "${BENCH}"
setsid "${CONDA}" run --prefix "${VLM_ENV}" python "${BENCH}/scripts/vlm_server.py" \
  --model_path "${MODEL_PATH}" --port "${PORT}" --load_8bit >> "${VLM_LOG}" 2>&1 &
VLM_PID=$!

deadline=$((SECONDS + 900))
while (( SECONDS < deadline )); do
  if ss -tln 2>/dev/null | grep -q ":${PORT} "; then break; fi
  sleep 2
done
echo "VLM ready pid=${VLM_PID}"

timeout --kill-after=300s 2400s env TERM=xterm OMNI_KIT_ACCEPT_EULA=YES "${CONDA}" run \
  --no-capture-output --prefix "${ISAAC_ENV}" "${ISAACLAB}" -p scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --vlm_port="${PORT}" --episode_idx=5 --result_suffix="${SUFFIX}" \
  --route_memory --route_hint_mode=compact \
  --route_hint_source=integrated --route_relocalization_backend=sequential_pair \
  --icp_align_return_yaw_to_anchor_segment \
  --route_relocalization_interval_updates=5 \
  --topdown_route_map --hint_action_arbiter \
  --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10 \
  --route_local_map_max_points=512 --route_local_map_profile=default \
  --route_local_map_quality_policy=diagnostic \
  >> "${EVAL_LOG}" 2>&1
EXIT_CODE=$?
echo "eval exit_code=${EXIT_CODE}"

kill -- -"${VLM_PID}" 2>/dev/null || kill "${VLM_PID}" 2>/dev/null || true
sleep 3
kill -9 -- -"${VLM_PID}" 2>/dev/null || true
echo "SMOKE_DONE exit_code=${EXIT_CODE}"
