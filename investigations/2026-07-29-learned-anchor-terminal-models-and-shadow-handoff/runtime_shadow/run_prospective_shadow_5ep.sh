#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/teambruce/navila-anchor-terminal-training-data-20260729"
ACTIVE_ROOT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
BASE_DRIVER="/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726/experiments/2026-07-26-v2-integrated-promotion-shadow-canary/run_policy_v2_batch_driver.sh"
ACTIVE50_RUNNER="${ACTIVE_ROOT}/experiments/2026-07-28-anchor-stop-active50/run_anchor_stop_active50.sh"
EVAL_SCRIPT="${ACTIVE_ROOT}/policy_v2_live_candidate/scripts/round_trip_eval.py"
MANIFEST="${ROOT}/runtime_shadow/prospective_5ep.tsv"
SCORER="${ROOT}/runtime_shadow/score_episode.py"
ISAAC_PYTHON="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
RUN_TAG="${RUN_TAG:-learned_anchor_terminal_replay_shadow_5ep_20260729}"
PORT_BASE="${PORT_BASE:-57000}"
ONLY_EPISODES="319 498 295 430 1008"
RESULT_PREFIX="${BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"

EXPECTED_MANIFEST_SHA="dfcf4ea1d2c00378b5a87c8b7ed5110860791f5902c3c912b26ddc50d4cb213c"
EXPECTED_SCORER_SHA="f59dc0ae2102ccc00de4c698c90b1f04df49743a6bdfd7055a1fc87e7391ea08"
EXPECTED_ANCHOR_MODEL_SHA="4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55"
EXPECTED_TERMINAL_MODEL_SHA="1b7bbc2fab5211c9b6422c70103735b89a8f3d75fa7c23beacfb8ea3b64cab84"
EXPECTED_DRIVER_SHA="540ed476cf203e90ff6d9a3851b8458a09fbca7c11e55ebe1cced962f41696c1"
EXPECTED_EVAL_SHA="fd6ef129dda486d5f93fffd3c21890524f4a89afffcb7aa397b43a004803d997"

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
  require_sha "${MANIFEST}" "${EXPECTED_MANIFEST_SHA}"
  require_sha "${SCORER}" "${EXPECTED_SCORER_SHA}"
  require_sha "${ROOT}/models/v1/anchor_transition_v1.joblib" "${EXPECTED_ANCHOR_MODEL_SHA}"
  require_sha "${ROOT}/models/v1/terminal_decision_v1.joblib" "${EXPECTED_TERMINAL_MODEL_SHA}"
  require_sha "${BASE_DRIVER}" "${EXPECTED_DRIVER_SHA}"
  require_sha "${EVAL_SCRIPT}" "${EXPECTED_EVAL_SHA}"
  bash "${ACTIVE50_RUNNER}" --preflight-only
  "${ISAAC_PYTHON}" - "${MANIFEST}" "${ROOT}/data/v1/episodes.jsonl" <<'PY'
import csv
import json
import sys

manifest_path, training_path = sys.argv[1:]
with open(manifest_path, newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
episode_ids = [int(row["episode_idx"]) for row in rows]
training_ids = {
    int(json.loads(line)["physical_episode_id"])
    for line in open(training_path, encoding="utf-8")
    if line.strip()
}
assert len(rows) == 5
assert len(set(episode_ids)) == 5
overlap = sorted(set(episode_ids) & training_ids)
assert not overlap, f"prospective cohort overlaps training corpus: {overlap}"
assert max(57000 + episode for episode in episode_ids) <= 65535
PY
  "${ISAAC_PYTHON}" -m py_compile "${SCORER}"
  echo "[preflight] PASS: frozen models, latest 2026-07-28 code, and five unseen episodes"
}

preflight
if [[ "${1:-}" == "--preflight-only" ]]; then
  exit 0
fi

COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --stop_gate_accept_confirm_steps=2 --stop_gate_verify_queries=2"
COMMON_EXTRA+=" --stop_gate_blind_max_queries=8 --stop_gate_pre_stop_blind_trigger_queries=4"
COMMON_EXTRA+=" --stop_gate_max_evidence_age_updates=25 --stop_gate_visual_confirm_steps=2"
COMMON_EXTRA+=" --stop_gate_home_visual_max_distance_m=1.5"
COMMON_EXTRA+=" --stop_gate_home_visual_min_confidence=0.45"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter"
COMMON_EXTRA+=" --hint_arbiter_min_relocalization_confidence=0.90"
COMMON_EXTRA+=" --sequential_pair_quarantine --sequential_pair_quarantine_mode=trend"
COMMON_EXTRA+=" --route_local_map_icp_objective=point_to_point"
COMMON_EXTRA+=" --route_local_map_voxel_size_m=0.10 --route_local_map_max_points=512"
COMMON_EXTRA+=" --route_local_map_profile=default --route_local_map_quality_policy=diagnostic"
COMMON_EXTRA+=" --sequential_pair_promotion_mode=bounded_evidence"
COMMON_EXTRA+=" --sequential_pair_promotion_window=5 --sequential_pair_promotion_min_votes=3"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_aware"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_threshold=0.6"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_window=8"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_min_votes=5"
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
COMMON_EXTRA+=" --sequential_pair_anchor_geometry_source=accumulated"
COMMON_EXTRA+=" --capture_icp_replay_dataset"
COMMON_EXTRA+=" --sequential_pair_reliability_quarantine"
COMMON_EXTRA+=" --reliability_quarantine_threshold=2.5"
COMMON_EXTRA+=" --sequential_pair_reliability_demote_current"
COMMON_EXTRA+=" --sequential_pair_reliability_distrust_downstream"
COMMON_EXTRA+=" --reliability_quarantine_shared_trend_budget --stuck_recovery"
COMMON_EXTRA+=" --route_memory_capture_start_anchor_descriptor"
COMMON_EXTRA+=" --sequential_pair_reconstructed_confidence_source_one_hop"

# Existing V1.1 predictions enrich the learned models' candidate inputs, but
# every consumer remains off. Neither learned v1 model is imported by the
# evaluator; both are scored only after the completed episode is on disk.
COMMON_EXTRA+=" --reliability_v11_online_shadow"
COMMON_EXTRA+=" --reliability_v11_runtime_root=${ACTIVE_ROOT}"
COMMON_EXTRA+=" --reliability_v11_portable_artifact=${ACTIVE_ROOT}/artifacts/reliability_v1_1_portable_shadow.json"
COMMON_EXTRA+=" --reliability_v11_decision_shadow"
COMMON_EXTRA+=" --reliability_v11_decision_policy=${ACTIVE_ROOT}/configs/v11_decision_shadow_v1.json"
COMMON_EXTRA+=" --reliability_v11_consumer_mode=off"
COMMON_EXTRA+=" --reliability_v11_derived_evidence_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_promotion_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_anchor_state_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_candidate_selector_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_candidate_controller_mode=off"
COMMON_EXTRA+=" --reliability_v11_active_scan_plan_mode=off"
COMMON_EXTRA+=" --reliability_v11_anchor_support_recovery_mode=off"
COMMON_EXTRA+=" --low_level_policy_log_root=${BENCH}/logs/rsl_rl"

mkdir -p "${LOG_DIR}"
cp "${MANIFEST}" "${LOG_DIR}/prospective_episode_manifest.tsv"
printf '%s\n' \
  "run_tag=${RUN_TAG}" \
  "mode=replay_shadow_no_control_effect" \
  "episodes=${ONLY_EPISODES}" \
  "manifest_sha256=${EXPECTED_MANIFEST_SHA}" \
  "anchor_model_sha256=${EXPECTED_ANCHOR_MODEL_SHA}" \
  "terminal_model_sha256=${EXPECTED_TERMINAL_MODEL_SHA}" \
  "round_trip_eval_sha256=${EXPECTED_EVAL_SHA}" \
  "created=$(date -Is)" > "${LOG_DIR}/learned_shadow_provenance.txt"

RUN_TAG="${RUN_TAG}" \
PORT_BASE="${PORT_BASE}" \
ONLY_EPISODES="${ONLY_EPISODES}" \
EVAL_SCRIPT="${EVAL_SCRIPT}" \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
bash "${BASE_DRIVER}"

score_failures=0
for episode in ${ONLY_EPISODES}; do
  result_dir="${RESULT_PREFIX}_${RUN_TAG}_ep${episode}"
  if [[ ! -d "${result_dir}" ]]; then
    echo "[shadow] episode ${episode}: result directory missing" \
      | tee -a "${LOG_DIR}/learned_shadow_scoring.log"
    score_failures=$((score_failures + 1))
    continue
  fi
  if "${ISAAC_PYTHON}" "${SCORER}" "${result_dir}" \
      >> "${LOG_DIR}/learned_shadow_scoring.log" 2>&1; then
    echo "[shadow] episode ${episode}: scoring PASS" \
      | tee -a "${LOG_DIR}/learned_shadow_scoring.log"
  else
    echo "[shadow] episode ${episode}: scoring unavailable" \
      | tee -a "${LOG_DIR}/learned_shadow_scoring.log"
    score_failures=$((score_failures + 1))
  fi
done

printf 'finished=%s score_failures=%s control_effect=none\n' \
  "$(date -Is)" "${score_failures}" \
  >> "${LOG_DIR}/learned_shadow_provenance.txt"
echo "[shadow] prospective 5ep replay-shadow finished; scoring_failures=${score_failures}" \
  | tee -a "${LOG_DIR}/learned_shadow_scoring.log"
