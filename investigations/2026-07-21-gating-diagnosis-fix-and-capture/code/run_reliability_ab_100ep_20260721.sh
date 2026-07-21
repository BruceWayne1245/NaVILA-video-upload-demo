#!/usr/bin/env bash
set -u

# =====================================================================================
# 2026-07-21 — clean fix-OFF vs fix-ON 100ep A/B for the Injection A/B/C reliability fix.
#
# Runs the SAME 100-episode set twice, byte-identical config EXCEPT the three
# default-off reliability flags (the "fix"), with --capture_icp_replay_dataset ON in
# BOTH arms so the run also feeds the Route-2 scalar/point-cloud dataset. Because the
# capture is identical in both arms it shifts both arms' absolute numbers equally and
# does NOT confound the fix's return-rate delta.
#
#   ARM 1 (fix-OFF): the exact canonical_report_next_stopgate config (batch2) + capture.
#   ARM 2 (fix-ON):  ARM 1 + Injection A (reliability quarantine, threshold 2.5)
#                          + Injection B (demote bad current)
#                          + Injection C (stop_gate defer-not-veto on low reliability).
#
# The fix (A/B/C) was merged into live scripts on 2026-07-21 (backup:
# navila-gating-ab-v1/live_prelaunch_backup_*/ and .../upstream_snapshot/). All 308 unit
# tests pass; flags are off unless explicitly passed, so ARM 1 == canonical byte-behaviour.
#
# Runtime: ~20 min/episode (the 16ep capture run averaged 21 min) => ~35 h/arm, ~70 h
# total. Detach with:  nohup bash run_reliability_ab_100ep_20260721.sh \
#                        > run_reliability_ab_100ep_20260721_master.log 2>&1 &
# =====================================================================================

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

# --- byte-identical canonical config (from run_capture_reliability_16ep_20260721.sh) ---
COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter"
COMMON_EXTRA+=" --hint_arbiter_min_relocalization_confidence=0.90"
COMMON_EXTRA+=" --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend"
COMMON_EXTRA+=" --route_local_map_icp_objective=point_to_point"
COMMON_EXTRA+=" --route_local_map_voxel_size_m=0.10"
COMMON_EXTRA+=" --route_local_map_max_points=512"
COMMON_EXTRA+=" --route_local_map_profile=default"
COMMON_EXTRA+=" --route_local_map_quality_policy=diagnostic"
COMMON_EXTRA+=" --sequential_pair_promotion_mode=bounded_evidence"
COMMON_EXTRA+=" --sequential_pair_promotion_window=5"
COMMON_EXTRA+=" --sequential_pair_promotion_min_votes=3"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_aware"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_threshold=0.6"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_window=8"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_min_votes=5"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_stall_attempts=200"
COMMON_EXTRA+=" --sequential_pair_promotion_use_pre_closure_estimates"
COMMON_EXTRA+=" --sequential_pair_short_baseline_disambiguation"
COMMON_EXTRA+=" --sequential_pair_short_baseline_min_travel_m=0.3"
COMMON_EXTRA+=" --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"
COMMON_EXTRA+=" --sequential_pair_closure_check"
COMMON_EXTRA+=" --sequential_pair_closure_reconciliation_signal=bearing"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor_suppress_if_stale"
COMMON_EXTRA+=" --stop_gate_anchor_corroboration --stop_gate_forced_anchor_confirm_steps=2"
COMMON_EXTRA+=" --sequential_pair_anchor_geometry_source=accumulated"
# capture ON in BOTH arms (Route-2 dataset; identical => does not confound the delta)
COMMON_EXTRA+=" --capture_icp_replay_dataset"

# the fix (ARM 2 only): Injection A + B + C. Threshold 2.5 is the calibrated default;
# passed explicitly for reproducibility.
FIX_ARGS="--sequential_pair_reliability_quarantine"
FIX_ARGS+=" --reliability_quarantine_threshold=2.5"
FIX_ARGS+=" --sequential_pair_reliability_demote_current"
FIX_ARGS+=" --sequential_pair_reliability_distrust_downstream"

run_arm () {
  local tag="$1"; local port_base="$2"; local extra="$3"
  echo "[master] ===== ARM ${tag} start $(date -Is) ====="
  echo "[master] EXTRA_ISAAC_ARGS = ${extra}"
  RUN_TAG="${tag}" \
  PORT_BASE="${port_base}" \
  ROUTE_HINT_SOURCE=integrated \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  EXTRA_ISAAC_ARGS="${extra}" \
  bash scripts/run_oracle_anchor_100ep_batch_20260720.sh
  echo "[master] ===== ARM ${tag} finished $(date -Is) ====="
}

echo "[master] reliability A/B started $(date -Is)"
# ARM 1 — fix OFF (canonical byte-behaviour + capture)
run_arm "reliability_ab_fixoff_100ep_20260721_accumulated" 54321 "${COMMON_EXTRA}"
# ARM 2 — fix ON (A+B+C)
run_arm "reliability_ab_fixon_100ep_20260721_accumulated"  55321 "${COMMON_EXTRA} ${FIX_ARGS}"
echo "[master] reliability A/B finished $(date -Is)"
