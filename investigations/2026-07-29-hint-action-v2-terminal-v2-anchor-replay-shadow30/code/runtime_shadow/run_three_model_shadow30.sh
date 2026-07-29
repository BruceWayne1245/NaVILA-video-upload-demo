#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/teambruce/navila-anchor-terminal-training-data-20260729"
ACTIVE_ROOT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
BASE_DRIVER="/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726/experiments/2026-07-26-v2-integrated-promotion-shadow-canary/run_policy_v2_batch_driver.sh"
ACTIVE50_RUNNER="${ACTIVE_ROOT}/experiments/2026-07-28-anchor-stop-active50/run_anchor_stop_active50.sh"
EVAL_SCRIPT="${ACTIVE_ROOT}/policy_v2_live_candidate/scripts/round_trip_eval.py"
MANIFEST="${ROOT}/runtime_shadow/three_model_shadow30.tsv"
SCORER="${ROOT}/runtime_shadow/score_three_model_episode.py"
TRAINING_EPISODES="${ROOT}/data/v1/episodes.jsonl"
ISAAC_PYTHON="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
RUN_ROOT="${ROOT}/runtime_shadow/runs/three_model_shadow30_20260729"
CANARY_TAG="three_model_readonly_shadow30_canary_20260729"
BATCH_TAG="three_model_readonly_shadow30_20260729"
PORT_BASE=58000
CANARY_EPISODE=670
ALL_EPISODES="670 783 382 381 653 652 338 696 189 144 178 277 289 248 488 486 546 467 1058 974 875 1004 639 640 726 534 354 137 409 410"
BATCH_EPISODES="783 382 381 653 652 338 696 189 144 178 277 289 248 488 486 546 467 1058 974 875 1004 639 640 726 534 354 137 409 410"
RESULT_PREFIX="${BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"

EXPECTED_MANIFEST_SHA="cf3c37470d29847bfc83a629ff2d1396b5e21dcc17d6186dc7de60fc233b4d27"
EXPECTED_SCORER_SHA="aba7c5eea466a3b08dc22b46285cf0e29c9056411bc62717858d6a107f0fbfc8"
EXPECTED_TRAINING_EPISODES_SHA="7843df320f4de391788ae5884c36e65ba8e43e1fed458b259c966fc8605a7722"
EXPECTED_ANCHOR_SHA="4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55"
EXPECTED_TERMINAL_SHA="f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb"
EXPECTED_HINT_V1_SHA="1851c727534f943396c7f74ec6b47f8da0695753cb0edc17fd957cdc532f03ca"
EXPECTED_HINT_V2_SHA="567e24aef5036e3310a36a8333ab8cc40ee467a293506973fa544fb1baa49603"
EXPECTED_DRIVER_SHA="540ed476cf203e90ff6d9a3851b8458a09fbca7c11e55ebe1cced962f41696c1"
EXPECTED_EVAL_SHA="fd6ef129dda486d5f93fffd3c21890524f4a89afffcb7aa397b43a004803d997"

mkdir -p "${RUN_ROOT}"
exec > >(tee -a "${RUN_ROOT}/orchestrator.log") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

sha_of() {
  sha256sum "$1" | awk '{print $1}'
}

require_sha() {
  local path="$1"
  local expected="$2"
  local actual
  actual="$(sha_of "${path}")"
  if [[ "${actual}" != "${expected}" ]]; then
    log "FATAL SHA mismatch path=${path} expected=${expected} actual=${actual}"
    return 1
  fi
}

preflight() {
  require_sha "${MANIFEST}" "${EXPECTED_MANIFEST_SHA}"
  require_sha "${SCORER}" "${EXPECTED_SCORER_SHA}"
  require_sha "${TRAINING_EPISODES}" "${EXPECTED_TRAINING_EPISODES_SHA}"
  require_sha "${ROOT}/models/v1/anchor_transition_v1.joblib" "${EXPECTED_ANCHOR_SHA}"
  require_sha "${ROOT}/models/v2/terminal_decision_v2_robust.joblib" "${EXPECTED_TERMINAL_SHA}"
  require_sha "${ROOT}/models/v1/hint_action_decision_v1.joblib" "${EXPECTED_HINT_V1_SHA}"
  require_sha "${ROOT}/models/v2/hint_action_decision_v2_binary.joblib" "${EXPECTED_HINT_V2_SHA}"
  require_sha "${BASE_DRIVER}" "${EXPECTED_DRIVER_SHA}"
  require_sha "${EVAL_SCRIPT}" "${EXPECTED_EVAL_SHA}"
  bash "${ACTIVE50_RUNNER}" --preflight-only
  "${ISAAC_PYTHON}" - "${MANIFEST}" "${TRAINING_EPISODES}" "${BASE_DRIVER}" <<'PY'
import csv
import json
import re
import sys

manifest_path, training_path, driver_path = sys.argv[1:]
with open(manifest_path, newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
ids = [int(row["episode_idx"]) for row in rows]
training = {
    int(json.loads(line)["physical_episode_id"])
    for line in open(training_path, encoding="utf-8")
    if line.strip()
}
prior_five = {319, 498, 295, 430, 1008}
driver_ids = {
    int(match.group(1))
    for match in re.finditer(
        r"^\s*run_episode\s+(\d+)\s+",
        open(driver_path, encoding="utf-8").read(),
        re.MULTILINE,
    )
}
assert len(rows) == 30
assert len(set(ids)) == 30
assert not (set(ids) & training), sorted(set(ids) & training)
assert not (set(ids) & prior_five), sorted(set(ids) & prior_five)
assert set(ids) <= driver_ids
assert len({row["scene"] for row in rows}) == 9
assert max(58000 + episode for episode in ids) <= 65535
PY
  "${ISAAC_PYTHON}" -m py_compile "${SCORER}"
  local free_mib
  free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
  if (( free_mib < 12000 )); then
    log "FATAL GPU free memory ${free_mib}MiB < 12000MiB"
    return 1
  fi
  log "preflight PASS: 30 unseen episodes, 9 scenes, frozen models, control consumers off"
}

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

run_driver() {
  local tag="$1"
  local episodes="$2"
  log "launching evaluator tag=${tag} episodes=${episodes}"
  RUN_TAG="${tag}" \
  PORT_BASE="${PORT_BASE}" \
  ONLY_EPISODES="${episodes}" \
  EVAL_SCRIPT="${EVAL_SCRIPT}" \
  ROUTE_HINT_SOURCE=integrated \
  ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
  ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
  EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" \
  bash "${BASE_DRIVER}"
}

score_episode() {
  local tag="$1"
  local episode="$2"
  local result_dir="${RESULT_PREFIX}_${tag}_ep${episode}"
  local score_log="${RUN_ROOT}/${tag}_scoring.log"
  if [[ ! -d "${result_dir}" ]]; then
    log "score unavailable ep=${episode}: result directory missing"
    return 2
  fi
  if "${ISAAC_PYTHON}" "${SCORER}" "${result_dir}" >> "${score_log}" 2>&1; then
    log "score PASS tag=${tag} ep=${episode}"
    return 0
  fi
  log "score unavailable tag=${tag} ep=${episode}; see ${score_log}"
  return 2
}

write_provenance() {
  cp "${MANIFEST}" "${RUN_ROOT}/three_model_shadow30.tsv"
  {
    echo "created=$(date -Is)"
    echo "mode=postepisode_readonly_shadow"
    echo "control_effect=none"
    echo "canary_tag=${CANARY_TAG}"
    echo "batch_tag=${BATCH_TAG}"
    echo "episodes=${ALL_EPISODES}"
    echo "manifest_sha256=${EXPECTED_MANIFEST_SHA}"
    echo "scorer_sha256=${EXPECTED_SCORER_SHA}"
    echo "anchor_sha256=${EXPECTED_ANCHOR_SHA}"
    echo "terminal_sha256=${EXPECTED_TERMINAL_SHA}"
    echo "hint_v1_sha256=${EXPECTED_HINT_V1_SHA}"
    echo "hint_v2_sha256=${EXPECTED_HINT_V2_SHA}"
    echo "round_trip_eval_sha256=${EXPECTED_EVAL_SHA}"
  } > "${RUN_ROOT}/provenance.txt"
}

if [[ "${1:-}" == "--preflight-only" ]]; then
  preflight
  exit 0
fi

preflight
write_provenance
log "starting canary ep=${CANARY_EPISODE}"
run_driver "${CANARY_TAG}" "${CANARY_EPISODE}"
score_episode "${CANARY_TAG}" "${CANARY_EPISODE}"
"${ISAAC_PYTHON}" - "${RESULT_PREFIX}_${CANARY_TAG}_ep${CANARY_EPISODE}/${OUTPUT_NAME:-three_model_readonly_shadow_summary.json}" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["scoreable"] is True
assert value["control_effect"] == "none"
assert set(value["tasks"]) == {
    "anchor_v1",
    "terminal_v2_robust",
    "hint_v1",
    "hint_v2_binary",
}
PY
log "canary PASS; starting remaining 29 episodes"
run_driver "${BATCH_TAG}" "${BATCH_EPISODES}"

score_failures=0
for episode in ${BATCH_EPISODES}; do
  if ! score_episode "${BATCH_TAG}" "${episode}"; then
    score_failures=$((score_failures + 1))
  fi
done
{
  echo "finished=$(date -Is)"
  echo "score_failures=${score_failures}"
  echo "control_effect=none"
} >> "${RUN_ROOT}/provenance.txt"
touch "${RUN_ROOT}/COMPLETED"
log "three-model shadow30 finished score_failures=${score_failures}"
