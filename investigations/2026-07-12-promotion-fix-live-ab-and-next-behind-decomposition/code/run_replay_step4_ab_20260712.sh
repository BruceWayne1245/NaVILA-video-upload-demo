#!/bin/bash
# Two tracks, run independently: TRACK_A = current code (step 1+2+4),
# TRACK_B = pre-step4 snapshot (step 1+2 only). Same 10 available episodes
# (ep678 excluded -- its icp_replay_capture anchors.json is corrupted beyond
# repair, documented in investigations/2026-07-09-.../DATA.md), same config,
# same STRIDE. One process per episode (NOT further chunked -- see the
# worker script's own comment on why intra-episode chunking is wrong here).
EPISODES=(1040 187 367 368 4 408 5 680 994)

WORKER=/home/teambruce/replay_worker_step4_ab_20260712.py
LIVE_SCRIPTS=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts
SNAPSHOT_SCRIPTS=/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/2026-07-10-promotion-fix-live-ab-and-next-behind-decomposition/code

OUT_A=/home/teambruce/replay_results_with_step4_20260712
OUT_B=/home/teambruce/replay_results_without_step4_20260712
LOG_A=/home/teambruce/replay_with_step4_20260712_master.log
LOG_B=/home/teambruce/replay_without_step4_20260712_master.log

mkdir -p "$OUT_A" "$OUT_B"
> "$LOG_A"
> "$LOG_B"

echo "[master] TRACK_A (with step4) started $(date -Iseconds)" >> "$LOG_A"
for ep in "${EPISODES[@]}"; do
  python3 "$WORKER" "$ep" --scripts-dir "$LIVE_SCRIPTS" --out-dir "$OUT_A" >> "$LOG_A" 2>&1 &
done

echo "[master] TRACK_B (without step4, step1+2 only) started $(date -Iseconds)" >> "$LOG_B"
for ep in "${EPISODES[@]}"; do
  python3 "$WORKER" "$ep" --scripts-dir "$SNAPSHOT_SCRIPTS" --out-dir "$OUT_B" >> "$LOG_B" 2>&1 &
done

wait
echo "[master] TRACK_A all done $(date -Iseconds)" >> "$LOG_A"
echo "[master] TRACK_B all done $(date -Iseconds)" >> "$LOG_B"
echo "ALL_DONE $(date -Iseconds)" >> "$LOG_A"
echo "ALL_DONE $(date -Iseconds)" >> "$LOG_B"
