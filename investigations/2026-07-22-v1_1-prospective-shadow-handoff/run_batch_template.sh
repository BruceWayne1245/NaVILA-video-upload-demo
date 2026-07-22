#!/usr/bin/env bash
set -u

# HANDOFF TEMPLATE ONLY. It is not scheduled. The expected live-code hashes
# below describe the 2026-07-22 fix-ON A+B+C baseline and MUST be refreshed by
# Claude after his next controller changes are finalized. Do not delete the
# hash checks merely to make a changed tree pass preflight.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
BASE_DRIVER="${BENCH}/scripts/run_oracle_anchor_100ep_batch_20260720.sh"
MANIFEST="${HERE}/episodes.tsv"
ARTIFACT="/home/teambruce/navila-reliability-v1_1/artifacts/reliability_v1_1_development.pkl"
RUN_TAG="reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated"
CONTROLLER_LABEL="${CONTROLLER_LABEL:-REPLACE_WITH_CLAUDE_FINAL_CONTROLLER_LABEL}"
PORT_BASE=57000
ROUTE_HINT_SOURCE=integrated
ROUTE_RELOCALIZATION_BACKEND=sequential_pair
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1
EPISODE_TIMEOUT_SECONDS=7200
EPISODE_TIMEOUT_KILL_AFTER_SECONDS=300

EXPECTED_DRIVER_SHA="ef05eb8464170a801b0043f5bcef35b9c00601734d466c4c5d5523b50d8786d8"
EXPECTED_ROUND_TRIP_SHA="a9e42b5441f5a44592afc77a2f6979b3cbe138c2d8e6ea07f4c4887327a5bd70"
EXPECTED_AGENT_SHA="fe37b7117087ea5da19afec43cc44ed3de27a45ebd85ac3e13880140f9986022"
EXPECTED_RELOCALIZATION_SHA="226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1"
EXPECTED_STOP_GATE_SHA="0c37014abdc4bc4ad66bf23f167292c3b7ecc21c9a4f09c0d672888bb4f79d0b"
EXPECTED_ARTIFACT_SHA="5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce"
EXPECTED_MANIFEST_SHA="60d2adf33efeaeb985dc2b234a284a4698ff69160b2a284adfa0ed060b1c60c7"

CURRENT_100="4 5 134 187 367 368 408 678 680 994 1040 144 166 1008 1058 89 647 381 651 409 639 319 49 488 56 273 708 486 1068 498 974 640 1000 1038 500 1011 589 758 875 295 973 342 515 281 268 96 354 347 430 214 338 277 410 137 198 189 491 963 55 337 289 813 537 932 382 726 546 336 889 20 1004 178 783 162 467 653 88 136 1002 1035 669 1042 692 652 248 953 1001 696 1039 525 271 447 386 830 122 670 534 436 290 135"

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
COMMON_EXTRA+=" --sequential_pair_promotion_window=5 --sequential_pair_promotion_min_votes=3"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_aware --sequential_pair_promotion_alias_threshold=0.6"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_window=8 --sequential_pair_promotion_alias_min_votes=5"
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
# Claude's current A+B+C controller remains the sole controller. The V1.1 model is
# deliberately absent from this command and will be scored offline after capture.
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current"
COMMON_EXTRA+=" --sequential_pair_reliability_distrust_downstream"
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}"

sha_of() {
  sha256sum "$1" | awk '{print $1}'
}

require_sha() {
  local path="$1"
  local expected="$2"
  local actual
  actual="$(sha_of "${path}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "[preflight] FATAL SHA mismatch: ${path}" >&2
    echo "[preflight] expected=${expected} actual=${actual}" >&2
    return 1
  fi
}

preflight() {
  local count unique overlap scene_counts
  if [[ "${CONTROLLER_LABEL}" == "REPLACE_WITH_CLAUDE_FINAL_CONTROLLER_LABEL" ]]; then
    echo "[preflight] FATAL: Claude must set CONTROLLER_LABEL after finalizing the controller" >&2
    return 1
  fi
  require_sha "${BASE_DRIVER}" "${EXPECTED_DRIVER_SHA}" || return 1
  require_sha "${BENCH}/scripts/round_trip_eval.py" "${EXPECTED_ROUND_TRIP_SHA}" || return 1
  require_sha "${BENCH}/scripts/route_memory_agent.py" "${EXPECTED_AGENT_SHA}" || return 1
  require_sha "${BENCH}/scripts/relocalization.py" "${EXPECTED_RELOCALIZATION_SHA}" || return 1
  require_sha "${BENCH}/scripts/stop_gate.py" "${EXPECTED_STOP_GATE_SHA}" || return 1
  require_sha "${ARTIFACT}" "${EXPECTED_ARTIFACT_SHA}" || return 1
  require_sha "${MANIFEST}" "${EXPECTED_MANIFEST_SHA}" || return 1
  count="$(awk 'NR > 1 {count++} END {print count+0}' "${MANIFEST}")"
  unique="$(awk 'NR > 1 {print $1}' "${MANIFEST}" | sort -n | uniq | wc -l)"
  overlap="$(awk -v old=" ${CURRENT_100} " 'NR > 1 && index(old, " "$1" ") {print $1}' "${MANIFEST}")"
  if [[ "${count}" != "100" || "${unique}" != "100" || -n "${overlap}" ]]; then
    echo "[preflight] FATAL manifest count=${count}, unique=${unique}, overlap=${overlap:-none}" >&2
    return 1
  fi
  scene_counts="$(awk 'NR > 1 {n[$3]++} END {for (s in n) printf "%s=%d ",s,n[s]}' "${MANIFEST}" | xargs)"
  echo "[preflight] PASS: 100 unique fresh episodes; scenes: ${scene_counts}"
  echo "[preflight] PASS: frozen V1.1 artifact present but model enforcement/inference is OFF"
}

preflight || exit 2
if [[ "${1:-}" == "--preflight-only" ]]; then
  exit 0
fi

# Reuse the exact, pinned lifecycle and per-episode execution functions of the
# currently running batch, without executing its hard-coded episode list.
source <(sed '/^main()/,$d' "${BASE_DRIVER}")

mkdir -p "${LOG_DIR}"
cp "${MANIFEST}" "${LOG_DIR}/frozen_episode_manifest.tsv"
printf '%s\n' \
  "run_tag=${RUN_TAG}" \
  "controller=${CONTROLLER_LABEL}" \
  "reliability_v11_mode=offline_capture_shadow_no_inference_no_enforcement" \
  "artifact_sha256=${EXPECTED_ARTIFACT_SHA}" \
  "episode_manifest_sha256=${EXPECTED_MANIFEST_SHA}" \
  "driver_sha256=${EXPECTED_DRIVER_SHA}" \
  "round_trip_eval_sha256=${EXPECTED_ROUND_TRIP_SHA}" \
  "route_memory_agent_sha256=${EXPECTED_AGENT_SHA}" \
  "relocalization_sha256=${EXPECTED_RELOCALIZATION_SHA}" \
  "stop_gate_sha256=${EXPECTED_STOP_GATE_SHA}" \
  "started=$(date -Is)" > "${LOG_DIR}/run_provenance.txt"

echo "[master] V1.1 prospective capture shadow 100ep started $(date -Is)"
echo "[master] RUN_TAG=${RUN_TAG}"
echo "[master] controller=${CONTROLLER_LABEL}; V1.1 inference=OFF; enforcement=OFF"
echo "[master] manifest=${MANIFEST}"

while IFS=$'\t' read -r ep_idx ep_id scene neighbor_idx neighbor_ep_id matched mean_distance baseline_distance; do
  [[ "${ep_idx}" == "episode_idx" ]] && continue
  if awk -F $'\t' -v ep="${ep_idx}" \
      'NR > 1 && $1 == ep && $12 != 98 {found=1} END {exit !found}' "${SUMMARY}"; then
    echo "[master] resume-skip completed episode ${ep_idx}"
    continue
  fi
  attempts="$(awk -F $'\t' -v ep="${ep_idx}" 'NR > 1 && $1 == ep {n++} END {print n+0}' "${SUMMARY}")"
  while (( attempts < 2 )); do
    run_episode "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
      "${matched}" "${mean_distance}" "${baseline_distance}"
    attempts=$((attempts + 1))
    latest_exit="$(awk -F $'\t' -v ep="${ep_idx}" '$1 == ep {code=$12} END {print code}' "${SUMMARY}")"
    [[ "${latest_exit}" != "98" ]] && break
    if (( attempts < 2 )); then
      echo "[master] episode ${ep_idx} had VLM-start exit 98; one predeclared retry after 120s"
      sleep 120
    fi
  done
done < "${MANIFEST}"

printf 'finished=%s\n' "$(date -Is)" >> "${LOG_DIR}/run_provenance.txt"
echo "[master] V1.1 prospective capture shadow 100ep finished $(date -Is)"
