#!/usr/bin/env bash
set -euo pipefail

# 2026-07-31 -- mirrors navila-unified-shadow50-20260730/launch/
# wait_for_route1_then_run_unified50.sh exactly, inverted: waits for the
# currently-running Route2 unified_shadow50_retry4 (49 fresh + ep670 canary,
# launched directly in session-4.scope, NOT under a systemd unit -- see
# route1_is_active()-style detection below, matched on its own lockfile-
# protected master script rather than a unit name) to finish, then GPU-frees,
# then launches the first live-enforcement (Phase 3, promote/wait only)
# 30ep batch: run_promotion_active_promote_30ep_20260731.sh. This doubles as
# the smoke test for the new --sequential_pair_promotion_model_active_promote
# code path (round_trip_eval.py/route_memory_agent.py/
# promotion_controller_runtime.py, all edited today, never run against a
# live Isaac Sim episode yet) -- if it's broken, it fails loud across up to
# 30 episodes overnight instead of quietly.

QUEUE_LOCK="${QUEUE_LOCK:-/tmp/navila-active-promote-30ep-queue.lock}"
exec 7>"${QUEUE_LOCK}"
if ! flock -n 7; then
  echo "FATAL: another active-promote-30ep queue worker is already running" >&2
  exit 75
fi

UNIFIED50_MASTERS="${UNIFIED50_MASTERS:-/home/teambruce/navila-unified-shadow50-20260730/launch/run_unified_shadow50.sh /home/teambruce/navila-unified-shadow50-20260730/launch/wait_for_route1_then_run_unified50.sh}"
UNIFIED50_EVAL_PATTERN="${UNIFIED50_EVAL_PATTERN:-navila-unified-shadow50-20260730/runtime_candidate/scripts/round_trip_eval.py}"
RUNNER="/home/teambruce/run_promotion_active_promote_30ep_20260731.sh"
QUEUE_ROOT="/home/teambruce/navila-active-promote-30ep-queue-20260731"
POLL_SECONDS="${POLL_SECONDS:-30}"
GPU_FREE_MIN_MIB="${GPU_FREE_MIN_MIB:-22000}"
GPU_WAIT_MAX_SECONDS="${GPU_WAIT_MAX_SECONDS:-1800}"

mkdir -p "${QUEUE_ROOT}"
exec > >(tee -a "${QUEUE_ROOT}/queue.log") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

unified50_is_active() {
  local master
  for master in ${UNIFIED50_MASTERS}; do
    if pgrep -f -- "${master}" >/dev/null; then
      return 0
    fi
  done
  # Episode processes disappear during normal between-episode VLM-server
  # restart -- the orchestrator/queue-watcher masters above are the durable
  # signal, this is a belt-and-suspenders fallback for the rare window where
  # both masters have already exited but a straggler eval process is still
  # winding down.
  if pgrep -f -- "${UNIFIED50_EVAL_PATTERN}" >/dev/null; then
    return 0
  fi
  return 1
}

log "waiting for unified_shadow50 masters=${UNIFIED50_MASTERS}"
while unified50_is_active; do
  sleep "${POLL_SECONDS}"
done
log "unified_shadow50 (masters + eval pattern) no longer active"

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

log "unified_shadow50 complete and GPU free=${free_mib}MiB; starting active-promote 30ep smoke batch"
exec /bin/bash "${RUNNER}"
