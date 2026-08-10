#!/usr/bin/env bash
set -u

# =====================================================================================
# 2026-08-10 -- GPU/kernel crash-precursor watchdog.
#
# Purpose: catch the EARLY WARNING SIGNS of the kind of full-machine kernel
# panic that killed pure_navila_baseline_100ep_20260810 at ep408 (14:25 BST) --
# not the panic itself (a watchdog running on the same box can't report once
# the kernel is actually frozen; network + this process die with it). Signals
# chosen are the ones observed in the ep408 postmortem:
#   - kernel: "Flip event timeout on head 0" (nvidia-drm) -- appeared right at
#     the start of the doomed boot, ~40min before the panic.
#   - "Not enough images received, padding." spamming the active eval log --
#     render/sensor pipeline degrading. (Checked against a low-noise baseline:
#     successful episodes show up to ~8 of these per 40-line window; 25+ is
#     the alert threshold.)
#   - kernel hung-task/soft-lockup/RCU-stall messages -- generic full-hang signs.
#
# NOT used as signals (calibrated out 2026-08-10, see inline note below):
# "corrupted data in primvar" and "GLFW initialization failed" -- these
# appear IDENTICALLY in every single episode's normal Kit startup/teardown
# (successful or not), so they carry zero discriminating power.
#   - nvidia-smi itself timing out -- direct evidence the GPU driver is wedged.
#   - a trivial `logger` call timing out -- evidence the whole box, not just
#     the GPU, is losing responsiveness (disk/journald I/O stalling).
#   - the batch's active eval log going stale (no growth) for too long.
#   - the batch's systemd unit dying unexpectedly.
#
# This script only detects and logs -- it does not kill/restart/reboot
# anything. A human (via Claude, watching this log through the Monitor tool)
# decides what to do about an alert.
# =====================================================================================

LOG_TAG="[watchdog]"
BATCH_DIR="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_navila_baseline_100ep_20260810"
BATCH_LOG="${BATCH_DIR}/batch.log"
UNIT="navila-pure-baseline-100ep-resume-20260810.service"
INTERVAL=30
HEARTBEAT_CYCLES=60      # 60 * 30s = 30min
ALERT_MIN_GAP_CYCLES=10  # don't repeat the same category more than once per 5min

log() { echo "[$(date -Is)] ${LOG_TAG} $1"; }

declare -A last_alert_cycle
should_alert() {
  local category="$1"
  local last="${last_alert_cycle[$category]:--999999}"
  if (( cycle - last >= ALERT_MIN_GAP_CYCLES )); then
    last_alert_cycle[$category]=${cycle}
    return 0
  fi
  return 1
}

last_kernel_check="$(date -Is)"
last_eval_log=""
last_eval_size=-1
stall_cycles=0
cycle=0
gpu_line=""

log "WATCHDOG-START monitoring GPU/kernel precursors + batch progress (interval=${INTERVAL}s, unit=${UNIT})"

while true; do
  cycle=$((cycle+1))
  now="$(date -Is)"

  # 1. Kernel-level GPU/hang precursor signals since last check.
  kmsg="$(journalctl -k --since "${last_kernel_check}" --no-pager 2>/dev/null)"
  last_kernel_check="${now}"
  hit="$(printf '%s\n' "${kmsg}" | grep -iE "flip event timeout|nvrm: xid|gpu has fallen off the bus|hung task|soft lockup|rcu_sched detected|nmi watchdog: bug" | tail -5)"
  if [[ -n "${hit}" ]]; then
    log "ALERT-CRITICAL kernel GPU/hang precursor: $(printf '%s' "${hit}" | tr '\n' '|')"
  fi

  # 2. Self-responsiveness probe: a trivial syscall-bound command should
  #    return almost instantly. If it can't within 5s, the box itself (not
  #    just the GPU) is losing responsiveness.
  if ! timeout 5 logger "navila_watchdog_ping_${cycle}" 2>/dev/null; then
    if should_alert selfresp; then
      log "ALERT-CRITICAL system barely responsive: 'logger' did not complete within 5s (cycle ${cycle})"
    fi
  fi

  # 3. GPU driver responsiveness via nvidia-smi.
  if ! gpu_line="$(timeout 8 nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader 2>&1)"; then
    if should_alert nvidiasmi; then
      log "ALERT-CRITICAL nvidia-smi unresponsive or errored: ${gpu_line}"
    fi
  fi

  # 4. Active episode's eval log: growing? any degradation strings?
  active_eval_log="$(ls -t "${BATCH_DIR}"/ep*_eval.log 2>/dev/null | head -1)"
  if [[ -n "${active_eval_log}" ]]; then
    cur_size="$(stat -c%s "${active_eval_log}" 2>/dev/null || echo -1)"
    if [[ "${active_eval_log}" == "${last_eval_log}" && "${cur_size}" == "${last_eval_size}" ]]; then
      stall_cycles=$((stall_cycles+1))
    else
      stall_cycles=0
    fi
    last_eval_log="${active_eval_log}"
    last_eval_size="${cur_size}"

    stall_seconds=$(( stall_cycles * INTERVAL ))
    if (( stall_seconds >= 1200 )); then
      if should_alert stall_critical; then
        log "ALERT-CRITICAL $(basename "${active_eval_log}") has not grown in ~$((stall_seconds/60))min -- episode may be stuck"
      fi
    elif (( stall_seconds >= 600 )); then
      if should_alert stall_warning; then
        log "ALERT-WARNING $(basename "${active_eval_log}") has not grown in ~$((stall_seconds/60))min"
      fi
    fi

    tail_lines="$(tail -n 40 "${active_eval_log}" 2>/dev/null)"
    padding_count="$(printf '%s\n' "${tail_lines}" | grep -c "Not enough images received, padding.")"
    if (( padding_count >= 25 )); then
      if should_alert padding; then
        log "ALERT-WARNING repeated 'Not enough images received, padding.' (${padding_count}/40 recent lines) in $(basename "${active_eval_log}") -- render/sensor pipeline may be degrading"
      fi
    fi
    # NOTE: "corrupted data in primvar" and "GLFW initialization failed" were
    # removed as signals on 2026-08-10 17:0x -- calibration against ep5/134/
    # 187/367/368 (all successful) showed BOTH appear identically in every
    # single episode's normal Kit startup/teardown (GLFW init "fails" once at
    # ~800ms and once at final shutdown; ~29 primvar warnings every time).
    # They are harmless headless-rendering boilerplate, not crash precursors.
  fi

  # 5. Is the resume batch's systemd unit still active? (one-shot, ends the watchdog)
  if ! systemctl --user is-active --quiet "${UNIT}" 2>/dev/null; then
    state="$(systemctl --user show "${UNIT}" -p ActiveState -p Result --value 2>/dev/null | tr '\n' ' ')"
    log "ALERT-CRITICAL batch systemd unit ${UNIT} is no longer active (state: ${state})"
    log "WATCHDOG-END stopping -- nothing left to watch"
    exit 0
  fi

  # 6. Periodic heartbeat -- proves the watchdog itself is still alive.
  if (( cycle % HEARTBEAT_CYCLES == 0 )); then
    cur_line="$(tail -1 "${BATCH_LOG}" 2>/dev/null)"
    log "HEARTBEAT cycle=${cycle} gpu=[${gpu_line:-n/a}] last_batch_line=[${cur_line}]"
  fi

  sleep "${INTERVAL}"
done
