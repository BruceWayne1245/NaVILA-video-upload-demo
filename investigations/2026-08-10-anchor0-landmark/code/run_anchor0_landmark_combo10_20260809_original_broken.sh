#!/usr/bin/env bash
# Recovered from the 2026-08-09 session transcript (the scratchpad copy was
# wiped when the machine was rebooted). This is the launch command that
# produced the 2026-08-09 combo batch: 1 episode completed with ZERO
# landmark activity, the rest crashed within ~4 minutes with no output.
# Root cause found 2026-08-10: missing --route_memory_capture_start_anchor_descriptor
# (see ../ROOT_CAUSE_AND_FIX_20260810.md). Kept here for reference only --
# do not re-run as-is.
set -u

EPISODES=(386 4 88 367 5 95 680 1040 89 226)
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
EVAL_SCRIPT="/home/teambruce/navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py"
ISAAC_PY="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
VLM_PORT=59530
LOG_DIR="/tmp/claude-1006/-home-teambruce/0174017e-1c75-4a5f-9337-f53e58bd5bf4/scratchpad/anchorv3_combo_batch_logs"
mkdir -p "$LOG_DIR"

SUMMARY="$LOG_DIR/summary.tsv"
echo -e "episode_idx\texit_code\tshadow_lines\tshadow_failures\tlandmark_placed\tlandmark_recognized\tresult_dir" > "$SUMMARY"

for EP in "${EPISODES[@]}"; do
  SUFFIX="anchor_v3_combo_20260809_ep${EP}"
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
    --anchor_v3_shadow \
    --anchor_v3_shadow_self_driven \
    --anchor0_landmark_shadow \
    > "$LOG" 2>&1
  EXIT_CODE=$?

  RESULT_DIR="$BENCH/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_${SUFFIX}"
  SHADOW_JSONL="$RESULT_DIR/anchor_v3_shadow.jsonl"
  LANDMARK_JSONL="$RESULT_DIR/anchor0_landmark.jsonl"
  SHADOW_LINES=0
  [ -f "$SHADOW_JSONL" ] && SHADOW_LINES=$(wc -l < "$SHADOW_JSONL")
  SHADOW_FAILURES=$(grep -c "WARNING: shadow inference failed" "$LOG" 2>/dev/null || echo 0)
  LANDMARK_PLACED=$(grep -c '"event": "landmark_placed"' "$LANDMARK_JSONL" 2>/dev/null || echo 0)
  LANDMARK_RECOGNIZED=$(grep -c '"event": "landmark_recognized"' "$LANDMARK_JSONL" 2>/dev/null || echo 0)

  echo -e "${EP}\t${EXIT_CODE}\t${SHADOW_LINES}\t${SHADOW_FAILURES}\t${LANDMARK_PLACED}\t${LANDMARK_RECOGNIZED}\t${RESULT_DIR}" >> "$SUMMARY"
  echo "[$(date -Is)] finished episode ${EP}: exit=${EXIT_CODE} shadow_lines=${SHADOW_LINES} shadow_failures=${SHADOW_FAILURES} landmark_placed=${LANDMARK_PLACED} landmark_recognized=${LANDMARK_RECOGNIZED}" | tee -a "$LOG_DIR/batch.log"
done

echo "[$(date -Is)] BATCH COMPLETE" | tee -a "$LOG_DIR/batch.log"
