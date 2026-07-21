#!/usr/bin/env bash
set -u

# 2026-07-21: re-run the 16 episodes that motivate the Injection A/B reliability
# fix (13 permanently-pinned + 8 stop-decision "reached home but failed";
# union = 16, overlap ep5/20/498/680/889) with --capture_icp_replay_dataset ON,
# so the raw anchor + per-return-step point clouds get saved.
#
# Purpose (investigations/2026-07-21-icp-reliability-signal): the offline replay
# could NOT answer whether un-sticking the pin would let `current` follow home,
# because the pinned tracker never READ the below-pin anchors -- that data was
# never collected. The capture lets an offline pass re-run ICP of ANY anchor
# against the current cloud at ANY return step (independent of what the live
# tracker chose), so we can measure the registrability of the below-pin anchors
# along the ACTUAL trajectory the robot took, without needing the trajectory to
# change. This decides Route 1 (fix reachable) vs the vision/mapping wall.
#
# Config is BYTE-IDENTICAL to canonical_report_next_stopgate_100ep_20260720
# (fix OFF -- the reliability quarantine is not enabled here; we are reproducing
# the pinned runs and collecting clouds, not testing the fix end-to-end). The
# only additions are --capture_icp_replay_dataset and ONLY_EPISODES.

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

# --- byte-identical canonical config (copied from run_canonical_report_next_stopgate_100ep_20260720.sh) ---
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
# --- the only additions ---
COMMON_EXTRA+=" --capture_icp_replay_dataset"

# 13 pinned {5,20,319,367,498,500,669,680,813,889,994,1038,653}
#  + 8 stop-decision {5,20,89,382,498,537,680,889}  ==> union of 16
ONLY_EPISODES_LIST="5 20 89 319 367 382 498 500 537 653 669 680 813 889 994 1038"

echo "[master] capture re-run started $(date -Is)"
echo "[master] episodes (16): ${ONLY_EPISODES_LIST}"
echo "[master] EXTRA_ISAAC_ARGS = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"

RUN_TAG=capture_reliability_16ep_20260721_accumulated \
PORT_BASE=54321 \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
ONLY_EPISODES="${ONLY_EPISODES_LIST}" \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
bash scripts/run_oracle_anchor_100ep_batch_20260720.sh

echo "[master] capture re-run finished $(date -Is)"
