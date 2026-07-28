#!/usr/bin/env bash
set -u
set -o pipefail

ROUTE1_UNIT="navila-promotion-shadow-30ep-20260728.service"
ROUTE1_RUNNER="/home/teambruce/run_promotion_shadow_30ep_20260728.sh"
ROUTE1_RUNNER_SHA="b541226c775175866176794c47fad56338caea92a687783dcc06e6455016edfe"
ROUTE1_LOG_DIR="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/promotion_shadow_30ep_20260728"
ROUTE1_SUMMARY="${ROUTE1_LOG_DIR}/summary.tsv"
ROUTE1_BATCH_LOG="${ROUTE1_LOG_DIR}/batch.log"

NEXT_ROOT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728"
NEXT_RUNNER="${NEXT_ROOT}/experiments/2026-07-28-anchor-stop-active50/run_anchor_stop_active50.sh"
NEXT_RUNNER_SHA="cd4f5a4cea78b457a120daf664292f2c70157f78b65ac2e5604e558ea07d559d"
NEXT_POLICY="${NEXT_ROOT}/configs/v11_anchor_support_recovery_active_v1_active50_approved_20260728.json"
NEXT_POLICY_SHA="04bdfd8260525dac7ed03c63b1189378c3f2eb6ee78a4d36fab3b3ffd2c816f2"
NEXT_LOG_DIR="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_anchor_stop_active50_20260728"
QUEUE_LOG="${NEXT_LOG_DIR}/queue.log"

EXPECTED_EPISODES="669 490 671 5 1062 427 688 581 368 310 351 888 962 658 785 815 264 268 205 961 1038 539 367 88 784 579 646 844 366 647"
POLL_SECONDS=30
GPU_MIN_FREE_MIB=12000
GPU_STABLE_CHECKS=6
GPU_STABLE_INTERVAL_SECONDS=10

mkdir -p "${NEXT_LOG_DIR}"

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "${QUEUE_LOG}"
}

sha_of() {
  sha256sum "$1" | awk '{print $1}'
}

require_sha() {
  local path="$1"
  local expected="$2"
  local actual
  actual="$(sha_of "${path}")"
  if [[ "${actual}" != "${expected}" ]]; then
    log "FATAL hash mismatch path=${path} expected=${expected} actual=${actual}"
    return 1
  fi
}

route1_summary_is_complete() {
  python3 - "${ROUTE1_SUMMARY}" "${EXPECTED_EPISODES}" <<'PY'
import csv
import sys
from collections import Counter

summary_path, expected_text = sys.argv[1:]
expected = [int(value) for value in expected_text.split()]
with open(summary_path, newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
observed = [int(row["episode_idx"]) for row in rows]
counts = Counter(observed)
missing = sorted(set(expected) - set(observed))
extra = sorted(set(observed) - set(expected))
duplicates = sorted(ep for ep, count in counts.items() if count != 1)
if len(rows) != len(expected) or missing or extra or duplicates:
    print(
        f"rows={len(rows)} expected={len(expected)} "
        f"missing={missing} extra={extra} duplicates={duplicates}",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
}

navila_processes_present() {
  pgrep -f '[r]ound_trip_eval.py|scripts/[v]lm_server.py' >/dev/null 2>&1
}

gpu_is_stably_free() {
  local check free_mib
  for ((check = 1; check <= GPU_STABLE_CHECKS; check++)); do
    if navila_processes_present; then
      log "handoff wait ${check}/${GPU_STABLE_CHECKS}: evaluator/VLM still present"
      return 1
    fi
    free_mib="$(
      nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits \
        | awk 'NR == 1 {print int($1)}'
    )"
    if [[ -z "${free_mib}" ]] || (( free_mib < GPU_MIN_FREE_MIB )); then
      log "handoff wait ${check}/${GPU_STABLE_CHECKS}: gpu_free_mib=${free_mib:-unknown}"
      return 1
    fi
    log "handoff stability ${check}/${GPU_STABLE_CHECKS}: gpu_free_mib=${free_mib}"
    if (( check < GPU_STABLE_CHECKS )); then
      sleep "${GPU_STABLE_INTERVAL_SECONDS}"
    fi
  done
}

log "queue armed: ${ROUTE1_UNIT} -> ${NEXT_RUNNER}"
require_sha "${ROUTE1_RUNNER}" "${ROUTE1_RUNNER_SHA}" || exit 10
require_sha "${NEXT_RUNNER}" "${NEXT_RUNNER_SHA}" || exit 11
require_sha "${NEXT_POLICY}" "${NEXT_POLICY_SHA}" || exit 12

if ! bash "${NEXT_RUNNER}" --preflight-only >>"${QUEUE_LOG}" 2>&1; then
  log "FATAL downstream 50ep preflight failed while arming queue"
  exit 13
fi
log "downstream 50ep preflight passed"

while systemctl --user is-active --quiet "${ROUTE1_UNIT}"; do
  main_pid="$(
    systemctl --user show "${ROUTE1_UNIT}" -p MainPID --value 2>/dev/null \
      || true
  )"
  summary_rows="$(
    awk 'NR > 1 {count++} END {print count+0}' "${ROUTE1_SUMMARY}" \
      2>/dev/null || echo 0
  )"
  log "route1 active main_pid=${main_pid:-unknown} summary_rows=${summary_rows}"
  sleep "${POLL_SECONDS}"
done

route1_status="$(
  systemctl --user show "${ROUTE1_UNIT}" -p ExecMainStatus --value 2>/dev/null \
    || true
)"
log "route1 unit inactive exec_status=${route1_status:-unknown}; validating completion"

if [[ -n "${route1_status}" && "${route1_status}" != "0" ]]; then
  log "FATAL route1 did not exit cleanly; downstream 50ep will not start"
  exit 20
fi
if [[ ! -f "${ROUTE1_BATCH_LOG}" ]] \
    || ! grep -q '^Batch finished at ' "${ROUTE1_BATCH_LOG}"; then
  log "FATAL route1 final batch marker missing; downstream 50ep will not start"
  exit 21
fi
if [[ ! -f "${ROUTE1_SUMMARY}" ]] || ! route1_summary_is_complete >>"${QUEUE_LOG}" 2>&1; then
  log "FATAL route1 summary is not the exact completed 30ep set"
  exit 22
fi
log "route1 completion contract passed: exact 30ep summary and final marker"

while ! gpu_is_stably_free; do
  log "GPU/process handoff not stable yet; retrying in ${POLL_SECONDS}s"
  sleep "${POLL_SECONDS}"
done

require_sha "${NEXT_RUNNER}" "${NEXT_RUNNER_SHA}" || exit 30
require_sha "${NEXT_POLICY}" "${NEXT_POLICY_SHA}" || exit 31
if ! bash "${NEXT_RUNNER}" --preflight-only >>"${QUEUE_LOG}" 2>&1; then
  log "FATAL downstream 50ep preflight failed at handoff"
  exit 32
fi

log "handoff passed; starting frozen anchor/stop Active-50"
cd "${NEXT_ROOT}" || exit 33
exec /usr/bin/bash "${NEXT_RUNNER}"
