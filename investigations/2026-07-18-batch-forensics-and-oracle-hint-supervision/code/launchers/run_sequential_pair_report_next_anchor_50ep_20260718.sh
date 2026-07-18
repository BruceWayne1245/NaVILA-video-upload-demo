#!/usr/bin/env bash
set -u

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

# 2026-07-18: the injected hint has always described the "current" role (the
# anchor most recently confirmed/promoted to -- a backward-looking "where you
# were last confirmed" signal), never "next" (the upcoming, unconfirmed
# candidate) -- despite the hint text's own "next-anchor vector" label
# implying otherwise. Confirmed on real ep367 data (shadow_hint_swap_50ep_
# 20260714): bearing frequently swings to +-150-179 deg mid-dwell between
# promotions -- i.e. the reported target is frequently BEHIND the robot. This
# is architecturally opposite --route_hint_source=oracle's
# direct_oracle_route_anchor_progress, which continuously looks ~1
# anchor-spacing AHEAD of the robot's true (privileged) position -- the two
# hint sources were never reporting analogous things despite an apparently
# shared "route anchor A{idx} is X m away" format.
#
# --sequential_pair_report_next_anchor switches hint generation to report
# next's own estimate instead, reusing next's EXISTING reliability machinery
# (quarantine, quarantine_next_quality, short_baseline_disambiguation's
# anchor_heading_reliable downgrade -- already feeds filter_std_m's hedged
# "position uncertain" fallback) rather than inventing new degradation logic.
# Does NOT touch the underlying (current, next) pair-tracking/promotion
# machinery at all -- only which role's estimate gets reported in the hint.
#
# Same base config as shadow_hint_swap_50ep_20260714_accumulated (the
# reference 14/22=63.6% baseline) plus only this one new flag -- isolated
# single-variable A/B, same 50-episode set.
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

# New (2026-07-18): report next's estimate in the hint instead of current's.
COMMON_EXTRA+=" --sequential_pair_report_next_anchor"

echo "[master] started $(date -Is)"
echo "[master] 50-episode shadow-driven navigation batch (route_hint_source=integrated), Variant-1 07-15 baseline code + --sequential_pair_report_next_anchor (report next, not current, in the injected hint)"
echo "[master] EXTRA_ISAAC_ARGS (accumulated) = ${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated"

RUN_TAG=sequential_pair_report_next_anchor_50ep_20260718_accumulated \
PORT_BASE=54321 \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA} --sequential_pair_anchor_geometry_source=accumulated" \
bash scripts/run_oracle_anchor_50ep_batch_20260714.sh

echo "[master] batch finished $(date -Is)"
