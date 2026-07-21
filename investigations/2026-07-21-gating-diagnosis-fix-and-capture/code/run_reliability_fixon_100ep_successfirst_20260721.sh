#!/usr/bin/env bash
set -u

# =====================================================================================
# 2026-07-21 — fix-ON 100ep run (Injection A+B+C), SUCCESS-FIRST ordering.
#
# Decision (2026-07-21): run only the fix-ON arm over the full 100 episodes now; decide
# whether/which episodes to run fix-OFF later, from these results. Rationale: VLM
# non-determinism is large, so restricting to the ~21 known-affected episodes could yield
# far fewer than 21 outbound-successes; the full 100 gives a proper outbound-success
# sample. batch2 (canonical_report_next_stopgate_100ep_20260720) already exists as a
# fix-OFF reference for the same episodes/config.
#
# ORDERING: batch2's 27 outbound-success episodes run FIRST, the other 73 last. So if the
# run is interrupted overnight, the ~27 episodes that actually reach the return phase (the
# only ones the fix can affect) are already done and analysable in the morning.
#
# Implemented as two back-to-back invocations of the SAME driver with the SAME RUN_TAG
# (phase 1 = success set, phase 2 = the rest) -- the driver is used byte-for-byte, only
# ONLY_EPISODES differs. Config is identical to run_reliability_ab_100ep_20260721.sh ARM 2
# (fix ON, capture on).
#
# Detach: nohup bash run_reliability_fixon_100ep_successfirst_20260721.sh \
#           > run_reliability_fixon_100ep_successfirst_20260721_master.log 2>&1 &
# =====================================================================================

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

# batch2 outbound-success (27) -- from scratch_inv/an/paths.py OUTBOUND_SUCCESS
SUCCESS_LIST="4 5 20 88 89 189 268 277 295 319 367 368 382 491 498 500 537 589 647 653 669 680 783 813 889 994 1038"
# full 100-episode set, exactly as the driver iterates it
FULL_LIST="4 5 134 187 367 368 408 678 680 994 1040 144 166 1008 1058 89 647 381 651 409 639 319 49 488 56 273 708 486 1068 498 974 640 1000 1038 500 1011 589 758 875 295 973 342 515 281 268 96 354 347 430 214 338 277 410 137 198 189 491 963 55 337 289 813 537 932 382 726 546 336 889 20 1004 178 783 162 467 653 88 136 1002 1035 669 1042 692 652 248 953 1001 696 1039 525 271 447 386 830 122 670 534 436 290 135"

# REST = FULL - SUCCESS (computed, not hand-listed, so it can't drift from the driver list)
REST_LIST=""
for e in ${FULL_LIST}; do
  if [[ " ${SUCCESS_LIST} " != *" ${e} "* ]]; then REST_LIST+="${e} "; fi
done
REST_LIST="$(echo ${REST_LIST})"  # trim

# sanity: 27 + rest must equal 100, and the two sets must be disjoint & cover FULL
n_succ=$(echo ${SUCCESS_LIST} | wc -w); n_rest=$(echo ${REST_LIST} | wc -w); n_full=$(echo ${FULL_LIST} | wc -w)
echo "[master] counts: success=${n_succ} rest=${n_rest} full=${n_full}"
if [[ $((n_succ + n_rest)) -ne ${n_full} ]]; then
  echo "[master] FATAL: success+rest != full ($((n_succ+n_rest)) vs ${n_full}) -- aborting"; exit 2
fi

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
COMMON_EXTRA+=" --capture_icp_replay_dataset"
# the fix (A+B+C)
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current"
COMMON_EXTRA+=" --sequential_pair_reliability_distrust_downstream"

RUN_TAG="reliability_fixon_100ep_20260721_accumulated"

run_phase () {
  local phase="$1"; local eps="$2"
  echo "[master] ===== phase ${phase} start $(date -Is) ($(echo ${eps} | wc -w) episodes) ====="
  RUN_TAG="${RUN_TAG}" \
  PORT_BASE=55321 \
  ROUTE_HINT_SOURCE=integrated \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  ONLY_EPISODES="${eps}" \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
  bash scripts/run_oracle_anchor_100ep_batch_20260720.sh
  echo "[master] ===== phase ${phase} finished $(date -Is) ====="
}

echo "[master] fix-ON 100ep (success-first) started $(date -Is)"
echo "[master] RUN_TAG=${RUN_TAG}"
echo "[master] phase 1 (success, first): ${SUCCESS_LIST}"
echo "[master] phase 2 (rest, last):     ${REST_LIST}"
run_phase 1-success "${SUCCESS_LIST}"
run_phase 2-rest    "${REST_LIST}"
echo "[master] fix-ON 100ep finished $(date -Is)"
