#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export RUN_TAG="${RUN_TAG:-direct_oracle_return_failures_fresh_20260629}"
export ONLY_EPISODES="${ONLY_EPISODES:-5 187 367 408 994}"

exec "${SCRIPT_DIR}/run_direct_oracle_hard_fresh_batch_20260629.sh" "$@"
