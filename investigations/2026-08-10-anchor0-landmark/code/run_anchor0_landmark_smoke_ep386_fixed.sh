#!/usr/bin/env bash
set -u

EP=386
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
EVAL_SCRIPT="/home/teambruce/navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py"
ISAAC_PY="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
VLM_PORT=59530
LOG_DIR="/tmp/claude-1006/-home-teambruce/50ef6f13-919e-4e18-a650-88a9f95ef8a2/scratchpad/anchor0_landmark_smoke_logs"
mkdir -p "$LOG_DIR"

SUFFIX="anchor0_landmark_fixed_smoke_20260810_ep${EP}"
LOG="$LOG_DIR/ep${EP}.log"
echo "[$(date -Is)] starting episode ${EP}" | tee -a "$LOG_DIR/batch.log"
cd "$BENCH" || exit 99
env TERM=xterm PYTHONUNBUFFERED=1 OMNI_KIT_ACCEPT_EULA=YES timeout --kill-after=180s 2400s \
  "$ISAAC_PY" "$EVAL_SCRIPT" \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=phase_prompt \
  --instruction_rewriter_provider=cache_only \
  --vlm_port="$VLM_PORT" \
  --episode_idx="$EP" \
  --result_suffix="$SUFFIX" \
  --route_memory \
  --route_hint_mode=compact \
  --route_hint_source=integrated \
  --route_relocalization_backend=sequential_pair \
  --oracle_align_return_yaw_to_anchor_segment \
  --route_relocalization_interval_updates=5 \
  --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 \
  --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90 \
  --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10 \
  --route_local_map_max_points=512 --route_local_map_profile=default \
  --route_local_map_quality_policy=diagnostic \
  --low_level_policy_log_root="$BENCH/logs/rsl_rl" \
  --route_memory_capture_start_anchor_descriptor \
  --anchor_v3_shadow \
  --anchor_v3_shadow_self_driven \
  --anchor0_landmark_shadow \
  > "$LOG" 2>&1
EXIT_CODE=$?

RESULT_DIR="$BENCH/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_${SUFFIX}"
LANDMARK_JSONL="$RESULT_DIR/anchor0_landmark.jsonl"
LANDMARK_PLACED=$(grep -c '"event": "landmark_placed"' "$LANDMARK_JSONL" 2>/dev/null || echo 0)
LANDMARK_RECOGNIZED=$(grep -c '"event": "landmark_recognized"' "$LANDMARK_JSONL" 2>/dev/null || echo 0)
OUTBOUND_CHECKS=$(grep -c '"event": "outbound_check"' "$LANDMARK_JSONL" 2>/dev/null || echo 0)

echo "[$(date -Is)] finished episode ${EP}: exit=${EXIT_CODE} outbound_checks=${OUTBOUND_CHECKS} landmark_placed=${LANDMARK_PLACED} landmark_recognized=${LANDMARK_RECOGNIZED}" | tee -a "$LOG_DIR/batch.log"
echo "BATCH COMPLETE" | tee -a "$LOG_DIR/batch.log"
