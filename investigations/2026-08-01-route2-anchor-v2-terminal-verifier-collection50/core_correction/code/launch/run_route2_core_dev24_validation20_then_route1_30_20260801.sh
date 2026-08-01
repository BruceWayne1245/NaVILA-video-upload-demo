#!/usr/bin/env bash
set -euo pipefail

# Route-2 replacement chain approved on 2026-08-01:
#   Core development24 -> locked validation20 -> existing Route-1 30ep.
# Each Route-2 cohort is a separate launcher invocation, manifest, run root,
# summary and completion marker. Any incomplete cohort stops the chain.

CORE_ROOT="/home/teambruce/navila-route2-v11-core-20260801"
CORE_LAUNCHER="${CORE_ROOT}/launch/run_route2_core_cohort.sh"
DEV_COMPLETED="${CORE_ROOT}/runs/route2_core_development_20260801/COMPLETED"
VALIDATION_COMPLETED="${CORE_ROOT}/runs/route2_core_locked_validation_20260801/COMPLETED"
ROUTE1_RUNNER="/home/teambruce/run_promotion_quarantine_veto_30ep_20260801.sh"
CHAIN_ROOT="/home/teambruce/navila-route2-core-chain-20260801"
POLL_SECONDS=15
GPU_FREE_MIN_MIB=22000
GPU_WAIT_MAX_SECONDS=1800

mkdir -p "${CHAIN_ROOT}"
exec > >(tee -a "${CHAIN_ROOT}/chain.log") 2>&1

log() { echo "[$(date -Is)] $*"; }

wait_for_gpu() {
  local deadline=$((SECONDS + GPU_WAIT_MAX_SECONDS))
  local free_mib
  while true; do
    free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
    if [[ "${free_mib}" =~ ^[0-9]+$ ]] && (( free_mib >= GPU_FREE_MIN_MIB )); then
      log "GPU available: ${free_mib} MiB free"
      return 0
    fi
    if (( SECONDS >= deadline )); then
      log "FATAL GPU did not become free: ${free_mib:-unknown} MiB"
      return 3
    fi
    log "waiting for GPU cleanup: ${free_mib:-unknown} MiB free"
    sleep "${POLL_SECONDS}"
  done
}

if pgrep -f '[r]ound_trip_eval.py' >/dev/null; then
  log "FATAL evaluator still active before replacement chain"
  exit 76
fi

wait_for_gpu
log "static preflight before development24"
/bin/bash "${CORE_LAUNCHER}"

if [[ ! -f "${DEV_COMPLETED}" ]]; then
  log "starting Route-2 Core development24"
  /bin/bash "${CORE_LAUNCHER}" --launch-development
else
  log "development24 already complete; reusing completion marker"
fi
[[ -f "${DEV_COMPLETED}" ]] || { log "FATAL development24 incomplete"; exit 2; }

wait_for_gpu
if [[ ! -f "${VALIDATION_COMPLETED}" ]]; then
  log "starting Route-2 Core locked validation20"
  /bin/bash "${CORE_LAUNCHER}" --launch-locked-validation
else
  log "locked validation20 already complete; reusing completion marker"
fi
[[ -f "${VALIDATION_COMPLETED}" ]] || { log "FATAL locked validation20 incomplete"; exit 2; }

wait_for_gpu
if pgrep -f '[r]ound_trip_eval.py' >/dev/null; then
  log "FATAL evaluator remained after locked validation20"
  exit 76
fi
log "both Route-2 Core cohorts complete; starting existing Route-1 30ep"
touch "${CHAIN_ROOT}/ROUTE1_STARTED"
exec /bin/bash "${ROUTE1_RUNNER}"
