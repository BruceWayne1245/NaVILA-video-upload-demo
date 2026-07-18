#!/usr/bin/env bash
set -u

MULTIFRAME_LOG="/home/teambruce/run_22ep_multiframe_submap_report_next_20260718_master.log"
NEXT_ANCHOR_LOG="/home/teambruce/run_sequential_pair_report_next_anchor_50ep_20260718_master.log"

echo "[chain] $(date -Is) starting stage 1/3: shadow_multiframe_submap_report_next_22ep_20260718 (restart of the killed shadow_multiframe_submap_22ep_20260716, with --sequential_pair_report_next_anchor added). Blocks here until it completes (synchronous, not backgrounded)."
bash /home/teambruce/run_22ep_multiframe_submap_report_next_20260718.sh > "${MULTIFRAME_LOG}" 2>&1
echo "[chain] $(date -Is) stage 1/3 finished."

echo "[chain] $(date -Is) starting stage 2/3: sequential_pair_report_next_anchor_50ep_20260718_accumulated (full 50ep, isolated single-variable A/B against the 14/22 baseline)."
bash /home/teambruce/run_sequential_pair_report_next_anchor_50ep_20260718.sh > "${NEXT_ANCHOR_LOG}" 2>&1
echo "[chain] $(date -Is) stage 2/3 finished."

echo "[chain] $(date -Is) starting stage 3/3: oracle_hint_supervision_report_next_50ep_20260718_accumulated (oracle-supervision stacked on top of report_next_anchor)."
bash /home/teambruce/run_oracle_hint_supervision_50ep_20260718.sh
echo "[chain] $(date -Is) stage 3/3 finished. All done."
