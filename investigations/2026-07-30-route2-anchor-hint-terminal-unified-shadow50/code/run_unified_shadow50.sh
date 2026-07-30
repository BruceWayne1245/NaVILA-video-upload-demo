#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/teambruce/navila-unified-shadow50-20260730"
TRAINING_ROOT="/home/teambruce/navila-anchor-terminal-training-data-20260729"
EVAL_ROOT="${ROOT}/runtime_candidate"
RELIABILITY_ROOT="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728"
ANCHOR_MODEL="${TRAINING_ROOT}/models/v1/anchor_transition_v1.joblib"
ANCHOR_FEATURE_ROOT="${TRAINING_ROOT}/training"
ANCHOR_ONLINE="${ROOT}/reliability/anchor_transition_online.py"
ANCHOR_GUARD="${ROOT}/reliability/anchor_transition_promotion_guard.py"
ANCHOR_FEATURES="${ANCHOR_FEATURE_ROOT}/model_features.py"
BENCH="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
DATASET="${BENCH}/isaaclab_exts/omni.isaac.vlnce/assets/vln_ce_isaac_v1.json.gz"
BASE_DRIVER="${ROOT}/launch/run_manifest_batch_driver.sh"
EVAL_SCRIPT="${EVAL_ROOT}/scripts/round_trip_eval.py"
STOP_GATE="${EVAL_ROOT}/scripts/stop_gate.py"
RELIABILITY_ARTIFACT="${RELIABILITY_ROOT}/artifacts/reliability_v1_1_portable_shadow.json"
RELIABILITY_POLICY="${RELIABILITY_ROOT}/configs/v11_decision_shadow_v1.json"
MANIFEST="${ROOT}/manifest/unified50.tsv"
PRIOR_SHADOW="${TRAINING_ROOT}/runtime_shadow/three_model_shadow30.tsv"
SCORER="${ROOT}/scoring/score_episode.py"
TRAINING_EPISODES="${TRAINING_ROOT}/data/v1/episodes.jsonl"
TERMINAL_MODEL="${TRAINING_ROOT}/models/v2/terminal_decision_v2_robust.joblib"
HINT_MODEL="${TRAINING_ROOT}/models/v2/hint_action_decision_v2_binary.joblib"
HINT_POLICY="/home/teambruce/navila-hint-terminal-v3-safety-20260730/models/hint_recheck_policy_v3.json"
TERMINAL_ABLATION="${ROOT}/config/terminal_evidence_ablation_v1.json"
PROTOCOL="${ROOT}/config/unified50_protocol.json"
ISAAC_PYTHON="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
RUN_ROOT="${ROOT}/runs/unified_shadow50_retry1_20260730"
CANARY_TAG="unified_shadow50_ep670_replication_retry1_20260730"
BATCH_TAG="unified_shadow50_fresh49_retry1_20260730"
PORT_BASE=59000
CANARY_EPISODE=670
ALL_EPISODES="670 94 185 1037 479 555 757 61 122 426 476 106 353 1016 130 470 690 97 123 566 855 168 266 614 86 656 992 517 621 705 667 806 960 1001 1056 802 829 833 1003 186 246 449 763 343 383 1039 683 386 136 336"
BATCH_EPISODES="94 185 1037 479 555 757 61 122 426 476 106 353 1016 130 470 690 97 123 566 855 168 266 614 86 656 992 517 621 705 667 806 960 1001 1056 802 829 833 1003 186 246 449 763 343 383 1039 683 386 136 336"
RESULT_PREFIX="${BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"

EXPECTED_MANIFEST_SHA="4019465c954882b2190fe7ae01d9368c767e402cd75100053418b01a3cafbbfa"
EXPECTED_PRIOR_SHADOW_SHA="cf3c37470d29847bfc83a629ff2d1396b5e21dcc17d6186dc7de60fc233b4d27"
EXPECTED_SCORER_SHA="5e6c385befb98176e50fd87de9bb096989745c4cbc01aec1bdbdd595ae454434"
EXPECTED_TRAINING_EPISODES_SHA="7843df320f4de391788ae5884c36e65ba8e43e1fed458b259c966fc8605a7722"
EXPECTED_TERMINAL_SHA="f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb"
EXPECTED_HINT_V2_SHA="567e24aef5036e3310a36a8333ab8cc40ee467a293506973fa544fb1baa49603"
EXPECTED_HINT_POLICY_SHA="21035c66e2748e3bc54f34ee849c6020ab113bf86906a8ce4460d51d41ef26f5"
EXPECTED_TERMINAL_ABLATION_SHA="1fde99e000ee9ae0ee50705ee54ad45cca2f3f3baf54ce74c5ab45c0a4adc81e"
EXPECTED_DRIVER_SHA="87b19e7c78c0846530cebf4e5eeae053830a3774bb9ed8533be439bb3cf454a8"
EXPECTED_EVAL_SHA="fd44c2a485366205beccd37b1f471f68d81dd1b5a860a7b9ab7f634b74a866fe"
EXPECTED_STOP_GATE_SHA="37a372ab121f1d7766698ffc89db0e3fce7b7ede1d1680263a22ec7699f5f16b"
EXPECTED_RELIABILITY_ARTIFACT_SHA="3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a"
EXPECTED_RELIABILITY_POLICY_SHA="f4199af4559e3ba70c1bdf23a4342129e2260c4b2785c6c4033acb8e4b08684b"
EXPECTED_ANCHOR_MODEL_SHA="4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55"
EXPECTED_ANCHOR_ONLINE_SHA="62f626cfcf232cf6546f1a41a5b36f691479a4134d50edc24aa90319a5c08b29"
EXPECTED_ANCHOR_GUARD_SHA="8afa155ace32aac3c0971e297bdef22835a11c05e697e369b0ea49dce89f86d1"
EXPECTED_ANCHOR_FEATURES_SHA="ca3030a878e44038b4d9e8ed9be4fa56b7263d423eaed48e9be523edf76a95a1"
EXPECTED_PROTOCOL_SHA="a88d6ed95531590fcb7d51449d481484a6830ddad29b5b3dd517b01d7024d8c2"

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
  local require_gpu="${1:-1}"
  require_sha "${MANIFEST}" "${EXPECTED_MANIFEST_SHA}"
  require_sha "${PRIOR_SHADOW}" "${EXPECTED_PRIOR_SHADOW_SHA}"
  require_sha "${SCORER}" "${EXPECTED_SCORER_SHA}"
  require_sha "${TRAINING_EPISODES}" "${EXPECTED_TRAINING_EPISODES_SHA}"
  require_sha "${TERMINAL_MODEL}" "${EXPECTED_TERMINAL_SHA}"
  require_sha "${HINT_MODEL}" "${EXPECTED_HINT_V2_SHA}"
  require_sha "${HINT_POLICY}" "${EXPECTED_HINT_POLICY_SHA}"
  require_sha "${TERMINAL_ABLATION}" "${EXPECTED_TERMINAL_ABLATION_SHA}"
  require_sha "${PROTOCOL}" "${EXPECTED_PROTOCOL_SHA}"
  require_sha "${BASE_DRIVER}" "${EXPECTED_DRIVER_SHA}"
  require_sha "${EVAL_SCRIPT}" "${EXPECTED_EVAL_SHA}"
  require_sha "${STOP_GATE}" "${EXPECTED_STOP_GATE_SHA}"
  require_sha "${RELIABILITY_ARTIFACT}" "${EXPECTED_RELIABILITY_ARTIFACT_SHA}"
  require_sha "${RELIABILITY_POLICY}" "${EXPECTED_RELIABILITY_POLICY_SHA}"
  require_sha "${ANCHOR_MODEL}" "${EXPECTED_ANCHOR_MODEL_SHA}"
  require_sha "${ANCHOR_ONLINE}" "${EXPECTED_ANCHOR_ONLINE_SHA}"
  require_sha "${ANCHOR_GUARD}" "${EXPECTED_ANCHOR_GUARD_SHA}"
  require_sha "${ANCHOR_FEATURES}" "${EXPECTED_ANCHOR_FEATURES_SHA}"
  "${ISAAC_PYTHON}" - "${MANIFEST}" "${TRAINING_EPISODES}" "${PRIOR_SHADOW}" "${DATASET}" <<'PY'
import csv
import gzip
import hashlib
import json
import sys

manifest_path, training_path, prior_path, dataset_path = sys.argv[1:]
with open(manifest_path, newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
ids = [int(row["episode_idx"]) for row in rows]
training = {
    int(json.loads(line)["physical_episode_id"])
    for line in open(training_path, encoding="utf-8")
    if line.strip()
}
prior_five = {319, 498, 295, 430, 1008}
with open(prior_path, newline="", encoding="utf-8") as handle:
    prior_shadow = {
        int(row["episode_idx"])
        for row in csv.DictReader(handle, delimiter="\t")
    }
fresh = [row for row in rows if row["cohort_role"] == "fresh_validation"]
replication = [row for row in rows if row["cohort_role"] == "replication_only"]
fresh_ids = {int(row["episode_idx"]) for row in fresh}
assert len(rows) == 50
assert len(set(ids)) == 50
assert len(fresh) == 49
assert len(replication) == 1
assert int(replication[0]["episode_idx"]) == 670
assert not (fresh_ids & training), sorted(fresh_ids & training)
assert not (fresh_ids & prior_five), sorted(fresh_ids & prior_five)
assert not (fresh_ids & prior_shadow), sorted(fresh_ids & prior_shadow)
assert not (fresh_ids & {49, 953})
assert len({row["scene"] for row in fresh}) == 8
assert len({row["geometry_sha256"] for row in fresh}) == 49
assert all(float(row["baseline_distance_to_start"]) > 3.35 for row in fresh)
assert max(59000 + episode for episode in ids) <= 65535
with gzip.open(dataset_path, "rt", encoding="utf-8") as handle:
    episodes = json.load(handle)["episodes"]
for row in rows:
    episode = episodes[int(row["episode_idx"])]
    neighbor = episodes[int(row["neighbor_idx"])]
    assert int(episode["episode_id"]) == int(row["episode_id"])
    assert int(neighbor["episode_id"]) == int(row["neighbor_episode_id"])
    scene = episode["scene_id"].split("/")[-2]
    assert scene == row["scene"]
    normalized = [
        [round(float(value), 3) for value in point]
        for point in episode["reference_path"]
    ]
    digest = hashlib.sha256(
        json.dumps(normalized, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == row["geometry_sha256"]
PY
  "${ISAAC_PYTHON}" -m py_compile "${SCORER}" "${EVAL_SCRIPT}" "${STOP_GATE}"
  bash -n "${BASE_DRIVER}"
  if (( require_gpu == 0 )); then
    log "static preflight PASS: frozen 49 fresh + ep670 replication"
    return 0
  fi
  local free_mib
  free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
  if (( free_mib < 12000 )); then
    log "FATAL GPU free memory ${free_mib}MiB < 12000MiB"
    return 1
  fi
  log "preflight PASS: 49 fresh + ep670, 8 scenes, all consumers off"
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
COMMON_EXTRA+=" --reliability_v11_runtime_root=${RELIABILITY_ROOT}"
COMMON_EXTRA+=" --reliability_v11_portable_artifact=${RELIABILITY_ARTIFACT}"
COMMON_EXTRA+=" --reliability_v11_decision_shadow"
COMMON_EXTRA+=" --reliability_v11_decision_policy=${RELIABILITY_POLICY}"
COMMON_EXTRA+=" --reliability_v11_consumer_mode=off"
COMMON_EXTRA+=" --reliability_v11_derived_evidence_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_promotion_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_anchor_state_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_candidate_selector_mode=off"
COMMON_EXTRA+=" --reliability_v11_integrated_candidate_controller_mode=off"
COMMON_EXTRA+=" --reliability_v11_active_scan_plan_mode=off"
COMMON_EXTRA+=" --reliability_v11_anchor_support_recovery_mode=off"
COMMON_EXTRA+=" --anchor_transition_guard_mode=shadow"
COMMON_EXTRA+=" --anchor_transition_guard_runtime_root=${ROOT}"
COMMON_EXTRA+=" --anchor_transition_guard_model=${ANCHOR_MODEL}"
COMMON_EXTRA+=" --anchor_transition_guard_feature_root=${ANCHOR_FEATURE_ROOT}"
COMMON_EXTRA+=" --anchor_transition_guard_expected_sha256=${EXPECTED_ANCHOR_MODEL_SHA}"
COMMON_EXTRA+=" --anchor_transition_guard_confidence_threshold=0.90"
COMMON_EXTRA+=" --anchor_transition_guard_max_deferrals=2"
COMMON_EXTRA+=" --low_level_policy_log_root=${BENCH}/logs/rsl_rl"

run_driver() {
  local tag="$1"
  local episodes="$2"
  log "launching evaluator tag=${tag} episodes=${episodes}"
  RUN_TAG="${tag}" \
  PORT_BASE="${PORT_BASE}" \
  ONLY_EPISODES="${episodes}" \
  EVAL_SCRIPT="${EVAL_SCRIPT}" \
  MANIFEST="${MANIFEST}" \
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
  cp "${MANIFEST}" "${RUN_ROOT}/unified50.tsv"
  {
    echo "created=$(date -Is)"
    echo "mode=anchor_v1_shadow_plus_postepisode_hint_terminal"
    echo "control_effect=none"
    echo "github_authoritative_commit=a1d50470ccc9c522d95ed76646ce10f6d3c04684"
    echo "canary_tag=${CANARY_TAG}"
    echo "batch_tag=${BATCH_TAG}"
    echo "episodes=${ALL_EPISODES}"
    echo "manifest_sha256=${EXPECTED_MANIFEST_SHA}"
    echo "scorer_sha256=${EXPECTED_SCORER_SHA}"
    echo "terminal_sha256=${EXPECTED_TERMINAL_SHA}"
    echo "hint_v2_sha256=${EXPECTED_HINT_V2_SHA}"
    echo "hint_policy_sha256=${EXPECTED_HINT_POLICY_SHA}"
    echo "terminal_ablation_sha256=${EXPECTED_TERMINAL_ABLATION_SHA}"
    echo "round_trip_eval_sha256=${EXPECTED_EVAL_SHA}"
    echo "stop_gate_sha256=${EXPECTED_STOP_GATE_SHA}"
    echo "reliability_artifact_sha256=${EXPECTED_RELIABILITY_ARTIFACT_SHA}"
    echo "reliability_policy_sha256=${EXPECTED_RELIABILITY_POLICY_SHA}"
    echo "anchor_model_sha256=${EXPECTED_ANCHOR_MODEL_SHA}"
    echo "anchor_online_sha256=${EXPECTED_ANCHOR_ONLINE_SHA}"
    echo "anchor_guard_sha256=${EXPECTED_ANCHOR_GUARD_SHA}"
    echo "anchor_features_sha256=${EXPECTED_ANCHOR_FEATURES_SHA}"
    echo "protocol_sha256=${EXPECTED_PROTOCOL_SHA}"
  } > "${RUN_ROOT}/provenance.txt"
}

if [[ "${1:-}" == "--static-preflight-only" ]]; then
  preflight 0
  exit 0
fi

if [[ "${1:-}" == "--preflight-only" ]]; then
  preflight 1
  exit 0
fi

preflight 1
write_provenance
log "starting canary ep=${CANARY_EPISODE}"
run_driver "${CANARY_TAG}" "${CANARY_EPISODE}"
"${ISAAC_PYTHON}" - \
  "${RESULT_PREFIX}_${CANARY_TAG}_ep${CANARY_EPISODE}" \
  "${EXPECTED_ANCHOR_MODEL_SHA}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected_anchor_sha = sys.argv[2]
completion = json.loads(
    (root / "capture_completion.json").read_text(encoding="utf-8")
)
assert completion["complete"] is True
assert int(completion["physical_episode_id"]) == 670
measurement_path = root / completion["measurement"]["path"]
trajectory_path = root / completion["trajectory"]["path"]
assert measurement_path.is_file()
assert trajectory_path.is_file()
assert int(completion["trajectory"]["rows"]) > 0
assert hashlib.sha256(measurement_path.read_bytes()).hexdigest() == (
    completion["measurement"]["sha256"]
)
measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
round_trip = measurement["round_trip"]
v11 = round_trip["reliability_v11_online_shadow"]
consumer = round_trip["reliability_v11_consumer_policy_v2"]
anchor = round_trip["anchor_transition_promotion_guard"]
assert v11["enabled"] is True
assert v11["enforcement_enabled"] is False
assert v11["controller_effect"] is False
assert consumer["enabled"] is False
assert consumer["mode"] == "off"
assert anchor["enabled"] is True
assert anchor["mode"] == "shadow"
assert anchor["controller_effects"] == 0
assert anchor["model_sha256"] == expected_anchor_sha
anchor_log = root / "anchor_transition_guard.jsonl"
assert anchor_log.is_file()
events = [
    json.loads(line)
    for line in anchor_log.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
assert events[0]["event"] == "anchor_transition_guard_session_start"
assert events[-1]["event"] == "anchor_transition_guard_session_end"
PY
log "ep670 replication infrastructure PASS; starting fresh49"
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
log "unified shadow50 finished score_failures=${score_failures}"
