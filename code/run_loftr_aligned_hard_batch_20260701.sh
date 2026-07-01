#!/usr/bin/env bash
# Non-oracle aligned hard batch.
#
# This keeps the successful oracle control stack shape (confirm yaw alignment,
# stop gate, hint-action arbiter, route maps) but uses the real LoFTR+depth
# route-memory relocalizer and integrated/non-oracle route hint source.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export RUN_TAG="${RUN_TAG:-loftr_aligned_hard_20260701}"
export EXTRA_ISAAC_ARGS="${EXTRA_ISAAC_ARGS:-} \
  --route_memory \
  --route_hint_mode=compact \
  --route_hint_source=integrated \
  --route_relocalization_backend=loftr_depth \
  --route_relocalization_interval_updates=25 \
  --oracle_align_return_yaw_to_anchor_segment \
  --stop_gate \
  --stop_gate_r_in=3.0 \
  --stop_gate_r_out=3.0 \
  --topdown_route_map \
  --hint_action_arbiter"

exec "${SCRIPT_DIR}/run_no_hint_hard_fresh_batch_20260629.sh" "$@"
