#!/usr/bin/env bash
set -euo pipefail

UPSTREAM_UNIT="navila-promotion-shadow-30ep-queued-20260728.service"
UPSTREAM_MASTER="/home/teambruce/run_promotion_shadow_30ep_master_queued_20260728.sh"
UPSTREAM_DRIVER="/home/teambruce/run_promotion_shadow_30ep_20260728.sh"
UPSTREAM_LOG="/home/teambruce/run_promotion_shadow_30ep_master_queued_20260728.log"
UPSTREAM_BATCH_LOG="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/promotion_shadow_30ep_20260728/batch.log"
SHADOW_RUNNER="/home/teambruce/navila-anchor-terminal-training-data-20260729/runtime_shadow/run_prospective_shadow_5ep.sh"
QUEUE_LOG="/home/teambruce/navila-anchor-terminal-training-data-20260729/runtime_shadow/shadow5_queue.log"
MIN_FREE_GPU_MIB=12000

log() {
  echo "[$(date -Is)] $*" | tee -a "${QUEUE_LOG}"
}

upstream_running() {
  systemctl --user is-active --quiet "${UPSTREAM_UNIT}" \
    || pgrep -f "${UPSTREAM_MASTER}" >/dev/null 2>&1 \
    || pgrep -f "${UPSTREAM_DRIVER}" >/dev/null 2>&1
}

gpu_has_enough_free_memory() {
  local used total free
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)"
  total="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)"
  free=$((total - used))
  if (( free >= MIN_FREE_GPU_MIB )); then
    return 0
  fi
  log "GPU free memory ${free}MiB < required ${MIN_FREE_GPU_MIB}MiB"
  return 1
}

bash "${SHADOW_RUNNER}" --preflight-only >> "${QUEUE_LOG}" 2>&1
log "queue armed behind ${UPSTREAM_UNIT}"

ticks=0
while upstream_running || ! gpu_has_enough_free_memory; do
  if (( ticks % 20 == 0 )); then
    log "waiting for promotion-shadow 30ep and GPU release"
  fi
  ticks=$((ticks + 1))
  sleep 30
done

log "upstream process clear; entering 60s settle window"
sleep 60
if upstream_running || ! gpu_has_enough_free_memory; then
  log "FATAL upstream or GPU became busy during settle window"
  exit 2
fi
if ! grep -q "30ep promotion-shadow run FINISHED" "${UPSTREAM_LOG}"; then
  log "FATAL upstream master completion marker missing"
  exit 3
fi
if ! grep -q "Batch finished at" "${UPSTREAM_BATCH_LOG}"; then
  log "FATAL upstream batch completion marker missing"
  exit 4
fi

log "upstream completion validated; launching prospective learned-model shadow5"
exec bash "${SHADOW_RUNNER}"

