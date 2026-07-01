#!/usr/bin/env bash
# Oracle-guided hard batch with non-oracle LoFTR shadow telemetry.
#
# VLM, stop gate, and hint-action arbiter receive oracle next-anchor hints.
# In parallel, RouteMemoryAgent still runs the LoFTR+depth relocalizer and logs
# route_memory_shadow / route_memory_alignment for judging non-oracle anchor,
# distance, and bearing quality against oracle.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export RUN_TAG="${RUN_TAG:-oracle_shadow_loftr_hard_20260701}"
export EXTRA_ISAAC_ARGS="${EXTRA_ISAAC_ARGS:-} \
  --route_memory \
  --route_hint_mode=compact \
  --route_hint_source=oracle \
  --route_relocalization_backend=loftr_depth \
  --route_relocalization_interval_updates=25 \
  --oracle_align_return_yaw_to_anchor_segment \
  --stop_gate \
  --stop_gate_r_in=3.0 \
  --stop_gate_r_out=3.0 \
  --topdown_route_map \
  --hint_action_arbiter"

exec "${SCRIPT_DIR}/run_no_hint_hard_fresh_batch_20260629.sh" "$@"
