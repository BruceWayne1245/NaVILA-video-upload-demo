#!/usr/bin/env bash
set -u
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_ROOT="/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
CANDIDATE_SCRIPTS="${WORK_ROOT}/policy_v2_live_candidate/scripts"
BASE_DRIVER="${HERE}/run_policy_v2_batch_driver.sh"
MANIFEST="${HERE}/episodes.tsv"
VALIDATOR="${HERE}/validate_completion.py"
EVAL_SCRIPT="${CANDIDATE_SCRIPTS}/round_trip_eval.py"
RUN_TAG="${RUN_TAG:-reliability_v11_policy_v2_active_50ep_outbound_top_20260725}"
CONTROLLER_LABEL="route1_ABC_trendbudget_stuckrecovery_plus_v11_policy_v2_active"
PORT_BASE="${PORT_BASE:-61000}"
RUN_ONLY_EPISODE="${RUN_ONLY_EPISODE:-}"
ROUTE_HINT_SOURCE=integrated
ROUTE_RELOCALIZATION_BACKEND=sequential_pair
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1
EPISODE_TIMEOUT_SECONDS=7200
EPISODE_TIMEOUT_KILL_AFTER_SECONDS=300

EXPECTED_DRIVER_SHA="540ed476cf203e90ff6d9a3851b8458a09fbca7c11e55ebe1cced962f41696c1"
EXPECTED_MANIFEST_SHA="5c31cf60c05e64f97e1842a5d9d36cf95484ac775f0b9a50bd3afc9b93dac957"
EXPECTED_VALIDATOR_SHA="3de8ac9343a0dda7ecdac37516ab168d9b07f8e621ec9fb346341b627731e4c2"
EXPECTED_ROUND_TRIP_SHA="437f35851d93e369b5573ce62140fac09ca93d2581b32d5fbde25dae43943551"
EXPECTED_AGENT_SHA="7120438c2bb44b3a3784a079e1c0f372af0dca265d1bcb3912a196e1c54cbc02"
EXPECTED_RELOCALIZATION_SHA="226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1"
EXPECTED_STOP_GATE_SHA="0c37014abdc4bc4ad66bf23f167292c3b7ecc21c9a4f09c0d672888bb4f79d0b"
EXPECTED_STUCK_RECOVERY_SHA="a23cfc6c18816eb8299b7b75eb7f0882455fb1f81c7c33a609c0ebfaabbb6b72"
EXPECTED_HINT_ARBITER_SHA="f87323fa4f851b44ea78805b8684e9da5d90a51742cef0c896c9c5b1f6f41a93"
EXPECTED_VLM_SERVER_SHA="0a4b2638af2eb6fd0a57dd9a8bdc1e694a9116d80cbcf1a8ee1f3b40c31773c8"
EXPECTED_PORTABLE_SHA="3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a"
EXPECTED_V1_POLICY_SHA="f4199af4559e3ba70c1bdf23a4342129e2260c4b2785c6c4033acb8e4b08684b"
EXPECTED_V2_POLICY_SHA="73acb4740d2c8baba2128dcb612d0ab8fc601f4db5fea70c6818b695cf35f1bc"
EXPECTED_V11_RUNTIME_SHA="cedd63bdf3ffb87e32e6e3ee22538656412b10f84edf738c9f438461c4fba05c"
EXPECTED_V2_RUNTIME_SHA="1a8727328a1ef0a98d29eceb1365e966b8fef10c3f2f0c2b6ef7dfb7094eab3f"
EXPECTED_PORTABLE_RUNTIME_SHA="7b177ffeeac878ce4125c28f4113c425db4680b028edb81345f0919d87854285"
EXPECTED_AGENT_CFG_SHA="4558ee69bb86e5a8d173fa1b52b768b76dbd7ae369ffefe8370532a9f601ac32"
EXPECTED_CHECKPOINT_SHA="1e21097122ab0bfccaf9d4df2df794d8c1c918a1ddca72c07e38b36768f2e76c"
EXPECTED_INSTRUCTION_CACHE_SHA="cd4044f4c4d7a94308e7587aa07b9a4e1acea1a2db8db1dc8bf5cc2d050731fb"

PORTABLE_ARTIFACT="${WORK_ROOT}/artifacts/reliability_v1_1_portable_shadow.json"
V1_DECISION_POLICY="${WORK_ROOT}/configs/v11_decision_shadow_v1.json"
V2_CONSUMER_POLICY="${WORK_ROOT}/configs/v11_consumer_policy_v2_active50_20260725.json"
LOW_LEVEL_LOG_ROOT="${BENCH}/logs/rsl_rl"
LOW_LEVEL_RUN_DIR="${LOW_LEVEL_LOG_ROOT}/go2_vision/2024-09-25_23-22-02"
LOW_LEVEL_AGENT_CFG="${LOW_LEVEL_RUN_DIR}/params/agent.yaml"
LOW_LEVEL_CHECKPOINT="${LOW_LEVEL_RUN_DIR}/model_26499.pt"
INSTRUCTION_CACHE="${CANDIDATE_SCRIPTS}/generated/reversed_instructions.json"

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
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current"
COMMON_EXTRA+=" --sequential_pair_reliability_distrust_downstream"
COMMON_EXTRA+=" --reliability_quarantine_shared_trend_budget"
COMMON_EXTRA+=" --stuck_recovery"

V11_ARGS="--reliability_v11_online_shadow"
V11_ARGS+=" --reliability_v11_runtime_root=${WORK_ROOT}"
V11_ARGS+=" --reliability_v11_portable_artifact=${PORTABLE_ARTIFACT}"
V11_ARGS+=" --reliability_v11_decision_shadow"
V11_ARGS+=" --reliability_v11_decision_policy=${V1_DECISION_POLICY}"
V11_ARGS+=" --reliability_v11_consumer_policy_v2=${V2_CONSUMER_POLICY}"
V11_ARGS+=" --reliability_v11_consumer_mode=active"
V11_ARGS+=" --low_level_policy_log_root=${LOW_LEVEL_LOG_ROOT}"

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
  local count unique scene_counts
  require_sha "${BASE_DRIVER}" "${EXPECTED_DRIVER_SHA}" || return 1
  require_sha "${MANIFEST}" "${EXPECTED_MANIFEST_SHA}" || return 1
  require_sha "${VALIDATOR}" "${EXPECTED_VALIDATOR_SHA}" || return 1
  require_sha "${EVAL_SCRIPT}" "${EXPECTED_ROUND_TRIP_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/route_memory_agent.py" "${EXPECTED_AGENT_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/relocalization.py" "${EXPECTED_RELOCALIZATION_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/stop_gate.py" "${EXPECTED_STOP_GATE_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/stuck_recovery.py" "${EXPECTED_STUCK_RECOVERY_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/hint_action_arbiter.py" "${EXPECTED_HINT_ARBITER_SHA}" || return 1
  require_sha "${BENCH}/scripts/vlm_server.py" "${EXPECTED_VLM_SERVER_SHA}" || return 1
  require_sha "${PORTABLE_ARTIFACT}" "${EXPECTED_PORTABLE_SHA}" || return 1
  require_sha "${V1_DECISION_POLICY}" "${EXPECTED_V1_POLICY_SHA}" || return 1
  require_sha "${V2_CONSUMER_POLICY}" "${EXPECTED_V2_POLICY_SHA}" || return 1
  require_sha "${WORK_ROOT}/reliability/v11_runtime.py" "${EXPECTED_V11_RUNTIME_SHA}" || return 1
  require_sha "${WORK_ROOT}/reliability/v11_consumer_policy_v2.py" "${EXPECTED_V2_RUNTIME_SHA}" || return 1
  require_sha "${WORK_ROOT}/candidate/scripts/reliability_v11_portable_runtime.py" "${EXPECTED_PORTABLE_RUNTIME_SHA}" || return 1
  require_sha "${LOW_LEVEL_AGENT_CFG}" "${EXPECTED_AGENT_CFG_SHA}" || return 1
  require_sha "${LOW_LEVEL_CHECKPOINT}" "${EXPECTED_CHECKPOINT_SHA}" || return 1
  require_sha "${INSTRUCTION_CACHE}" "${EXPECTED_INSTRUCTION_CACHE_SHA}" || return 1

  count="$(awk 'NR > 1 {count++} END {print count+0}' "${MANIFEST}")"
  unique="$(awk 'NR > 1 {print $1}' "${MANIFEST}" | sort -n | uniq | wc -l)"
  if [[ "${count}" != "50" || "${unique}" != "50" ]]; then
    echo "[preflight] FATAL manifest count=${count}, unique=${unique}" >&2
    return 1
  fi
  if [[ -n "${RUN_ONLY_EPISODE}" ]] && ! awk -v ep="${RUN_ONLY_EPISODE}" \
      'NR > 1 && $1 == ep {found=1} END {exit !found}' "${MANIFEST}"; then
    echo "[preflight] FATAL RUN_ONLY_EPISODE is not in manifest: ${RUN_ONLY_EPISODE}" >&2
    return 1
  fi
  scene_counts="$(awk 'NR > 1 {n[$3]++} END {for (s in n) printf "%s=%d ",s,n[s]}' "${MANIFEST}" | xargs)"

  python3 - "${V2_CONSUMER_POLICY}" <<'PY' || return 1
import json
import sys
policy = json.load(open(sys.argv[1], encoding="utf-8"))
assert policy["schema"] == "navila-v11-consumer-policy-v2"
assert policy["mode"] == "active"
assert policy["enforcement_approved"] is True
assert policy["identity_override_authorized"] is False
assert policy["candidate_flow"] == "preserve_baseline_candidates"
PY
  python3 -m py_compile \
    "${EVAL_SCRIPT}" \
    "${CANDIDATE_SCRIPTS}/route_memory_agent.py" \
    "${WORK_ROOT}/reliability/v11_consumer_policy_v2.py" \
    "${VALIDATOR}" || return 1

  echo "[preflight] PASS: 50 unique outbound-top episodes; scenes: ${scene_counts}"
  echo "[preflight] PASS: Policy V2 active enforcement is explicitly approved"
  echo "[preflight] PASS: isolated candidate, runtime, low-level config/checkpoint, and instruction-cache hashes match"
}

result_dir_for_episode() {
  local ep_idx="$1"
  printf '%s/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_%s_ep%s' \
    "${BENCH}" "${RUN_TAG}" "${ep_idx}"
}

valid_completion() {
  local ep_idx="$1"
  local result_dir
  result_dir="$(result_dir_for_episode "${ep_idx}")"
  python3 "${VALIDATOR}" "${result_dir}" --episode "${ep_idx}" >/dev/null 2>&1
}

report_completion_failure() {
  local ep_idx="$1"
  local result_dir
  result_dir="$(result_dir_for_episode "${ep_idx}")"
  python3 "${VALIDATOR}" "${result_dir}" --episode "${ep_idx}" 2>&1 \
    | sed "s/^/[validator ep${ep_idx}] /" \
    | tee -a "${LOG_DIR}/batch.log" >&2
}

episode_selected() {
  local ep_idx="$1"
  [[ -z "${RUN_ONLY_EPISODE}" || "${ep_idx}" == "${RUN_ONLY_EPISODE}" ]]
}

archive_incomplete_result() {
  local ep_idx="$1"
  local result_dir archive_path
  result_dir="$(result_dir_for_episode "${ep_idx}")"
  if [[ ! -d "${result_dir}" ]] || valid_completion "${ep_idx}"; then
    return 0
  fi
  archive_path="${result_dir}.incomplete.$(date +%Y%m%dT%H%M%S)"
  mv "${result_dir}" "${archive_path}"
  echo "[master] archived incomplete result: ${archive_path}" | tee -a "${LOG_DIR}/batch.log"
}

preflight || exit 2
if [[ "${1:-}" == "--preflight-only" ]]; then
  exit 0
fi

EXTRA_ISAAC_ARGS="${COMMON_EXTRA} ${V11_ARGS}"

# Import the pinned lifecycle functions without executing its built-in cohort.
# EVAL_SCRIPT is already an absolute isolated-candidate path and is preserved by
# the local driver.
# shellcheck source=/dev/null
source <(sed '/^main()/,$d' "${BASE_DRIVER}")

mkdir -p "${LOG_DIR}"
cp "${MANIFEST}" "${LOG_DIR}/frozen_episode_manifest.tsv"
if [[ ! -f "${LOG_DIR}/run_provenance.txt" ]]; then
  printf '%s\n' \
    "run_tag=${RUN_TAG}" \
    "controller=${CONTROLLER_LABEL}" \
    "policy_v2_mode=active_enforcement_approved" \
    "episode_manifest_sha256=${EXPECTED_MANIFEST_SHA}" \
    "batch_driver_sha256=${EXPECTED_DRIVER_SHA}" \
    "round_trip_eval_sha256=${EXPECTED_ROUND_TRIP_SHA}" \
    "route_memory_agent_sha256=${EXPECTED_AGENT_SHA}" \
    "low_level_agent_cfg_sha256=${EXPECTED_AGENT_CFG_SHA}" \
    "low_level_checkpoint_sha256=${EXPECTED_CHECKPOINT_SHA}" \
    "instruction_cache_sha256=${EXPECTED_INSTRUCTION_CACHE_SHA}" \
    "portable_artifact_sha256=${EXPECTED_PORTABLE_SHA}" \
    "v1_decision_policy_sha256=${EXPECTED_V1_POLICY_SHA}" \
    "v2_consumer_policy_sha256=${EXPECTED_V2_POLICY_SHA}" \
    "created=$(date -Is)" > "${LOG_DIR}/run_provenance.txt"
fi
printf 'launch_or_resume=%s pid=%s\n' "$(date -Is)" "$$" >> "${LOG_DIR}/run_provenance.txt"

echo "[master] Policy V2 active 50ep launch/resume $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
echo "[master] candidate=${EVAL_SCRIPT}" | tee -a "${LOG_DIR}/batch.log"
echo "[master] enforcement=ON; guarded consumer decisions affect control" | tee -a "${LOG_DIR}/batch.log"

while IFS=$'\t' read -r ep_idx ep_id scene neighbor_idx neighbor_ep_id matched mean_distance baseline_distance; do
  [[ "${ep_idx}" == "episode_idx" ]] && continue
  episode_selected "${ep_idx}" || continue
  if valid_completion "${ep_idx}"; then
    echo "[master] resume-skip valid completed episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log"
    continue
  fi

  attempts="$(awk -F $'\t' -v ep="${ep_idx}" 'NR > 1 && $1 == ep {n++} END {print n+0}' "${SUMMARY}")"
  while (( attempts < 2 )); do
    archive_incomplete_result "${ep_idx}"
    run_episode "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
      "${matched}" "${mean_distance}" "${baseline_distance}"
    attempts=$((attempts + 1))
    if valid_completion "${ep_idx}"; then
      echo "[master] episode ${ep_idx} completion validation PASS" | tee -a "${LOG_DIR}/batch.log"
      break
    fi
    echo "[master] episode ${ep_idx} completion validation FAIL after attempt ${attempts}" | tee -a "${LOG_DIR}/batch.log"
    report_completion_failure "${ep_idx}" || true
    result_dir="$(result_dir_for_episode "${ep_idx}")"
    if [[ ! -d "${result_dir}" ]]; then
      echo "[master] FATAL bootstrap failure: episode ${ep_idx} created no result directory; aborting cohort" \
        | tee -a "${LOG_DIR}/batch.log" >&2
      tail -n 100 "${LOG_DIR}/ep${ep_idx}_eval.log" \
        | sed "s/^/[eval ep${ep_idx}] /" \
        | tee -a "${LOG_DIR}/batch.log" >&2
      exit 3
    fi
    if (( attempts < 2 )); then
      echo "[master] one bounded infrastructure retry after 120s" | tee -a "${LOG_DIR}/batch.log"
      sleep 120
    fi
  done
done < "${MANIFEST}"

valid_count=0
expected_count=0
while IFS=$'\t' read -r ep_idx _; do
  [[ "${ep_idx}" == "episode_idx" ]] && continue
  episode_selected "${ep_idx}" || continue
  expected_count=$((expected_count + 1))
  if valid_completion "${ep_idx}"; then
    valid_count=$((valid_count + 1))
  fi
done < "${MANIFEST}"

printf 'finished=%s valid_completion_count=%s\n' "$(date -Is)" "${valid_count}" >> "${LOG_DIR}/run_provenance.txt"
echo "[master] Policy V2 active finished $(date -Is); valid=${valid_count}/${expected_count}" | tee -a "${LOG_DIR}/batch.log"
if (( valid_count != expected_count )); then
  exit 4
fi
