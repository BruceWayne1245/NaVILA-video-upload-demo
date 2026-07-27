#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725/experiments/2026-07-25-policy-v2-active-50ep/episodes.tsv"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
ROUTE1_MASTER_PID="${ROUTE1_MASTER_PID:-1824426}"
ROUTE1_MASTER_PATTERN="/home/teambruce/run_vision_disagreement_ab_50ep_master_20260726.sh"
ROUTE1_MASTER_LOG="/home/teambruce/run_vision_disagreement_ab_50ep_master_20260726.log"
DOWNGRADE_SUMMARY="${BENCH}/batch_logs/vision_disagreement_ab_50ep_20260726_downgrade/summary.tsv"
DIAGNOSTIC_SUMMARY="${BENCH}/batch_logs/vision_disagreement_ab_50ep_20260726_diagnostic/summary.tsv"
RUN_TAG="${RUN_TAG:-reliability_v11_route2_terminal_recovery_active50_20260727}"
PORT_BASE="${PORT_BASE:-64000}"
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"
QUEUE_LOG="${LOG_DIR}/queue.log"
MIN_FREE_GPU_MIB=12000
RUNNER_SHA="3bca3e9a1c99ce508d6f834f888136c0411c79dc765f3391b25d07912c4953ea"
HANDOFF_VALIDATOR_SHA="ed52bcdc28cfeceb29c5b9a250daef0e2524d40cb4c8500966c739843ad49811"

mkdir -p "${LOG_DIR}"

log() {
  printf '[queue] %s %s\n' "$(date -Is)" "$*" | tee -a "${QUEUE_LOG}"
}

require_sha() {
  local path="$1"
  local expected="$2"
  local actual
  actual="$(sha256sum "${path}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    log "FATAL: frozen artifact changed: ${path}; expected=${expected}; actual=${actual}"
    exit 21
  fi
}

master_is_original_process() {
  [[ "${ROUTE1_MASTER_PID}" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/${ROUTE1_MASTER_PID}/cmdline" ]] || return 1
  tr '\0' ' ' < "/proc/${ROUTE1_MASTER_PID}/cmdline" | grep -Fq "${ROUTE1_MASTER_PATTERN}"
}

route1_complete() {
  python3 "${HERE}/validate_route1_handoff.py" \
    --manifest "${MANIFEST}" \
    --summary "${DOWNGRADE_SUMMARY}" \
    --summary "${DIAGNOSTIC_SUMMARY}" >> "${QUEUE_LOG}" 2>&1 \
    && grep -Fq "Route1 vision_disagreement_mode A/B (50ep) FINISHED" "${ROUTE1_MASTER_LOG}"
}

gpu_free_mib() {
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1
}

gpu_consumers_clear() {
  ! pgrep -f "round_trip_eval.py" >/dev/null 2>&1 \
    && ! pgrep -f "vlm_server.py" >/dev/null 2>&1
}

require_sha "${HERE}/run_recovery_active50.sh" "${RUNNER_SHA}"
require_sha "${HERE}/validate_route1_handoff.py" "${HANDOFF_VALIDATOR_SHA}"
log "queued behind Route1 master pid=${ROUTE1_MASTER_PID}; target=${RUN_TAG}"
while master_is_original_process; do
  log "Route1 master still active; waiting"
  sleep 60
done

if ! route1_complete; then
  log "FATAL: Route1 master ended without both 50-episode arms reaching terminal summaries"
  exit 20
fi
log "Route1 completion artifacts validated: downgrade=50/50, diagnostic=50/50"

while true; do
  free="$(gpu_free_mib)"
  if gpu_consumers_clear && (( free >= MIN_FREE_GPU_MIB )); then
    log "GPU consumers clear and free=${free}MiB; entering 60s settle window"
    sleep 60
    free="$(gpu_free_mib)"
    if gpu_consumers_clear && (( free >= MIN_FREE_GPU_MIB )); then
      break
    fi
  else
    log "waiting for GPU handoff; free=${free}MiB"
  fi
  sleep 60
done

log "handoff confirmed; launching Route2 Active-50"
exec env RUN_TAG="${RUN_TAG}" PORT_BASE="${PORT_BASE}" \
  bash "${HERE}/run_recovery_active50.sh" >> "${QUEUE_LOG}" 2>&1
