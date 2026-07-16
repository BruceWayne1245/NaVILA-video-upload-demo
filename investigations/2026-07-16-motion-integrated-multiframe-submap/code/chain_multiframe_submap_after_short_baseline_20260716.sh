#!/usr/bin/env bash
set -u

CONFIDENCE_GATE_LOG="/home/teambruce/run_22ep_current_confidence_gate_20260716_master.log"
SHORT_BASELINE_LOG="/home/teambruce/run_22ep_short_baseline_require_resolution_20260716_master.log"

echo "[chain] $(date -Is) waiting for shadow_current_confidence_gate_22ep_20260716 to finish..."
while ! grep -q "^\[master\] batch finished" "$CONFIDENCE_GATE_LOG" 2>/dev/null; do
    sleep 30
done
echo "[chain] $(date -Is) confidence-gate batch finished."

echo "[chain] $(date -Is) waiting for shadow_short_baseline_require_resolution_22ep_20260716 to finish..."
while ! grep -q "^\[master\] batch finished" "$SHORT_BASELINE_LOG" 2>/dev/null; do
    sleep 30
done
echo "[chain] $(date -Is) short-baseline batch finished, launching multiframe_submap batch now."

bash /home/teambruce/run_22ep_multiframe_submap_20260716.sh
