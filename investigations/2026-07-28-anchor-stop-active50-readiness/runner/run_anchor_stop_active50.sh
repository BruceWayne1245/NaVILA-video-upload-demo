#!/usr/bin/env bash
set -u
set -o pipefail

WORK_ROOT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
CANDIDATE_SCRIPTS="${WORK_ROOT}/policy_v2_live_candidate/scripts"
BASE_DRIVER="/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726/experiments/2026-07-26-v2-integrated-promotion-shadow-canary/run_policy_v2_batch_driver.sh"
MANIFEST="/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725/experiments/2026-07-25-policy-v2-active-50ep/episodes.tsv"
VALIDATOR="/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726/experiments/2026-07-26-v2-integrated-promotion-shadow-canary/validate_completion.py"
EVAL_SCRIPT="${CANDIDATE_SCRIPTS}/round_trip_eval.py"
RUN_TAG="${RUN_TAG:-reliability_v11_anchor_stop_active50_20260728}"
PORT_BASE="${PORT_BASE:-64000}"
RUN_ONLY_EPISODE="${RUN_ONLY_EPISODE:-}"
ROUTE_HINT_SOURCE=integrated
ROUTE_RELOCALIZATION_BACKEND=sequential_pair
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1
EPISODE_TIMEOUT_SECONDS="${EPISODE_TIMEOUT_SECONDS:-7200}"
EPISODE_TIMEOUT_KILL_AFTER_SECONDS=300
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"
SUMMARY="${LOG_DIR}/summary.tsv"

PORTABLE_ARTIFACT="${WORK_ROOT}/artifacts/reliability_v1_1_portable_shadow.json"
V1_DECISION_POLICY="${WORK_ROOT}/configs/v11_decision_shadow_v1.json"
V2_CONSUMER_POLICY="${WORK_ROOT}/configs/v11_consumer_policy_v2_recovery_active50_20260727.json"
ANCHOR_SUPPORT_POLICY="${WORK_ROOT}/configs/v11_anchor_support_recovery_active_v1_active50_approved_20260728.json"
LOW_LEVEL_LOG_ROOT="${BENCH}/logs/rsl_rl"
LOW_LEVEL_RUN_DIR="${LOW_LEVEL_LOG_ROOT}/go2_vision/2024-09-25_23-22-02"
LOW_LEVEL_AGENT_CFG="${LOW_LEVEL_RUN_DIR}/params/agent.yaml"
LOW_LEVEL_CHECKPOINT="${LOW_LEVEL_RUN_DIR}/model_26499.pt"
INSTRUCTION_CACHE="${CANDIDATE_SCRIPTS}/generated/reversed_instructions.json"

EXPECTED_DRIVER_SHA="540ed476cf203e90ff6d9a3851b8458a09fbca7c11e55ebe1cced962f41696c1"
EXPECTED_MANIFEST_SHA="5c31cf60c05e64f97e1842a5d9d36cf95484ac775f0b9a50bd3afc9b93dac957"
EXPECTED_VALIDATOR_SHA="3de8ac9343a0dda7ecdac37516ab168d9b07f8e621ec9fb346341b627731e4c2"
EXPECTED_ROUND_TRIP_SHA="fd6ef129dda486d5f93fffd3c21890524f4a89afffcb7aa397b43a004803d997"
EXPECTED_AGENT_SHA="7f858fe734e6d3fc5196d6c0af56a360246a299317341918eb996a4d628162ce"
EXPECTED_RELOCALIZATION_SHA="89cda76f800caf019eb7138b5377864da139937486fd0f748ea9948194b9df2f"
EXPECTED_STOP_GATE_SHA="3d816e4ed37dbe46f20bf04eb48d5cae3fbd84ac4b1555aac1f85cfc75af9266"
EXPECTED_SCAN_CONTEXT_SHA="0940a002b58287cfad7f8a5d702386a9680e05c813b0c16453fb98e9b73dae97"
EXPECTED_STUCK_RECOVERY_SHA="a23cfc6c18816eb8299b7b75eb7f0882455fb1f81c7c33a609c0ebfaabbb6b72"
EXPECTED_HINT_ARBITER_SHA="f87323fa4f851b44ea78805b8684e9da5d90a51742cef0c896c9c5b1f6f41a93"
EXPECTED_VLM_SERVER_SHA="0a4b2638af2eb6fd0a57dd9a8bdc1e694a9116d80cbcf1a8ee1f3b40c31773c8"
EXPECTED_PORTABLE_SHA="3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a"
EXPECTED_V1_POLICY_SHA="f4199af4559e3ba70c1bdf23a4342129e2260c4b2785c6c4033acb8e4b08684b"
EXPECTED_V2_POLICY_SHA="eeb94179a5ca7a00df63e9ad9e0aa53bb366d762817ac51e87625500a044fd1e"
EXPECTED_ANCHOR_SUPPORT_POLICY_SHA="04bdfd8260525dac7ed03c63b1189378c3f2eb6ee78a4d36fab3b3ffd2c816f2"
EXPECTED_V11_RUNTIME_SHA="df3686adbef833b0bd5269acac1a54858dcc140b9c660394242b2929fa019a99"
EXPECTED_V2_RUNTIME_SHA="67fa17bac59e8a2ebf84460cc46b84d383eee530b48b54b5dace028ff3007f1a"
EXPECTED_ANCHOR_SUPPORT_RUNTIME_SHA="4715a7226e8153a2053c6d0534b6be3739d97f1d8e993b8bfb49f5d68831acba"
EXPECTED_PORTABLE_RUNTIME_SHA="7b177ffeeac878ce4125c28f4113c425db4680b028edb81345f0919d87854285"
EXPECTED_AGENT_CFG_SHA="4558ee69bb86e5a8d173fa1b52b768b76dbd7ae369ffefe8370532a9f601ac32"
EXPECTED_CHECKPOINT_SHA="1e21097122ab0bfccaf9d4df2df794d8c1c918a1ddca72c07e38b36768f2e76c"
EXPECTED_INSTRUCTION_CACHE_SHA="cd4044f4c4d7a94308e7587aa07b9a4e1acea1a2db8db1dc8bf5cc2d050731fb"

COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --stop_gate_accept_confirm_steps=2 --stop_gate_verify_queries=2"
COMMON_EXTRA+=" --stop_gate_blind_max_queries=8 --stop_gate_pre_stop_blind_trigger_queries=4"
COMMON_EXTRA+=" --stop_gate_max_evidence_age_updates=25 --stop_gate_visual_confirm_steps=2"
COMMON_EXTRA+=" --stop_gate_home_visual_max_distance_m=1.5"
COMMON_EXTRA+=" --stop_gate_home_visual_min_confidence=0.45"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90"
COMMON_EXTRA+=" --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend"
COMMON_EXTRA+=" --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10"
COMMON_EXTRA+=" --route_local_map_max_points=512 --route_local_map_profile=default"
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
COMMON_EXTRA+=" --sequential_pair_closure_check --sequential_pair_closure_reconciliation_signal=bearing"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor --sequential_pair_report_next_anchor_suppress_if_stale"
COMMON_EXTRA+=" --sequential_pair_anchor_geometry_source=accumulated --capture_icp_replay_dataset"
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current --sequential_pair_reliability_distrust_downstream"
COMMON_EXTRA+=" --reliability_quarantine_shared_trend_budget --stuck_recovery"
COMMON_EXTRA+=" --route_memory_capture_start_anchor_descriptor"
COMMON_EXTRA+=" --sequential_pair_reconstructed_confidence_source_one_hop"

V11_ARGS="--reliability_v11_online_shadow"
V11_ARGS+=" --reliability_v11_runtime_root=${WORK_ROOT}"
V11_ARGS+=" --reliability_v11_portable_artifact=${PORTABLE_ARTIFACT}"
V11_ARGS+=" --reliability_v11_decision_shadow --reliability_v11_decision_policy=${V1_DECISION_POLICY}"
V11_ARGS+=" --reliability_v11_consumer_policy_v2=${V2_CONSUMER_POLICY}"
V11_ARGS+=" --reliability_v11_consumer_mode=active"
V11_ARGS+=" --reliability_v11_derived_evidence_mode=active"
V11_ARGS+=" --reliability_v11_derived_evidence_max_age_updates=25"
V11_ARGS+=" --reliability_v11_derived_evidence_max_edge_hops=1"
V11_ARGS+=" --reliability_v11_integrated_promotion_mode=off"
V11_ARGS+=" --reliability_v11_integrated_anchor_state_mode=off"
V11_ARGS+=" --reliability_v11_integrated_candidate_selector_mode=off"
V11_ARGS+=" --reliability_v11_integrated_candidate_controller_mode=off"
V11_ARGS+=" --reliability_v11_active_scan_plan_mode=off"
V11_ARGS+=" --reliability_v11_anchor_support_recovery_mode=active"
V11_ARGS+=" --reliability_v11_anchor_support_recovery_policy=${ANCHOR_SUPPORT_POLICY}"
V11_ARGS+=" --reliability_v11_anchor_support_recovery_active_armed"
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
  local count unique max_port
  require_sha "${BASE_DRIVER}" "${EXPECTED_DRIVER_SHA}" || return 1
  require_sha "${MANIFEST}" "${EXPECTED_MANIFEST_SHA}" || return 1
  require_sha "${VALIDATOR}" "${EXPECTED_VALIDATOR_SHA}" || return 1
  require_sha "${EVAL_SCRIPT}" "${EXPECTED_ROUND_TRIP_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/route_memory_agent.py" "${EXPECTED_AGENT_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/relocalization.py" "${EXPECTED_RELOCALIZATION_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/stop_gate.py" "${EXPECTED_STOP_GATE_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/scan_context.py" "${EXPECTED_SCAN_CONTEXT_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/stuck_recovery.py" "${EXPECTED_STUCK_RECOVERY_SHA}" || return 1
  require_sha "${CANDIDATE_SCRIPTS}/hint_action_arbiter.py" "${EXPECTED_HINT_ARBITER_SHA}" || return 1
  require_sha "${BENCH}/scripts/vlm_server.py" "${EXPECTED_VLM_SERVER_SHA}" || return 1
  require_sha "${PORTABLE_ARTIFACT}" "${EXPECTED_PORTABLE_SHA}" || return 1
  require_sha "${V1_DECISION_POLICY}" "${EXPECTED_V1_POLICY_SHA}" || return 1
  require_sha "${V2_CONSUMER_POLICY}" "${EXPECTED_V2_POLICY_SHA}" || return 1
  require_sha "${ANCHOR_SUPPORT_POLICY}" "${EXPECTED_ANCHOR_SUPPORT_POLICY_SHA}" || return 1
  require_sha "${WORK_ROOT}/reliability/v11_runtime.py" "${EXPECTED_V11_RUNTIME_SHA}" || return 1
  require_sha "${WORK_ROOT}/reliability/v11_consumer_policy_v2.py" "${EXPECTED_V2_RUNTIME_SHA}" || return 1
  require_sha "${WORK_ROOT}/reliability/v11_anchor_support_recovery.py" "${EXPECTED_ANCHOR_SUPPORT_RUNTIME_SHA}" || return 1
  require_sha "${WORK_ROOT}/candidate/scripts/reliability_v11_portable_runtime.py" "${EXPECTED_PORTABLE_RUNTIME_SHA}" || return 1
  require_sha "${LOW_LEVEL_AGENT_CFG}" "${EXPECTED_AGENT_CFG_SHA}" || return 1
  require_sha "${LOW_LEVEL_CHECKPOINT}" "${EXPECTED_CHECKPOINT_SHA}" || return 1
  require_sha "${INSTRUCTION_CACHE}" "${EXPECTED_INSTRUCTION_CACHE_SHA}" || return 1

  count="$(awk 'NR > 1 {count++} END {print count+0}' "${MANIFEST}")"
  unique="$(awk 'NR > 1 {print $1}' "${MANIFEST}" | sort -n | uniq | wc -l)"
  max_port="$((PORT_BASE + $(awk 'NR > 1 {if ($1 > m) m=$1} END {print m+0}' "${MANIFEST}")))"
  if [[ "${count}" != "50" || "${unique}" != "50" || "${max_port}" -gt 65535 ]]; then
    echo "[preflight] FATAL manifest count=${count} unique=${unique} max_port=${max_port}" >&2
    return 1
  fi
  if [[ -n "${RUN_ONLY_EPISODE}" ]] && ! awk -v ep="${RUN_ONLY_EPISODE}" \
      'NR > 1 && $1 == ep {found=1} END {exit !found}' "${MANIFEST}"; then
    echo "[preflight] FATAL requested episode outside approved manifest: ${RUN_ONLY_EPISODE}" >&2
    return 1
  fi

  python3 - "${V2_CONSUMER_POLICY}" "${ANCHOR_SUPPORT_POLICY}" "${MANIFEST}" <<'PY' || return 1
import csv
import hashlib
import json
import sys
consumer_path, support_path, manifest_path = sys.argv[1:]
consumer = json.load(open(consumer_path, encoding="utf-8"))
support = json.load(open(support_path, encoding="utf-8"))
manifest_bytes = open(manifest_path, "rb").read()
manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
with open(manifest_path, newline="", encoding="utf-8") as handle:
    episode_ids = [
        int(row["episode_idx"])
        for row in csv.DictReader(handle, delimiter="\t")
    ]
assert consumer["schema"] == "navila-v11-consumer-policy-v2"
assert consumer["mode"] == "active"
assert consumer["enforcement_approved"] is True
assert consumer["identity_override_authorized"] is False
assert consumer["approval_scope"]["episode_manifest_sha256"] == manifest_sha
assert consumer["approval_scope"]["max_completed_episodes"] == 50
assert support["schema"] == "navila-v11-anchor-support-recovery-active-v1"
assert support["mode"] == "active"
assert support["enforcement_approved"] is True
assert support["identity_semantics"] == "guidance_support_not_localization"
assert support["scan_role"] == "shadow_observer_only"
assert support["approval_scope"]["episode_ids"] == episode_ids
assert support["approval_scope"]["episode_manifest_sha256"] == manifest_sha
assert support["approval_scope"]["max_completed_episodes"] == 50
PY

  python3 -m py_compile \
    "${EVAL_SCRIPT}" \
    "${CANDIDATE_SCRIPTS}/route_memory_agent.py" \
    "${CANDIDATE_SCRIPTS}/stop_gate.py" \
    "${CANDIDATE_SCRIPTS}/scan_context.py" \
    "${WORK_ROOT}/reliability/v11_anchor_support_recovery.py" \
    "${VALIDATOR}" || return 1
  echo "[preflight] PASS: frozen 50ep scope, code hashes, approval and port range"
}

result_dir_for_episode() {
  printf '%s/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_%s_ep%s' \
    "${BENCH}" "${RUN_TAG}" "$1"
}

valid_completion() {
  python3 "${VALIDATOR}" "$(result_dir_for_episode "$1")" --episode "$1" \
    >/dev/null 2>&1
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
  echo "[master] archived incomplete result: ${archive_path}" \
    | tee -a "${LOG_DIR}/batch.log"
}

preflight || exit 2
if [[ "${1:-}" == "--preflight-only" ]]; then
  exit 0
fi

EXTRA_ISAAC_ARGS="${COMMON_EXTRA} ${V11_ARGS}"
# Import lifecycle functions only; never execute the base driver's cohort.
# shellcheck source=/dev/null
source <(sed '/^main()/,$d' "${BASE_DRIVER}")

cleanup_interrupted_batch() {
  local status="$1"
  trap - INT TERM
  kill_process_group "${eval_pid:-}"
  kill_process_group "${VLM_PID:-}"
  exit "${status}"
}
trap 'cleanup_interrupted_batch 130' INT
trap 'cleanup_interrupted_batch 143' TERM

mkdir -p "${LOG_DIR}"
cp "${MANIFEST}" "${LOG_DIR}/frozen_episode_manifest.tsv"
if [[ ! -f "${LOG_DIR}/run_provenance.txt" ]]; then
  printf '%s\n' \
    "run_tag=${RUN_TAG}" \
    "episode_manifest_sha256=${EXPECTED_MANIFEST_SHA}" \
    "round_trip_eval_sha256=${EXPECTED_ROUND_TRIP_SHA}" \
    "stop_gate_sha256=${EXPECTED_STOP_GATE_SHA}" \
    "scan_context_sha256=${EXPECTED_SCAN_CONTEXT_SHA}" \
    "anchor_support_runtime_sha256=${EXPECTED_ANCHOR_SUPPORT_RUNTIME_SHA}" \
    "stop_gate_pre_stop_blind_trigger_queries=4" \
    "stop_gate_total_blind_budget_queries=8" \
    "integrated_candidate_controller=off" \
    "active_scan_plan=off" \
    "created=$(date -Is)" > "${LOG_DIR}/run_provenance.txt"
fi
printf 'launch_or_resume=%s pid=%s\n' "$(date -Is)" "$$" \
  >> "${LOG_DIR}/run_provenance.txt"

echo "[master] Anchor/stop Active-50 launch/resume $(date -Is)" \
  | tee -a "${LOG_DIR}/batch.log"
echo "[master] candidate=${EVAL_SCRIPT}" | tee -a "${LOG_DIR}/batch.log"
echo "[master] controller/selector/scan motor off; anchor support recovery active" \
  | tee -a "${LOG_DIR}/batch.log"

while IFS=$'\t' read -r ep_idx ep_id scene neighbor_idx neighbor_ep_id matched mean_distance baseline_distance; do
  [[ "${ep_idx}" == "episode_idx" ]] && continue
  [[ -n "${RUN_ONLY_EPISODE}" && "${ep_idx}" != "${RUN_ONLY_EPISODE}" ]] && continue
  if valid_completion "${ep_idx}"; then
    echo "[master] resume-skip valid completed episode ${ep_idx}" \
      | tee -a "${LOG_DIR}/batch.log"
    continue
  fi

  attempts="$(awk -F $'\t' -v ep="${ep_idx}" \
    'NR > 1 && $1 == ep {n++} END {print n+0}' "${SUMMARY}")"
  while (( attempts < 2 )); do
    archive_incomplete_result "${ep_idx}"
    run_episode "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" \
      "${neighbor_ep_id}" "${matched}" "${mean_distance}" "${baseline_distance}"
    attempts=$((attempts + 1))
    if valid_completion "${ep_idx}"; then
      echo "[master] episode ${ep_idx} completion validation PASS" \
        | tee -a "${LOG_DIR}/batch.log"
      break
    fi
    echo "[master] episode ${ep_idx} invalid after attempt ${attempts}" \
      | tee -a "${LOG_DIR}/batch.log"
    if (( attempts < 2 )); then
      echo "[master] bounded infrastructure retry after 120s" \
        | tee -a "${LOG_DIR}/batch.log"
      sleep 120
    fi
  done
done < "${MANIFEST}"

valid_count=0
expected_count=0
while IFS=$'\t' read -r ep_idx _; do
  [[ "${ep_idx}" == "episode_idx" ]] && continue
  [[ -n "${RUN_ONLY_EPISODE}" && "${ep_idx}" != "${RUN_ONLY_EPISODE}" ]] && continue
  expected_count=$((expected_count + 1))
  valid_completion "${ep_idx}" && valid_count=$((valid_count + 1))
done < "${MANIFEST}"

printf 'finished=%s valid_completion_count=%s expected_count=%s\n' \
  "$(date -Is)" "${valid_count}" "${expected_count}" \
  >> "${LOG_DIR}/run_provenance.txt"
echo "[master] Anchor/stop Active-50 finished; valid=${valid_count}/${expected_count}" \
  | tee -a "${LOG_DIR}/batch.log"
(( valid_count == expected_count ))
