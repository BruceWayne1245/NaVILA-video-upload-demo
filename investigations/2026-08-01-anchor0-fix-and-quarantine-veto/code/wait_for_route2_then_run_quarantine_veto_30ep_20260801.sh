#!/usr/bin/env bash
set -euo pipefail

# 2026-08-01 -- mirrors wait_for_unified50_then_run_active_promote_30ep_20260731.sh's
# pattern exactly, retargeted at today's currently-running Route2 job
# (navila-route2-anchorv2-terminal50-resume1-20260801.service, a 50ep batch,
# currently on batch49/ep678, GPU at ~22.6/24.5GiB used). Waits for that job
# to finish and the GPU to free, then launches
# run_promotion_quarantine_veto_30ep_20260801.sh (anchor0 fix +
# quarantine-veto smoke/data batch).

QUEUE_LOCK="${QUEUE_LOCK:-/tmp/navila-quarantine-veto-30ep-queue.lock}"
exec 7>"${QUEUE_LOCK}"
if ! flock -n 7; then
  echo "FATAL: another quarantine-veto-30ep queue worker is already running" >&2
  exit 75
fi

ROUTE2_MASTERS="${ROUTE2_MASTERS:-/home/teambruce/navila-route2-anchorv2-terminal50-20260801/launch/run_route2_anchorv2_terminal50.sh}"
ROUTE2_EVAL_PATTERN="${ROUTE2_EVAL_PATTERN:-navila-route2-anchorv2-terminal50-20260801/runtime_candidate/scripts/round_trip_eval.py}"
ROUTE2_UNIT="${ROUTE2_UNIT:-navila-route2-anchorv2-terminal50-resume1-20260801.service}"
RUNNER="/home/teambruce/run_promotion_quarantine_veto_30ep_20260801.sh"
QUEUE_ROOT="/home/teambruce/navila-quarantine-veto-30ep-queue-20260801"
POLL_SECONDS="${POLL_SECONDS:-30}"
GPU_FREE_MIN_MIB="${GPU_FREE_MIN_MIB:-22000}"
GPU_WAIT_MAX_SECONDS="${GPU_WAIT_MAX_SECONDS:-1800}"

mkdir -p "${QUEUE_ROOT}"
exec > >(tee -a "${QUEUE_ROOT}/queue.log") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

route2_is_active() {
  if systemctl --user is-active --quiet "${ROUTE2_UNIT}" 2>/dev/null; then
    return 0
  fi
  local master
  for master in ${ROUTE2_MASTERS}; do
    if pgrep -f -- "${master}" >/dev/null; then
      return 0
    fi
  done
  # Belt-and-suspenders fallback for the window between the unit/master
  # exiting and a straggler eval process fully winding down.
  if pgrep -f -- "${ROUTE2_EVAL_PATTERN}" >/dev/null; then
    return 0
  fi
  return 1
}

log "waiting for Route2 (unit=${ROUTE2_UNIT}, masters=${ROUTE2_MASTERS})"
while route2_is_active; do
  sleep "${POLL_SECONDS}"
done
log "Route2 (unit + masters + eval pattern) no longer active"

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

log "Route2 complete and GPU free=${free_mib}MiB; starting quarantine-veto 30ep batch"
exec /bin/bash "${RUNNER}"
