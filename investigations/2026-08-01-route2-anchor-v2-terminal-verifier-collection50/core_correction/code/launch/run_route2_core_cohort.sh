#!/usr/bin/env bash
set -u

# Default: immutable static preflight only. This file neither queues work nor
# stops a running evaluator. A cohort starts only with one explicit launch arm.
ROOT="/home/teambruce/navila-route2-v11-core-20260801"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
DATASET="${BENCH}/isaaclab_exts/omni.isaac.vlnce/assets/vln_ce_isaac_v1.json.gz"
ISAAC_PYTHON="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
DRIVER="${ROOT}/launch/run_manifest_batch_driver.sh"
EVALUATOR="${ROOT}/runtime_candidate/scripts/round_trip_eval.py"
STOP_GATE="${ROOT}/runtime_candidate/scripts/stop_gate.py"
PORTABLE_RUNTIME="${ROOT}/runtime_candidate/scripts/reliability_v11_portable_runtime.py"
CORE_RUNTIME="${ROOT}/reliability/v11_consumer_policy_v3.py"
CORE_POLICY="${ROOT}/config/v11_consumer_policy_v3_core_active.json"
CORE_HINT_POLICY="${ROOT}/config/core_hint_shadow_policy_v1.json"
VALIDATOR="${ROOT}/validation/validate_v11_core_episode.py"
SCORER="${ROOT}/scoring/score_episode.py"
EXPORTER="${ROOT}/scoring/export_terminal_collection.py"
VERIFIER_FEATURES="${ROOT}/scoring/terminal_candidate_verifier_features.py"
ANCHOR_ONLINE="${ROOT}/anchor_transition_runtime/online.py"
ANCHOR_GUARD="${ROOT}/anchor_transition_runtime/promotion_guard.py"
ANCHOR_FEATURES="${ROOT}/training/core_v1_src/model_features.py"
ANCHOR_MODEL="${ROOT}/models/core_v1/anchor_transition_core_v1.joblib"
TERMINAL_MODEL="${ROOT}/models/core_v1/terminal_decision_core_v1.joblib"
HINT_MODEL="${ROOT}/models/core_v1/hint_action_core_v1.joblib"
COHORT_LOCK="${ROOT}/config/route2_core_cohort_lock_v1.json"
COHORT_EVIDENCE="${ROOT}/manifest/route2_core_cohort_evidence.tsv"
DEV_MANIFEST="${ROOT}/manifest/route2_core_development24.tsv"
VALIDATION_MANIFEST="${ROOT}/manifest/route2_core_locked_validation20.tsv"
V11_ARTIFACT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/artifacts/reliability_v1_1_portable_shadow.json"
RESULT_PREFIX="${BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"
PORT_BASE=54000

EXPECTED_DRIVER_SHA="887fec7ad8296ec8b6c19af7e8a4639d2cdfa2d3ca7cf03fde46f01133ef80bb"
EXPECTED_EVALUATOR_SHA="9a43cd096ff07c00a1cff54d0f1ad1b685377ba587c4a56e710ffd7145387a5a"
EXPECTED_STOP_GATE_SHA="37a372ab121f1d7766698ffc89db0e3fce7b7ede1d1680263a22ec7699f5f16b"
EXPECTED_PORTABLE_RUNTIME_SHA="7b177ffeeac878ce4125c28f4113c425db4680b028edb81345f0919d87854285"
EXPECTED_CORE_RUNTIME_SHA="90c2768afdfb2a26e3d305065266a8e95c205ac93fbbea815992c85f36159e7e"
EXPECTED_CORE_POLICY_SHA="543f71754f4f7ef43bb36f007e8809f2ae9c8c097b83634e5faae0c5fffb1460"
EXPECTED_HINT_POLICY_SHA="88a2247a007fa722e0046c53f7432915e345e95e1422d404d9ce31bfccde7275"
EXPECTED_VALIDATOR_SHA="4a6af77032b97a780038f469e18a69eae37f94757bb43ba74c3b9760a555c923"
EXPECTED_SCORER_SHA="c1d4a0e713e056745d626705660f46801fc14182125380277c23019ea93e9480"
EXPECTED_EXPORTER_SHA="d9098cfb03f6a1b109c774b9ba999cc40afd9ea911ac08b1b4b876bba7c125a9"
EXPECTED_VERIFIER_FEATURES_SHA="7534f27c22bde1f09c1b81b30c77cb8ee789c715be236ef959333df068000a64"
EXPECTED_ANCHOR_ONLINE_SHA="ac70bf4b5da95d27f48a109522a9ad3a390e371dc380d234387b2b215d59cd49"
EXPECTED_ANCHOR_GUARD_SHA="fd5ff72689b5c6d4736f8054de1f9b8032b1ed53de75bf5116119f5c5e9664d4"
EXPECTED_ANCHOR_FEATURES_SHA="ca3030a878e44038b4d9e8ed9be4fa56b7263d423eaed48e9be523edf76a95a1"
EXPECTED_ANCHOR_MODEL_SHA="cf920f45852c3ed7e0d15068c7e67a943bb01372ce9d922c7dfaa7531f73fa37"
EXPECTED_TERMINAL_MODEL_SHA="49358cb7b53397469792718fc33765f87617b009290727c0cfac23eae0d1fa5b"
EXPECTED_HINT_MODEL_SHA="2829784b30920a9e270a5c9f7050303f7ef2488cbedabb3a8c9c4901b9e97e7e"
EXPECTED_V11_ARTIFACT_SHA="3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a"
EXPECTED_COHORT_LOCK_SHA="1e64770549f388db8b7232af72d7bb154694e03298ff8827d913894d776529b4"
EXPECTED_EVIDENCE_SHA="62aa9cc37dede5ac8527758b3a9e9e096ac6f2aca0f51022d9f01ed1706f44a4"
EXPECTED_DEV_MANIFEST_SHA="35e06e51ebb0747e4d5a9fcadb843298766ee5a81cc384892ce51337afb29fd1"
EXPECTED_VALIDATION_MANIFEST_SHA="4faafb4bec7e36505fd46a0f2060bb0ec9a6046556de36a2013809820f807ef0"

sha_of() { sha256sum "$1" | awk '{print $1}'; }
require_sha() {
  local actual
  actual="$(sha_of "$1")"
  if [[ "${actual}" != "$2" ]]; then
    echo "FATAL SHA mismatch path=$1 expected=$2 actual=${actual}" >&2
    return 1
  fi
}

COMMON_EXTRA="--route_relocalization_interval_updates=5"
COMMON_EXTRA+=" --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0"
COMMON_EXTRA+=" --stop_gate_accept_confirm_steps=2 --stop_gate_verify_queries=2"
COMMON_EXTRA+=" --stop_gate_blind_max_queries=8 --stop_gate_pre_stop_blind_trigger_queries=4"
COMMON_EXTRA+=" --stop_gate_max_evidence_age_updates=25 --stop_gate_visual_confirm_steps=2"
COMMON_EXTRA+=" --stop_gate_home_visual_max_distance_m=1.5 --stop_gate_home_visual_min_confidence=0.45"
COMMON_EXTRA+=" --terminal_a0_probe_all_return_queries_shadow"
COMMON_EXTRA+=" --topdown_route_map --hint_action_arbiter --hint_arbiter_min_relocalization_confidence=0.90"
COMMON_EXTRA+=" --route_local_map_icp_objective=point_to_point --route_local_map_voxel_size_m=0.10"
COMMON_EXTRA+=" --route_local_map_max_points=512 --route_local_map_profile=default"
COMMON_EXTRA+=" --route_local_map_quality_policy=diagnostic"
COMMON_EXTRA+=" --sequential_pair_promotion_mode=bounded_evidence --sequential_pair_promotion_window=5"
COMMON_EXTRA+=" --sequential_pair_promotion_min_votes=3 --sequential_pair_promotion_alias_aware"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_threshold=0.6 --sequential_pair_promotion_alias_window=8"
COMMON_EXTRA+=" --sequential_pair_promotion_alias_min_votes=5 --sequential_pair_promotion_alias_stall_attempts=200"
COMMON_EXTRA+=" --sequential_pair_promotion_use_pre_closure_estimates"
COMMON_EXTRA+=" --sequential_pair_short_baseline_disambiguation"
COMMON_EXTRA+=" --sequential_pair_short_baseline_min_travel_m=0.3"
COMMON_EXTRA+=" --sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0"
COMMON_EXTRA+=" --sequential_pair_disable_temporal_smoothing --sequential_pair_closure_check"
COMMON_EXTRA+=" --sequential_pair_closure_reconciliation_signal=bearing --sequential_pair_report_next_anchor"
COMMON_EXTRA+=" --sequential_pair_report_next_anchor_suppress_if_stale"
COMMON_EXTRA+=" --sequential_pair_anchor_geometry_source=accumulated --capture_icp_replay_dataset"
COMMON_EXTRA+=" --route_memory_capture_start_anchor_descriptor"
COMMON_EXTRA+=" --sequential_pair_reconstructed_confidence_source_one_hop"
COMMON_EXTRA+=" --reliability_v11_online --reliability_v11_runtime_root=${ROOT}"
COMMON_EXTRA+=" --reliability_v11_portable_artifact=${V11_ARTIFACT}"
COMMON_EXTRA+=" --reliability_v11_core_policy=${CORE_POLICY} --reliability_v11_core_mode=active"
COMMON_EXTRA+=" --reliability_v11_derived_evidence_mode=active"
COMMON_EXTRA+=" --reliability_v11_integrated_promotion_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_anchor_state_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_candidate_selector_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_candidate_controller_mode=off"
COMMON_EXTRA+=" --reliability_v11_active_scan_plan_mode=off"
COMMON_EXTRA+=" --reliability_v11_anchor_support_recovery_mode=off"
COMMON_EXTRA+=" --anchor_transition_guard_mode=shadow --anchor_transition_guard_runtime_root=${ROOT}"
COMMON_EXTRA+=" --anchor_transition_guard_model=${ANCHOR_MODEL}"
COMMON_EXTRA+=" --anchor_transition_guard_feature_root=${ROOT}/training/core_v1_src"
COMMON_EXTRA+=" --anchor_transition_guard_expected_sha256=${EXPECTED_ANCHOR_MODEL_SHA}"
COMMON_EXTRA+=" --anchor_transition_guard_confidence_threshold=0.90"
COMMON_EXTRA+=" --anchor_transition_guard_max_deferrals=2"
COMMON_EXTRA+=" --low_level_policy_log_root=${BENCH}/logs/rsl_rl"

static_preflight() {
  require_sha "${DRIVER}" "${EXPECTED_DRIVER_SHA}" || return
  require_sha "${EVALUATOR}" "${EXPECTED_EVALUATOR_SHA}" || return
  require_sha "${STOP_GATE}" "${EXPECTED_STOP_GATE_SHA}" || return
  require_sha "${PORTABLE_RUNTIME}" "${EXPECTED_PORTABLE_RUNTIME_SHA}" || return
  require_sha "${CORE_RUNTIME}" "${EXPECTED_CORE_RUNTIME_SHA}" || return
  require_sha "${CORE_POLICY}" "${EXPECTED_CORE_POLICY_SHA}" || return
  require_sha "${CORE_HINT_POLICY}" "${EXPECTED_HINT_POLICY_SHA}" || return
  require_sha "${VALIDATOR}" "${EXPECTED_VALIDATOR_SHA}" || return
  require_sha "${SCORER}" "${EXPECTED_SCORER_SHA}" || return
  require_sha "${EXPORTER}" "${EXPECTED_EXPORTER_SHA}" || return
  require_sha "${VERIFIER_FEATURES}" "${EXPECTED_VERIFIER_FEATURES_SHA}" || return
  require_sha "${ANCHOR_ONLINE}" "${EXPECTED_ANCHOR_ONLINE_SHA}" || return
  require_sha "${ANCHOR_GUARD}" "${EXPECTED_ANCHOR_GUARD_SHA}" || return
  require_sha "${ANCHOR_FEATURES}" "${EXPECTED_ANCHOR_FEATURES_SHA}" || return
  require_sha "${ANCHOR_MODEL}" "${EXPECTED_ANCHOR_MODEL_SHA}" || return
  require_sha "${TERMINAL_MODEL}" "${EXPECTED_TERMINAL_MODEL_SHA}" || return
  require_sha "${HINT_MODEL}" "${EXPECTED_HINT_MODEL_SHA}" || return
  require_sha "${V11_ARTIFACT}" "${EXPECTED_V11_ARTIFACT_SHA}" || return
  require_sha "${COHORT_LOCK}" "${EXPECTED_COHORT_LOCK_SHA}" || return
  require_sha "${COHORT_EVIDENCE}" "${EXPECTED_EVIDENCE_SHA}" || return
  require_sha "${DEV_MANIFEST}" "${EXPECTED_DEV_MANIFEST_SHA}" || return
  require_sha "${VALIDATION_MANIFEST}" "${EXPECTED_VALIDATION_MANIFEST_SHA}" || return
  bash -n "${DRIVER}" || return
  bash -n "$0" || return
  "${ISAAC_PYTHON}" -m py_compile \
    "${EVALUATOR}" "${STOP_GATE}" "${PORTABLE_RUNTIME}" "${CORE_RUNTIME}" \
    "${VALIDATOR}" "${SCORER}" "${EXPORTER}" "${ANCHOR_ONLINE}" "${ANCHOR_GUARD}" || return
  "${ISAAC_PYTHON}" - "${ROOT}" "${COHORT_LOCK}" "${DATASET}" <<'PY'
import csv, gzip, json, sys
from pathlib import Path
import joblib

root, lock_path, dataset_path = map(Path, sys.argv[1:])
lock = json.loads(lock_path.read_text(encoding="utf-8"))
assert lock["state"] == "sealed_before_execution"
assert lock["execution_authorized"] is False and lock["queue_authorized"] is False
assert lock["current_50_control_effect"] == "none"
with gzip.open(dataset_path, "rt", encoding="utf-8") as handle:
    episodes = json.load(handle)["episodes"]
all_ids = set()
for name, expected_count, role in (
    ("route2_core_development24.tsv", 24, "training_development"),
    ("route2_core_locked_validation20.tsv", 20, "locked_validation"),
):
    with (root / "manifest" / name).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == expected_count
    for row in rows:
        idx = int(row["episode_idx"])
        assert idx not in all_ids and row["cohort_role"] == role
        assert int(episodes[idx]["episode_id"]) == int(row["episode_id"])
        all_ids.add(idx)
for name, head in (
    ("anchor_transition_core_v1.joblib", "pose"),
    ("terminal_decision_core_v1.joblib", "distance"),
    ("hint_action_core_v1.joblib", "bearing"),
):
    bundle = joblib.load(root / "models/core_v1" / name)
    assert bundle["required_v11_head"] == head
    assert bundle["raw_icp_quality_authority"] is False
    status = bundle.get("integration_status", bundle.get("decision_policy", {}).get("integration_status"))
    assert status == "shadow_only"
PY
  case " ${COMMON_EXTRA} " in
    *" --reliability_v11_core_mode=active "*) ;;
    *) echo "FATAL: Reliability V1.1 core is not active" >&2; return 1 ;;
  esac
  case " ${COMMON_EXTRA} " in
    *" --anchor_transition_guard_mode=shadow "*) ;;
    *) echo "FATAL: retrained Anchor is not in shadow collection" >&2; return 1 ;;
  esac
  for forbidden in \
    "--reliability_v11_consumer_mode=off" \
    "--sequential_pair_reliability_distrust_downstream" \
    "--sequential_pair_reliability_demote_current"; do
    if [[ " ${COMMON_EXTRA} " == *" ${forbidden}"* ]]; then
      echo "FATAL forbidden Route-2 bypass: ${forbidden}" >&2
      return 1
    fi
  done
  echo "Route 2 core cohort static preflight PASS; no episode launched or queued"
}

launch_cohort() {
  local cohort="$1" manifest="$2" expected_count="$3"
  local run_tag="route2_core_${cohort}_20260801"
  local run_root="${ROOT}/runs/${run_tag}"
  local lock_file="/tmp/navila-route2-core-${cohort}-driver.lock"
  local failures=0
  local completed=0

  if pgrep -f '[r]ound_trip_eval.py' >/dev/null; then
    echo "FATAL: an evaluator is already running; refusing overlap. Nothing was stopped or queued." >&2
    return 76
  fi
  mkdir -p "${run_root}"
  cp "${manifest}" "${run_root}/manifest.tsv"
  cp "${COHORT_LOCK}" "${run_root}/cohort_lock.json"
  {
    echo "started=$(date -Is)"
    echo "scope=route2_only"
    echo "cohort=${cohort}"
    echo "episode_count=${expected_count}"
    echo "v11_core_mode=active"
    echo "anchor_core_v1_mode=shadow"
    echo "terminal_core_v1_mode=postepisode_shadow"
    echo "hint_core_v1_mode=postepisode_shadow"
    echo "current_50_control_effect=none"
  } > "${run_root}/provenance.txt"

  while IFS=$'\t' read -r episode_idx _rest; do
    if [[ "${episode_idx}" == "episode_idx" || -z "${episode_idx}" ]]; then
      continue
    fi
    local episode_tag="${run_tag}_ep${episode_idx}"
    if env \
      LOCK_FILE="${lock_file}" RUN_TAG="${run_tag}" PORT_BASE="${PORT_BASE}" \
      ONLY_EPISODES="${episode_idx}" EVAL_SCRIPT="${EVALUATOR}" \
      EPISODE_VALIDATOR="${VALIDATOR}" MANIFEST="${manifest}" \
      FAIL_FAST=1 REQUIRE_ALL_EPISODES=1 ROUTE_HINT_SOURCE=integrated \
      ROUTE_RELOCALIZATION_BACKEND=sequential_pair ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
      EXTRA_ISAAC_ARGS="${COMMON_EXTRA}" bash "${DRIVER}"; then
      local result_dir="${RESULT_PREFIX}_${episode_tag}"
      if ! "${ISAAC_PYTHON}" "${EXPORTER}" "${result_dir}" --arm "${cohort}_core_shadow" \
        >> "${run_root}/terminal_export.log" 2>&1; then
        failures=$((failures + 1))
        continue
      fi
      if ! "${ISAAC_PYTHON}" "${SCORER}" "${result_dir}" \
        >> "${run_root}/downstream_shadow_score.log" 2>&1; then
        failures=$((failures + 1))
        continue
      fi
      completed=$((completed + 1))
    else
      failures=$((failures + 1))
    fi
  done < "${manifest}"

  {
    echo "finished=$(date -Is)"
    echo "complete_episodes=${completed}"
    echo "failures=${failures}"
  } >> "${run_root}/provenance.txt"
  if [[ "${completed}" != "${expected_count}" || "${failures}" != "0" ]]; then
    echo "FATAL cohort incomplete completed=${completed}/${expected_count} failures=${failures}" >&2
    return 2
  fi
  touch "${run_root}/COMPLETED"
}

case "${1:-}" in
  "")
    static_preflight
    ;;
  --launch-development)
    static_preflight && launch_cohort development "${DEV_MANIFEST}" 24
    ;;
  --launch-locked-validation)
    static_preflight && launch_cohort locked_validation "${VALIDATION_MANIFEST}" 20
    ;;
  *)
    echo "Usage: $0 [--launch-development|--launch-locked-validation]" >&2
    exit 2
    ;;
esac
