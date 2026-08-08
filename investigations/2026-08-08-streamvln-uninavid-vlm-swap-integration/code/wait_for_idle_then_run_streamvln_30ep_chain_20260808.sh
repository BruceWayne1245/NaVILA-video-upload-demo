#!/usr/bin/env bash
# Fail-closed queue + chain: waits for GPU/no-active-navila, runs the
# StreamVLN hint_action 30ep batch (same episode list + config as the
# oracle_hint batch, plus --hint_action_arbiter -- this is the one that maps
# onto the 4.3%-intervention story), then automatically chains into the
# plain oracle_hint (no hint_action) 30ep batch on the same episode list.
# Never kills anything; only waits, so it can't collide with a NaVILA test
# the user starts/stops in the meantime.
set -euo pipefail

QUEUE_LOCK=/tmp/streamvln-30ep-chain-queue.lock
GPU_FREE_MIN_MIB=20000
GPU_WAIT_MAX_SECONDS=21600
POLL_SECONDS=30
QUEUE_ROOT=/home/teambruce/streamvln-30ep-chain-queue-20260808
DRIVER=/home/teambruce/run_streamvln_oracle_hint_30ep_20260808.sh

exec 9>"${QUEUE_LOCK}"
if ! flock -n 9; then
  echo "FATAL: another streamvln-30ep-chain queue worker is already active" >&2
  exit 75
fi

mkdir -p "${QUEUE_ROOT}"
exec > >(tee -a "${QUEUE_ROOT}/queue.log") 2>&1
log() { echo "[$(date -Is)] $*"; }

wait_for_idle() {
  local deadline=$((SECONDS + GPU_WAIT_MAX_SECONDS))
  while true; do
    local active_navila free_mib
    active_navila="$(systemctl --user list-units --all 2>/dev/null | grep 'navila.*running' | grep -vc 'navila-xvfb' || true)"
    free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
    if [[ "${active_navila}" == "0" && "${free_mib}" -ge "${GPU_FREE_MIN_MIB}" ]]; then
      return 0
    fi
    if (( SECONDS >= deadline )); then
      log "FATAL: still blocked after ${GPU_WAIT_MAX_SECONDS}s (active_navila=${active_navila}, free_mib=${free_mib})"
      return 3
    fi
    log "waiting: active_navila_services=${active_navila} gpu_free=${free_mib}MiB"
    sleep "${POLL_SECONDS}"
  done
}

log "=== stage 1: StreamVLN hint_action 30ep (the 4.3%-comparable run) ==="
wait_for_idle
log "clear to launch stage 1"
RUN_TAG=streamvln_hint_action_30ep_20260808 \
  PORT_BASE=61100 \
  EXTRA_ISAAC_ARGS="--hint_action_arbiter" \
  bash "${DRIVER}"
log "=== stage 1 finished ==="

log "=== stage 2: StreamVLN oracle_hint (no hint_action) 30ep ==="
wait_for_idle
log "clear to launch stage 2"
RUN_TAG=streamvln_oracle_hint_30ep_20260808 \
  PORT_BASE=59950 \
  bash "${DRIVER}"
log "=== stage 2 finished ==="

log "chain complete"
