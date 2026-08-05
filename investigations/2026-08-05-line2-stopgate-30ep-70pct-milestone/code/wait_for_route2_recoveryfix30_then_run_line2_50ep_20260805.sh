#!/usr/bin/env bash
set -euo pipefail
# 2026-08-05 -- queue worker: wait for Route2's currently-running
# anchor_v2_full_active_recoveryfix30_20260805_tail29 batch (driven by
# run_manifest_batch_driver.sh, pid confirmed live at launch time of this
# script) to reach a terminal state, then launch Route1's
# line2_50ep_historical_outbound_20260805 batch behind it. Modeled directly on
# 2026-08-04's wait_for_route2_semanticfix30_then_run_line2_stopgate_redesign_30ep_20260804.sh
# (this project's established GPU-sharing handoff pattern between the two
# routes), same structure, same episode/driver-liveness detection approach.
# Own dedicated lock file, own dedicated systemd unit name -- does not touch or
# reuse either route's own driver lock.

QUEUE_LOCK="${QUEUE_LOCK:-/tmp/navila-route2-recoveryfix30-to-line2-50ep-queue.lock}"
exec 7>"${QUEUE_LOCK}"
if ! flock -n 7; then
  echo "FATAL: another route2-recoveryfix30-to-line2-50ep queue worker is active" >&2
  exit 75
fi

ROUTE2_DIR="/home/teambruce/navila-route2-v11-core-20260801"
ROUTE2_DRIVER="${ROUTE2_DIR}/launch/run_manifest_batch_driver.sh"
ROUTE2_TAG="anchor_v2_full_active_recoveryfix30_20260805_tail29"
ROUTE2_LOG_DIR="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/${ROUTE2_TAG}"
ROUTE2_BATCH_LOG="${ROUTE2_LOG_DIR}/batch.log"
ROUTE2_SUMMARY="${ROUTE2_LOG_DIR}/summary.tsv"
ROUTE2_PORT_BASE=56000
# episode_idx list confirmed live from the running driver's own environment
# (/proc/<pid>/environ ONLY_EPISODES) at the time this queue worker was
# written -- kept in sync manually (not sourced from the manifest, to avoid
# this queue worker accidentally picking up a future edit to it mid-wait).
ROUTE2_EPISODES=(95 87 264 310 88 268 367 89 579 844 484 187 658 427 539 276 994 688 646 351 815 680 1040 888 961 5 214 962 500)
ROUTE2_LAST_EPISODE="${ROUTE2_EPISODES[-1]}"

ROUTE1_SCRIPT="/home/teambruce/run_line2_50ep_historical_outbound_20260805.sh"
ROUTE1_TAG="line2_50ep_historical_outbound_20260805"
QUEUE_ROOT="/home/teambruce/navila-route2-recoveryfix30-to-line2-50ep-queue-20260805"
POLL_SECONDS="${POLL_SECONDS:-30}"
# How many consecutive "driver looks dead" polls before treating it as real,
# not a one-off race (checked exactly between kill_process_group() and the
# next episode's fresh VLM server starting) -- same rationale as the prior
# queue scripts' own constant.
DEAD_CONFIRM_POLLS="${DEAD_CONFIRM_POLLS:-3}"
GPU_FREE_MIN_MIB="${GPU_FREE_MIN_MIB:-22000}"
GPU_WAIT_MAX_SECONDS="${GPU_WAIT_MAX_SECONDS:-1800}"

mkdir -p "${QUEUE_ROOT}"
exec > >(tee -a "${QUEUE_ROOT}/queue.log") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

# Driver process alive (covers every normal inter-episode gap for the SAME
# outer bash process running all remaining episodes; it only exits at true
# completion or a real crash). This is the ONLY signal the wait loop gates
# on, precisely so a routine gap between/within episodes can never be
# misread as "Route2 is done." NOTE: RUN_TAG is passed to
# run_manifest_batch_driver.sh via an exported env var, not a CLI argument,
# so it does not appear in `ps`/pgrep -f output at all (confirmed directly
# via /proc/<pid>/environ on 20260805). Matched on the driver script path
# alone instead; cross-checked against a live child eval process's own
# result_suffix=${ROUTE2_TAG}_ep<N> argument (which DOES carry the tag)
# purely as an extra sanity log, not a gate.
route2_driver_alive() {
  pgrep -f -- "${ROUTE2_DRIVER}" >/dev/null
}

# Orphaned eval/VLM processes left behind if the driver above already died
# (crash, OOM-kill, etc.) without reaching its own cleanup.
route2_orphans_present() {
  pgrep -f -- "scripts/round_trip_eval.py.*result_suffix=${ROUTE2_TAG}" >/dev/null && return 0
  local idx port
  for idx in "${ROUTE2_EPISODES[@]}"; do
    port=$((ROUTE2_PORT_BASE + idx))
    pgrep -f -- "vlm_server.py.*--port ${port}( |$)" >/dev/null && return 0
  done
  return 1
}

route2_reached_last_episode() {
  grep -q "starting episode ${ROUTE2_LAST_EPISODE} " "${ROUTE2_BATCH_LOG}" 2>/dev/null
}

route2_finished_cleanly() {
  grep -q "^Batch finished at " "${ROUTE2_BATCH_LOG}" 2>/dev/null
}

force_cleanup_route2_orphans() {
  log "forcing cleanup of leftover Route2 processes (suffix=${ROUTE2_TAG}, ports ${ROUTE2_PORT_BASE}+episode_idx)"
  local pids pid idx port
  pids="$(pgrep -f -- "scripts/round_trip_eval.py.*result_suffix=${ROUTE2_TAG}" 2>/dev/null || true)"
  for idx in "${ROUTE2_EPISODES[@]}"; do
    port=$((ROUTE2_PORT_BASE + idx))
    pids="${pids} $(pgrep -f -- "vlm_server.py.*--port ${port}( |$)" 2>/dev/null || true)"
  done
  pids="$(tr ' ' '\n' <<<"${pids}" | grep -E '^[0-9]+$' | sort -nu || true)"
  if [[ -z "${pids}" ]]; then
    log "no leftover Route2 processes found (already clean)"
    return 0
  fi
  log "leftover PIDs: $(tr '\n' ' ' <<<"${pids}")"
  for pid in ${pids}; do
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  done
  sleep 5
  for pid in ${pids}; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill -9 -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
    fi
  done
  sleep 2
  log "leftover-process cleanup pass complete"
}

log "waiting for Route2's ${ROUTE2_TAG} batch driver to exit (last cohort episode: ${ROUTE2_LAST_EPISODE})"
last_ep_seen=false
dead_polls=0
while true; do
  if route2_driver_alive; then
    dead_polls=0
    if ! ${last_ep_seen} && route2_reached_last_episode; then
      last_ep_seen=true
      log "driver has started its last cohort episode (${ROUTE2_LAST_EPISODE}); still alive, continuing to wait for it to exit"
    fi
    sleep "${POLL_SECONDS}"
    continue
  fi
  dead_polls=$((dead_polls + 1))
  log "driver process not detected (confirm poll ${dead_polls}/${DEAD_CONFIRM_POLLS})"
  if (( dead_polls < DEAD_CONFIRM_POLLS )); then
    sleep "${POLL_SECONDS}"
    continue
  fi
  break
done

if route2_finished_cleanly; then
  log "Route2's ${ROUTE2_TAG} batch finished cleanly (batch.log shows 'Batch finished at')"
else
  log "Route2's ${ROUTE2_TAG} batch driver exited WITHOUT a clean 'Batch finished at' marker" \
      "(last_episode_seen=${last_ep_seen}) -- treating this as 'did not end correctly'"
  force_cleanup_route2_orphans
fi

if route2_orphans_present; then
  log "orphans still present after cleanup pass -- one more attempt"
  force_cleanup_route2_orphans
fi

route1_is_active() {
  pgrep -f -- "${ROUTE1_SCRIPT}" >/dev/null
}

if route1_is_active; then
  log "Route1 ${ROUTE1_TAG} is already active; no duplicate launch"
  exit 0
fi

deadline=$((SECONDS + GPU_WAIT_MAX_SECONDS))
free_mib=0
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

log "Route2 ${ROUTE2_TAG} complete (summary rows: $(wc -l < "${ROUTE2_SUMMARY}" 2>/dev/null || echo 'n/a')) and GPU free=${free_mib}MiB; starting queued Route1 ${ROUTE1_TAG}"

exec bash "${ROUTE1_SCRIPT}"
