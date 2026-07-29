#!/usr/bin/env bash
set -u
# 2026-07-28 -- waits for Route2's currently-running anchor_stop active50 job
# (run_anchor_stop_active50.sh, RUN_TAG=reliability_v11_anchor_stop_active50_20260728,
# just started at episode 1/50 -- could run many hours) to finish, then launches the
# promotion-controller shadow 30ep run (run_promotion_shadow_30ep_20260728.sh, already
# validated by the earlier 3ep smoke test: zero exceptions, live promote precision
# 88.3%/100%). Wait logic copied from run_vision_disagreement_ab_50ep_master_20260726.sh's
# wait_for_current_5ep_job (same project convention: process-name patterns + a GPU
# free-memory gate as a second, name-independent safety net, plus a settle window in
# case a "clear" reading is just the gap between two episodes of the SAME job).

MASTER_LOG="/home/teambruce/run_promotion_shadow_30ep_master_queued_20260728.log"
SHADOW_DRIVER="/home/teambruce/run_promotion_shadow_30ep_20260728.sh"

WAIT_PATTERNS=(
  "run_anchor_stop_active50.sh"
  "reliability_v11_anchor_stop_active50_20260728"
)
MIN_FREE_GPU_MIB=12000

log() {
  echo "[$(date -Is)] $*" | tee -a "${MASTER_LOG}"
}

any_wait_pattern_running() {
  local pat
  for pat in "${WAIT_PATTERNS[@]}"; do
    if pgrep -f "${pat}" > /dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

gpu_has_enough_free_memory() {
  local used total free
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  total=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
  free=$(( total - used ))
  if (( free >= MIN_FREE_GPU_MIB )); then
    return 0
  fi
  log "GPU free memory ${free}MiB < required ${MIN_FREE_GPU_MIB}MiB (used=${used}MiB/total=${total}MiB)."
  return 1
}

log "===== Waiting for Route2's anchor_stop_active50 job to finish before starting the 30ep promotion-shadow run ====="
ticks=0
while true; do
  while any_wait_pattern_running || ! gpu_has_enough_free_memory; do
    if (( ticks % 20 == 0 )); then
      log "Still waiting (Route2 process(es) still running, or GPU memory not yet free)... [$((ticks * 30 / 60)) min elapsed]"
    fi
    ticks=$((ticks + 1))
    sleep 30
  done
  log "No Route2 process matching any wait pattern detected, and GPU memory is free. Confirming with a 60s settle window..."
  sleep 60
  if ! any_wait_pattern_running && gpu_has_enough_free_memory; then
    log "Confirmed clear after 60s settle. Launching the 30ep promotion-shadow run."
    break
  fi
  log "Route2 process reappeared or GPU memory not free during the settle window (likely between episodes within the same batch) -- resuming wait."
done

bash "${SHADOW_DRIVER}" 2>&1 | tee -a "${MASTER_LOG}"
log "===== 30ep promotion-shadow run FINISHED ====="
