#!/usr/bin/env bash
set -euo pipefail

ROUTE1_UNITS="${ROUTE1_UNITS:-navila-promotion-shadow-unseen30-20260730.service navila-promotion-shadow-unseen30v2-20260730.service}"
RUNNER="/home/teambruce/navila-unified-shadow50-20260730/launch/run_unified_shadow50.sh"
QUEUE_ROOT="/home/teambruce/navila-unified-shadow50-20260730/runs/queued_after_route1_20260730"
POLL_SECONDS="${POLL_SECONDS:-30}"
GPU_FREE_MIN_MIB="${GPU_FREE_MIN_MIB:-12000}"
GPU_WAIT_MAX_SECONDS="${GPU_WAIT_MAX_SECONDS:-1800}"

mkdir -p "${QUEUE_ROOT}"
exec > >(tee -a "${QUEUE_ROOT}/queue.log") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

route1_is_active() {
  local unit
  for unit in ${ROUTE1_UNITS}; do
    if systemctl --user is-active --quiet "${unit}"; then
      return 0
    fi
  done
  if pgrep -f '/home/teambruce/run_promotion_shadow_unseen30[^ ]*_20260730\.sh' >/dev/null; then
    return 0
  fi
  if pgrep -f 'result_suffix=promotion_shadow_unseen30' >/dev/null; then
    return 0
  fi
  return 1
}

log "waiting for route1 units/processes=${ROUTE1_UNITS}"
while route1_is_active; do
  sleep "${POLL_SECONDS}"
done
log "all route1 units and matching processes are no longer active"

deadline=$((SECONDS + GPU_WAIT_MAX_SECONDS))
while true; do
  free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
  if (( free_mib >= GPU_FREE_MIN_MIB )); then
    break
  fi
  if (( SECONDS >= deadline )); then
    log "FATAL GPU did not become free: ${free_mib}MiB < ${GPU_FREE_MIN_MIB}MiB"
    exit 3
  fi
  log "waiting for GPU cleanup: free=${free_mib}MiB"
  sleep "${POLL_SECONDS}"
done

log "route1 complete and GPU free=${free_mib}MiB; starting Route2 unified50"
exec /bin/bash "${RUNNER}"
