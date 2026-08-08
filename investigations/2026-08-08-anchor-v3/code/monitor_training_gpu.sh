#!/usr/bin/env bash
# Monitors the anchor_v3 baseline training process: liveness, CPU progress,
# and GPU memory (own usage + total free), to catch a repeat of the silent
# CUDA-OOM-style death seen on the first 2026-08-08 attempt (process vanished
# with no checkpoint, no OOM-killer log entry).

set -u

WORKSPACE="/home/teambruce/anchor-v3-20260808"
LOG="$WORKSPACE/reports/gpu_monitor.log"
CHECKPOINT="${1:-$WORKSPACE/reports/anchor_v3_baseline_checkpoint.pt}"
MATCH_PATTERN="tools/train_anchor_v3.py"
POLL_SECONDS=15
FREE_MEM_WARN_MIB=2048
FREE_MEM_CRIT_MIB=512

mkdir -p "$WORKSPACE/reports"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"
}

log "=== monitor started (poll=${POLL_SECONDS}s, warn<${FREE_MEM_WARN_MIB}MiB, crit<${FREE_MEM_CRIT_MIB}MiB free) ==="

last_seen_pid=""
last_checkpoint_size=""
had_process=0

while true; do
    pid=$(pgrep -f "$MATCH_PATTERN" | head -1)

    gpu_line=$(nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits 2>/dev/null)
    gpu_used=$(echo "$gpu_line" | awk -F', ' '{print $1}')
    gpu_free=$(echo "$gpu_line" | awk -F', ' '{print $2}')
    gpu_util=$(echo "$gpu_line" | awk -F', ' '{print $3}')

    if [ -n "$pid" ]; then
        had_process=1
        last_seen_pid="$pid"
        proc_mem=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null | awk -F', ' -v p="$pid" '$1==p{print $2}')
        cpu_stats=$(ps -o etimes=,time=,pcpu=,rss= -p "$pid" 2>/dev/null)

        log "OK pid=$pid gpu_self=${proc_mem:-0}MiB gpu_used=${gpu_used}MiB gpu_free=${gpu_free}MiB gpu_util=${gpu_util}% ps='${cpu_stats}'"

        if [ -n "$gpu_free" ] && [ "$gpu_free" -lt "$FREE_MEM_CRIT_MIB" ]; then
            log "CRITICAL: only ${gpu_free}MiB GPU free (<${FREE_MEM_CRIT_MIB}MiB) while training pid=$pid is alive -- imminent CUDA OOM risk"
        elif [ -n "$gpu_free" ] && [ "$gpu_free" -lt "$FREE_MEM_WARN_MIB" ]; then
            log "WARNING: ${gpu_free}MiB GPU free (<${FREE_MEM_WARN_MIB}MiB) while training pid=$pid is alive"
        fi
    else
        if [ "$had_process" -eq 1 ] && [ -n "$last_seen_pid" ]; then
            log "ALERT: training process (last pid=$last_seen_pid) is no longer running. gpu_used=${gpu_used}MiB gpu_free=${gpu_free}MiB gpu_util=${gpu_util}%"
            if [ -f "$CHECKPOINT" ]; then
                log "  checkpoint exists at $CHECKPOINT ($(stat -c '%s bytes, mtime %y' "$CHECKPOINT" 2>/dev/null)) -- looks like a clean finish or a mid-run save"
            else
                log "  no checkpoint file present -- process likely died before completing epoch 0 (crash, not clean finish)"
            fi
            log "=== monitor exiting: nothing left to watch ==="
            exit 0
        else
            log "WAITING: training process not found yet (pattern: $MATCH_PATTERN)"
        fi
    fi

    if [ -f "$CHECKPOINT" ]; then
        size=$(stat -c '%s' "$CHECKPOINT" 2>/dev/null)
        if [ "$size" != "$last_checkpoint_size" ]; then
            log "CHECKPOINT UPDATED: $CHECKPOINT now ${size} bytes"
            last_checkpoint_size="$size"
        fi
    fi

    sleep "$POLL_SECONDS"
done
