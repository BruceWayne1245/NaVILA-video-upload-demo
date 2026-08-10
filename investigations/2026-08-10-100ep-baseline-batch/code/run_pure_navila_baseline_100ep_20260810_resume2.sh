#!/usr/bin/env bash
set -u

# Second resume of pure_navila_baseline_100ep_20260810 -- NOT a crash this time.
# Paused intentionally after ep515 finished (18:24:24 BST 2026-08-10) so the
# user could use the GPU. 43/100 episodes done (original 6 + first resume's
# 37). ep281 had just started (VLM server barely up) when the pause happened
# and produced no summary row, so it's included in the remaining list below
# along with everything never attempted. Computed programmatically from
# scripts/run_pure_baseline_100ep_20260810.sh's full 100-ep order minus
# batch_logs/pure_navila_baseline_100ep_20260810/summary.tsv's completed rows
# -- see investigations/2026-08-10-100ep-baseline-batch/README.md for the
# full handoff context (why this run exists, the ep408 kernel-panic incident,
# the fix applied, how to check GPU availability before resuming).
#
# DO NOT launch this automatically -- only run it after the user has
# explicitly confirmed they're done using the GPU.

BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
cd "${BENCH}" || exit 99

RUN_TAG="pure_navila_baseline_100ep_20260810"
REMAINING="281 268 96 354 347 430 214 338 277 410 137 198 189 491 963 55 337 289 813 537 932 382 726 546 336 889 20 1004 178 783 162 467 653 88 136 1002 1035 669 1042 692 652 248 953 1001 696 1039 525 271 447 386 830 122 670 534 436 290 135"

echo "[master-resume2] pure NaVILA baseline (100ep) RESUME started $(date -Is)"
echo "[master-resume2] RUN_TAG=${RUN_TAG}"
echo "[master-resume2] remaining episodes (57): ${REMAINING}"

RUN_TAG="${RUN_TAG}" \
PORT_BASE=56321 \
ONLY_EPISODES="${REMAINING}" \
bash scripts/run_pure_baseline_100ep_20260810.sh

echo "[master-resume2] pure NaVILA baseline (100ep) RESUME finished $(date -Is)"
