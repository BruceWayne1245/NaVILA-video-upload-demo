#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

# 2026-07-18: research-only oracle-supervision experiment. Same base config as
# shadow_hint_swap_50ep_20260714_accumulated (the run that produced the 14/22=63.6%
# reference baseline) -- Variant 1 (no fusion), bounded_evidence+alias_aware
# promotion, promotion_use_pre_closure_estimates, short_baseline_disambiguation
# (diagnostic-only), sequential_pair_quarantine trend mode -- deliberately WITHOUT
# any of the 2026-07-16 additions (current_confidence_ambiguity_gate,
# short_baseline_require_resolution, multiframe_submap), per the user's explicit
# request to isolate this experiment against the exact 07-15 baseline code path.
#
# New on top: --oracle_hint_supervision (suppresses the injected hint text, falling
# back to the existing hedged "position uncertain" wording, whenever Isaac's
# privileged ground-truth bearing to the target anchor disagrees with the reported
# hint by more than 10 deg) and --oracle_hint_action_supervision (separately blocks
# hint_action_arbiter's override execution whenever that same ground-truth bearing
# error exceeds 45 deg). Both flags are off by default elsewhere -- this is the
# first live use of either.
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

# Variant 1: no fusion at all (closure_check omitted, temporal smoothing off).
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing"

# New (2026-07-18): oracle-supervised hint / hint_action interception.
COMMON_EXTRA+=" --oracle_hint_supervision --oracle_hint_bearing_error_threshold_deg=10.0"
COMMON_EXTRA+=" --oracle_hint_action_supervision --oracle_hint_action_bearing_error_threshold_deg=45.0"

# Added later same day, per explicit user call: testing oracle-supervision on
# top of the old "reports current" hint has no analytical value now that
# current-vs-next is understood as a likely root cause of hint inaccuracy --
# stack --sequential_pair_report_next_anchor underneath it instead of testing
# oracle-supervision in isolation against the old baseline.
COMMON_EXTRA+=" --sequential_pair_report_next_anchor"

echo "[master] started $(date -Is)"
echo "[master] 50-episode shadow-driven navigation batch (route_hint_source=integrated), Variant-1 07-15 baseline code + --sequential_pair_report_next_anchor + oracle-supervised hint/hint_action interception (10 deg / 45 deg) on top of it"
echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"

RUN_TAG=oracle_hint_supervision_report_next_50ep_20260718_accumulated \
PORT_BASE=54321 \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
bash scripts/run_oracle_anchor_50ep_batch_20260714.sh

echo "[master] batch finished $(date -Is)"
