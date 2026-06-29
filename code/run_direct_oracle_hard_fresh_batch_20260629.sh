#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export RUN_TAG="${RUN_TAG:-direct_oracle_hard_fresh_20260629}"
export ROUTE_HINT_SOURCE="${ROUTE_HINT_SOURCE:-oracle}"
export ROUTE_RELOCALIZATION_BACKEND="${ROUTE_RELOCALIZATION_BACKEND:-none}"

exec "${SCRIPT_DIR}/run_oracle_anchor_hard_fresh_batch_20260629.sh" "$@"
