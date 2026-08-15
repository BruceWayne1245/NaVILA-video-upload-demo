#!/usr/bin/env bash
set -u

# 2026-08-15 -- copied from
# run_line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813.sh (stopped
# mid-run today by explicit user instruction after this session's closure_check
# investigation -- see investigations/2026-08-14-closure-check-cooldown-and-
# disable-decision/ once pushed). Three changes vs that script, all applied
# together per explicit user instruction (not a controlled A/B -- time-
# constrained tonight, control-variable isolation deliberately skipped):
#   1. --sequential_pair_closure_cooldown_attempts=20 ADDED (new flag, off by
#      default elsewhere in the codebase -- see route_memory_agent.py's
#      sequential_pair_closure_cooldown_attempts docstring, 2026-08-14).
#   2. --sequential_pair_closure_check and --sequential_pair_closure_reconciliation_signal
#      REMOVED entirely (closure precheck disabled) -- survey across this
#      batch + the 2026-08-04 30ep 7/10 batch + the 50ep_historical_outbound
#      batch found 51-67% of outbound-success episodes hit a long
#      "current pinned on one anchor, ambiguity/anomaly gates both quiet"
#      stuck window; hand-verified on ep517 (this batch) and ep4 (2026-08-04
#      batch) that closure_reject_veto is the actual blocker in both, via two
#      different concrete sub-causes (edge-geometry heading mismatch;
#      marginal position-disagreement noise at the 0.75m threshold). Real
#      redundant protection against what closure was built to catch (a bad
#      ICP read causing overshoot/premature-stop) still stands:
#      --sequential_pair_short_baseline_disambiguation (temporal self-
#      consistency cross-check) and --stop_gate_anchor_corroboration /
#      --stop_gate_require_cross_role_agreement (last-line defense at the
#      actual stop decision) are both still enabled below, unchanged.
#   3. scripts/relocalization.py's _nearest_neighbor_2d() now uses
#      scipy.spatial.cKDTree instead of brute-force O(N*M) search (2026-08-15,
#      implementing the previously-proposed-but-unimplemented
#      investigations/2026-08-11-.../ICP_PERFORMANCE_AND_KDTREE_PROPOSAL.md).
#      Exact (not approximate) nearest-neighbor -- verified numerically
#      identical to the old brute-force output (max diff ~5e-7, float32
#      rounding only) across 20 random trials up to 512x512 points, ~27x
#      faster at that size. Applies automatically (shared module), not a CLI
#      flag -- no line below reflects this change directly.
# Episode order also reshuffled vs the source script: the 20 episodes with the
# longest observed "stuck window" in the closure-check survey above are moved
# to the front of the queue (same 100-episode set, not a different manifest),
# so tonight's overnight run surfaces closure's effect (or lack of one) in the
# first ~20 episodes rather than possibly episode 80+.
#
# 2026-08-13 -- Route1 "line2_stopgate_redesign" config (the 2026-08-04 30ep batch that
# hit 70.0% return-rate, 7/10, on reliable30v3's 10-outbound-success cohort -- the
# project's highest-verified non-oracle-hint result, and the only non-oracle candidate
# confirmed to still be running on today's live code: stop_gate.py/route_memory_agent.py/
# hint_action_arbiter.py all last modified 2026-08-04, before this batch's source run, and
# never touched since; round_trip_eval.py's only post-batch change is a diagnostic-logging
# -only patch (LOOP_EXIT/MEASUREMENT_WRITE prints), no logic change -- see this session's
# code-integrity check).
#
# Route2's Anchor V2/V3 controller-model alternatives were checked and rejected as
# candidates: no git history exists for that codebase at all (not a git repo), the one
# seemingly-good number (66.7%/10-15, 2026-08-03) was measured on the PRE-fix buggy
# controller (its own write-up says "尚未以修复后的代码重跑"), and every batch actually run
# on the FIXED controller since then did worse -- recovery10 (08-04) 10/10 infra failures,
# recoveryfix30_rerun2 (08-07) only 6/20=30.0%, anchor_v3_active_30ep (08-11) 0 controller
# triggers. No better/earlier working Route2 version exists to fall back on.
#
# Same flag set as investigations/2026-08-04-stopgate-redesign-and-line2-30ep-retrospective/
# code/run_line2_stopgate_redesign_30ep_20260804.sh (via
# run_promotion_shadow_reliable30v3_driver_20260731.sh) -- the episode manifest is
# swapped from the 30ep reliable30v3 cohort to the same high-outbound-success
# 100-episode sample used for the just-finished oracle_hint -> oracle_hint_action ->
# oracle_hint_action+stop_gate ablation chain (investigations/数据补全/), so this is a
# direct episode-for-episode non-oracle comparison against that chain's step 3
# (pure_oracle_hint_action_stopgate_highsuccess100ep_20260813, 71/87=81.6%).
#
# 2026-08-13, NO-YAW-ALIGN VARIANT (per explicit user instruction): unlike
# run_line2_stopgate_redesign_highsuccess100ep_20260813.sh (which kept
# --oracle_align_return_yaw_to_anchor_segment, matching the source 08-04 batch's
# default), this run enables NEITHER --oracle_align_return_yaw_to_anchor_segment NOR
# the new --icp_align_return_yaw_to_anchor_segment (see
# investigations/2026-08-13-icp-return-yaw-alignment/FINDINGS.md for that mechanism).
# Return-phase heading is whatever the robot naturally has after outbound ends -- no
# yaw correction of any kind, oracle or self-driven. This is the genuinely
# yaw-signal-free arm; per this session's audit, no batch in this project's history
# has ever been run this way at scale before.

ROOT="/mnt/SSD4T/teambruce/projects/navila-isaac"
BENCH="${ROOT}/NaVILA-Bench"
ISAACLAB="${ROOT}/IsaacLab/isaaclab.sh"
CONDA="/home/teambruce/miniconda3/bin/conda"
VLM_ENV="/mnt/SSD4T/teambruce/conda_envs/navila-vlm"
ISAAC_ENV="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac"
MODEL_PATH="${ROOT}/checkpoints/navila-llama3-8b-8f"
PORT_BASE="${PORT_BASE:-62000}"
PORT="${PORT:-62000}"
RUN_TAG="${RUN_TAG:-line2_closure_off_cooldown_kdtree_100ep_20260815}"
START_AT="${START_AT:-0}"
ONLY_EPISODES="${ONLY_EPISODES:-}"
EPISODE_TIMEOUT_SECONDS="${EPISODE_TIMEOUT_SECONDS:-7200}"
EPISODE_TIMEOUT_KILL_AFTER_SECONDS="${EPISODE_TIMEOUT_KILL_AFTER_SECONDS:-300}"
LOG_DIR="${BENCH}/batch_logs/${RUN_TAG}"
SUMMARY="${LOG_DIR}/summary.tsv"

# --- 2026-08-04 line2 stop_gate/route_memory_agent redesign flag set, verbatim from
# run_line2_stopgate_redesign_30ep_20260804.sh's COMMON_EXTRA (the 70.0% batch) ---
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
COMMON_EXTRA+=" --sequential_pair_promotion_window=5"
COMMON_EXTRA+=" --sequential_pair_promotion_min_votes=3"
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
# 2026-08-15: closure_check REMOVED (see header) -- was
# "--sequential_pair_closure_check --sequential_pair_closure_reconciliation_signal=bearing".
# Cooldown flag kept even though closure is off (harmless no-op while it's
# disabled -- the gate lives inside _sequential_pair_closure_precheck, which
# early-returns before reaching it whenever closure_check_enabled is False --
# so it's ready if closure ever gets re-enabled later without needing to
# remember to re-add this).
COMMON_EXTRA+=" --sequential_pair_closure_cooldown_attempts=20"
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
COMMON_EXTRA+=" --sequential_pair_loftr_rear_yaw_check"
COMMON_EXTRA+=" --sequential_pair_vision_disagreement_mode=downgrade --sequential_pair_vision_disagreement_confidence_penalty=0.3"
# --- 2026-08-03 line-2 Phase 0.2 / 1.1 / 1.2 (carried forward unchanged) ---
COMMON_EXTRA+=" --sequential_pair_evict_unreliable_current --current_evict_stall_attempts=30"
COMMON_EXTRA+=" --sequential_pair_promotion_ambiguity_gate --sequential_pair_promotion_min_confidence=0.35"
COMMON_EXTRA+=" --hint_action_arbiter_stop_veto --hint_action_arbiter_stop_veto_min_confidence=0.5"
COMMON_EXTRA+=" --hint_action_arbiter_stop_veto_anchor_remaining_min_m=3.0"
# --- 2026-08-04 stop_gate redesign additions (all 6) ---
COMMON_EXTRA+=" --stop_gate_corroboration_overrides_low_reliability"
COMMON_EXTRA+=" --current_evict_mode=window --current_evict_window=40 --current_evict_min_votes=30"
COMMON_EXTRA+=" --sequential_pair_promotion_anomaly_gate"
COMMON_EXTRA+=" --sequential_pair_promotion_anomaly_max_bearing_jump_deg=90"
COMMON_EXTRA+=" --sequential_pair_promotion_anomaly_max_collapse_m=1.5"
COMMON_EXTRA+=" --sequential_pair_stale_relocalization_distrust --stale_relocalization_max_attempts=30"
COMMON_EXTRA+=" --sequential_pair_relocalization_uncertainty_mode=growing --stale_uncertainty_base_floor_m=0.35"
COMMON_EXTRA+=" --stop_gate_use_uncertainty_interval"
COMMON_EXTRA+=" --stop_gate_blind_budget --stop_gate_blind_budget_max_attempts=8"
COMMON_EXTRA+=" --stop_gate_require_cross_role_agreement --stop_gate_cross_role_max_disagreement_m=1.5"

mkdir -p "${LOG_DIR}"

if [[ ! -f "${SUMMARY}" ]]; then
  cat > "${SUMMARY}" <<'EOF'
episode_idx	episode_id	scene	neighbor_idx	neighbor_episode_id	matched_waypoints	mean_distance	baseline_distance_to_start	vlm_port	start_time	end_time	exit_code	result_suffix	vlm_log	eval_log	measurement_file	outbound_success	return_success	round_trip_success	distance_to_start	outbound_stop_distance_to_goal	trajectory_record_count
EOF
fi

kill_process_group() {
  local pid="$1"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
    sleep 5
  fi
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill -9 -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
    sleep 2
  fi
}

port_is_listening() {
  ss -tln 2>/dev/null | grep -q ":${PORT} "
}

wait_for_port_open() {
  local deadline=$((SECONDS + 900))
  while (( SECONDS < deadline )); do
    if port_is_listening; then
      return 0
    fi
    if [[ -n "${VLM_PID:-}" ]] && ! kill -0 "${VLM_PID}" 2>/dev/null; then
      return 1
    fi
    sleep 2
  done
  return 1
}

wait_for_port_closed() {
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    if ! port_is_listening; then
      return 0
    fi
    sleep 2
  done
  return 1
}

stop_existing_vlm_server() {
  local pids
  pids="$(pgrep -f "scripts/vlm_server.py.*--port ${PORT}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping pre-existing vlm_server.py on port ${PORT}: ${pids}" | tee -a "${LOG_DIR}/batch.log"
    while read -r pid; do
      [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
    done <<< "${pids}"
    sleep 10
  fi
}

start_vlm_server() {
  local vlm_log="$1"
  stop_existing_vlm_server
  if port_is_listening; then
    echo "Port ${PORT} is still busy before VLM startup; refusing to reuse an existing server." | tee -a "${vlm_log}"
    return 1
  fi

  cd "${BENCH}" || return 99
  setsid "${CONDA}" run \
    --prefix "${VLM_ENV}" \
    python "${BENCH}/scripts/vlm_server.py" \
    --model_path "${MODEL_PATH}" \
    --port "${PORT}" \
    --load_8bit \
    >> "${vlm_log}" 2>&1 &
  VLM_PID="$!"

  if ! wait_for_port_open; then
    echo "Timed out waiting for VLM server on port ${PORT}" | tee -a "${vlm_log}"
    kill_process_group "${VLM_PID}"
    return 1
  fi
  echo "VLM server ready on port ${PORT}, pid=${VLM_PID}" | tee -a "${vlm_log}"
  return 0
}

extract_measurement_summary() {
  local suffix="$1"
  python3 - "${BENCH}" "${suffix}" <<'PY'
import glob
import json
import os
import sys

bench, suffix = sys.argv[1], sys.argv[2]
pattern = os.path.join(
    bench,
    "eval_results",
    f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{suffix}",
    "measurements",
    "*.json",
)
matches = sorted(glob.glob(pattern), key=os.path.getmtime)
if not matches:
    print("\t".join(["", "", "", "", "", "", ""]))
    raise SystemExit(0)

path = matches[-1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
rt = data.get("round_trip", {})
print("\t".join([
    path,
    str(rt.get("outbound_success", "")),
    str(rt.get("return_success", "")),
    str(rt.get("round_trip_success", "")),
    str(rt.get("distance_to_start", "")),
    str(rt.get("outbound_stop_distance_to_goal", "")),
    str(rt.get("trajectory_record_count", "")),
]))
PY
}

run_episode() {
  local ep_idx="$1"
  local ep_id="$2"
  local scene="$3"
  local neighbor_idx="$4"
  local neighbor_ep_id="$5"
  local matched="$6"
  local mean_distance="$7"
  local baseline_distance="$8"
  local suffix="${RUN_TAG}_ep${ep_idx}"
  local vlm_log="${LOG_DIR}/ep${ep_idx}_vlm.log"
  local eval_log="${LOG_DIR}/ep${ep_idx}_eval.log"
  local start_time
  local end_time
  local exit_code
  local eval_pid=""
  local parsed

  if (( ep_idx < START_AT )); then
    echo "Skipping episode ${ep_idx}; START_AT=${START_AT}" | tee -a "${LOG_DIR}/batch.log"
    return 0
  fi
  if [[ -n "${ONLY_EPISODES}" && " ${ONLY_EPISODES} " != *" ${ep_idx} "* ]]; then
    echo "Skipping episode ${ep_idx}; ONLY_EPISODES=${ONLY_EPISODES}" | tee -a "${LOG_DIR}/batch.log"
    return 0
  fi

  PORT="$((PORT_BASE + ep_idx))"
  VLM_PID=""
  start_time="$(date -Is)"
  echo "[$start_time] starting episode ${ep_idx} (${scene}), port=${PORT}, suffix=${suffix}" | tee -a "${LOG_DIR}/batch.log"

  if start_vlm_server "${vlm_log}"; then
    cd "${BENCH}" || exit_code=99
    if [[ -z "${exit_code:-}" ]]; then
      setsid timeout --kill-after="${EPISODE_TIMEOUT_KILL_AFTER_SECONDS}s" "${EPISODE_TIMEOUT_SECONDS}s" \
        env TERM=xterm OMNI_KIT_ACCEPT_EULA=YES "${CONDA}" run \
        --no-capture-output \
        --prefix "${ISAAC_ENV}" \
        "${ISAACLAB}" -p \
        scripts/round_trip_eval.py \
        --task=go2_matterport_vision \
        --num_envs=1 \
        --history_length=9 \
        --load_run=2024-09-25_23-22-02 \
        --headless \
        --enable_cameras \
        --round_trip_mode=phase_prompt \
        --instruction_rewriter_provider=cache_only \
        --vlm_port="${PORT}" \
        --episode_idx="${ep_idx}" \
        --result_suffix="${suffix}" \
        --route_memory \
        --route_hint_mode=compact \
        --route_hint_source=integrated \
        --route_relocalization_backend=sequential_pair \
        ${COMMON_EXTRA} \
        >> "${eval_log}" 2>&1 &
      eval_pid="$!"
      wait "${eval_pid}"
      exit_code="$?"
      kill_process_group "${eval_pid}"
      if [[ "${exit_code}" == "124" || "${exit_code}" == "137" ]]; then
        echo "Episode ${ep_idx} timed out after ${EPISODE_TIMEOUT_SECONDS}s; continuing to next episode." | tee -a "${LOG_DIR}/batch.log" "${eval_log}"
      fi
    fi
  else
    exit_code=98
  fi

  kill_process_group "${eval_pid}"
  kill_process_group "${VLM_PID}"
  wait_for_port_closed || echo "Warning: port ${PORT} still appears busy after episode ${ep_idx}" | tee -a "${LOG_DIR}/batch.log"
  sleep 15

  end_time="$(date -Is)"
  parsed="$(extract_measurement_summary "${suffix}")"
  measurement_retry=0
  while [[ -z "$(cut -f1 <<<"${parsed}")" && "${measurement_retry}" -lt 10 ]]; do
    sleep 2
    parsed="$(extract_measurement_summary "${suffix}")"
    measurement_retry=$((measurement_retry + 1))
  done
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${ep_idx}" "${ep_id}" "${scene}" "${neighbor_idx}" "${neighbor_ep_id}" \
    "${matched}" "${mean_distance}" "${baseline_distance}" "${PORT}" "${start_time}" \
    "${end_time}" "${exit_code}" "${suffix}" "${vlm_log}" "${eval_log}" "${parsed}" \
    >> "${SUMMARY}"
  echo "[$end_time] finished episode ${ep_idx}, exit_code=${exit_code}" | tee -a "${LOG_DIR}/batch.log"
  unset exit_code
}

main() {
  echo "Batch started at $(date -Is)" | tee "${LOG_DIR}/batch.log"
  echo "RUN_TAG=${RUN_TAG}" | tee -a "${LOG_DIR}/batch.log"
  echo "line2_stopgate_redesign config (2026-08-04's 70.0% flag set) on the high-outbound-success 100ep manifest, replacing route_hint_source=oracle/route_relocalization_backend=none with integrated/sequential_pair (self-driven). NO-YAW-ALIGN VARIANT: neither --oracle_align_return_yaw_to_anchor_segment nor --icp_align_return_yaw_to_anchor_segment is enabled -- return-phase heading gets no correction of any kind. Non-oracle, yaw-signal-free comparison arm for investigations/数据补全/'s oracle ablation chain step 3." | tee -a "${LOG_DIR}/batch.log"
  echo "Extra Isaac args: ${COMMON_EXTRA}" | tee -a "${LOG_DIR}/batch.log"

  # Same 100-episode high-outbound-success manifest as
  # pure_oracle_hint_action_stopgate_highsuccess100ep_20260813 (and steps 1-2), ranked by
  # historical outbound_success rate (high to low, ties broken by attempt count).
  run_episode 806 1368 TbHJrupSAjP 966 1648 5 0.702683 8.977993
  run_episode 470 798 QUCTc6BB5sX 546 943 5 0.662972 10.232210
  run_episode 646 1118 x8F5xyUWy9e 354 583 4 0.475011 8.570651
  run_episode 889 1517 EU6Fwq7SyZv 276 442 4 1.213044 8.345141
  run_episode 517 899 zsNo4HB9uLZ 726 1240 4 0.684778 7.519623
  run_episode 95 141 2azQ1b91cZZ 579 1006 5 0.000000 13.368412
  run_episode 324 523 TbHJrupSAjP 615 1075 4 1.103096 10.936766
  run_episode 961 1643 TbHJrupSAjP 291 472 4 0.315807 6.949306
  run_episode 962 1644 TbHJrupSAjP 291 472 4 0.315807 6.949306
  run_episode 844 1439 zsNo4HB9uLZ 882 1501 5 0.000000 6.517529
  run_episode 555 958 2azQ1b91cZZ 177 262 5 0.151484 7.823619
  run_episode 669 1153 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 670 1154 X7HyMhZNoso 681 1168 5 0.000000 3.276791
  run_episode 367 602 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 579 1006 2azQ1b91cZZ 93 139 5 0.000000 13.760632
  run_episode 484 827 zsNo4HB9uLZ 810 1375 4 0.000000 7.025259
  run_episode 5 9 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 696 1189 2azQ1b91cZZ 120 166 5 0.333557 10.149185
  run_episode 88 128 EU6Fwq7SyZv 288 460 5 1.348777 2.292637
  run_episode 534 922 zsNo4HB9uLZ 840 1435 5 0.750029 4.674335
  run_episode 647 1119 x8F5xyUWy9e 354 583 4 0.475000 8.374983
  run_episode 89 129 EU6Fwq7SyZv 288 460 5 1.349000 2.292637
  run_episode 268 422 QUCTc6BB5sX 435 739 6 0.000000 8.807060
  run_episode 1038 1759 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 205 314 2azQ1b91cZZ 807 1372 0 0.000000 0.000000
  run_episode 671 1155 X7HyMhZNoso 681 1168 0 0.000000 0.000000
  run_episode 688 1178 X7HyMhZNoso 783 1336 4 0.000000 5.328553
  run_episode 319 512 2azQ1b91cZZ 429 721 4 0.000000 2.920037
  run_episode 264 418 zsNo4HB9uLZ 639 1108 6 0.000000 12.458867
  run_episode 658 1139 QUCTc6BB5sX 660 1141 5 0.000000 7.587837
  run_episode 310 500 QUCTc6BB5sX 792 1351 5 0.368796 9.363973
  run_episode 351 577 QUCTc6BB5sX 105 151 5 0.000000 14.125214
  run_episode 539 930 TbHJrupSAjP 198 307 7 1.519046 7.633810
  run_episode 581 1008 2azQ1b91cZZ 93 139 5 0.000000 13.760632
  run_episode 366 601 X7HyMhZNoso 1038 1759 7 0.000000 9.774121
  run_episode 490 854 X7HyMhZNoso 1038 1759 6 0.190970 8.881821
  run_episode 888 1516 EU6Fwq7SyZv 276 442 4 1.213044 8.710791
  run_episode 815 1380 x8F5xyUWy9e 951 1633 4 0.830905 5.487870
  run_episode 20 33 x8F5xyUWy9e 135 199 4 1.070148 4.718646
  run_episode 813 1378 x8F5xyUWy9e 951 1633 4 0.830905 4.214828
  run_episode 189 286 2azQ1b91cZZ 696 1189 4 0.000000 6.937679
  run_episode 783 1336 X7HyMhZNoso 687 1177 4 0.960138 7.436316
  run_episode 784 1337 X7HyMhZNoso 687 1177 4 0.960138 7.972808
  run_episode 785 1338 X7HyMhZNoso 687 1177 4 0.960138 7.768569
  run_episode 1004 1713 TbHJrupSAjP 585 1018 4 0.315807 4.023420
  run_episode 1062 1801 2azQ1b91cZZ 930 1579 5 0.278728 9.902829
  run_episode 86 126 zsNo4HB9uLZ 942 1612 5 0.215112 12.411028
  run_episode 271 428 QUCTc6BB5sX 66 94 6 0.244698 15.260509
  run_episode 479 810 2azQ1b91cZZ 816 1381 5 0.918991 7.632172
  run_episode 656 1137 zsNo4HB9uLZ 984 1681 6 0.000000 10.837272
  run_episode 814 1379 x8F5xyUWy9e 951 1633 4 0.830905 5.487870
  run_episode 829 1406 TbHJrupSAjP 225 358 5 0.000000 8.322788
  run_episode 18 31 x8F5xyUWy9e 135 199 4 1.070148 6.361872
  run_episode 97 143 QUCTc6BB5sX 855 1462 5 0.000000 4.898193
  run_episode 226 359 TbHJrupSAjP 747 1279 5 0.313656 11.091585
  run_episode 228 361 zsNo4HB9uLZ 990 1690 4 0.000000 10.026331
  run_episode 233 366 2azQ1b91cZZ 132 193 6 0.000000 7.469688
  run_episode 266 420 zsNo4HB9uLZ 639 1108 6 0.000000 12.458868
  run_episode 291 472 TbHJrupSAjP 255 406 6 0.000000 10.362745
  run_episode 304 494 2azQ1b91cZZ 177 262 4 0.712771 7.766384
  run_episode 353 579 QUCTc6BB5sX 105 151 5 0.000000 11.832883
  run_episode 376 629 zsNo4HB9uLZ 534 922 5 1.661286 7.809501
  run_episode 426 718 2azQ1b91cZZ 756 1288 5 0.853292 4.718741
  run_episode 428 720 2azQ1b91cZZ 756 1288 5 0.853292 5.156441
  run_episode 463 785 QUCTc6BB5sX 657 1138 5 1.651042 8.700310
  run_episode 476 807 2azQ1b91cZZ 144 214 4 1.355172 5.492750
  run_episode 566 978 QUCTc6BB5sX 396 664 4 0.000000 5.330832
  run_episode 621 1084 zsNo4HB9uLZ 771 1321 4 0.444923 3.827381
  run_episode 645 1117 x8F5xyUWy9e 354 583 4 0.475011 8.570651
  run_episode 679 1166 zsNo4HB9uLZ 612 1069 7 0.000 1.995
  run_episode 705 1198 zsNo4HB9uLZ 0 1 5 0.000000 4.938268
  run_episode 733 1256 2azQ1b91cZZ 111 157 5 1.022231 9.430092
  run_episode 738 1264 2azQ1b91cZZ 183 277 6 0.000000 13.536292
  run_episode 833 1419 TbHJrupSAjP 615 1075 5 0.650377 5.938150
  run_episode 885 1513 QUCTc6BB5sX 462 784 5 0.000000 10.728850
  run_episode 895 1523 zsNo4HB9uLZ 882 1501 4 1.209300 5.070233
  run_episode 960 1642 TbHJrupSAjP 291 472 4 0.315807 6.593922
  run_episode 993 1699 QUCTc6BB5sX 105 151 7 0.000 1.994
  run_episode 1002 1711 TbHJrupSAjP 585 1018 4 0.315807 4.023420
  run_episode 1003 1712 TbHJrupSAjP 585 1018 4 0.315807 4.023420
  run_episode 4 8 x8F5xyUWy9e 354 583 5 0.000000 10.248705
  run_episode 994 1700 QUCTc6BB5sX 105 151 7 0.000000 12.657429
  run_episode 368 603 X7HyMhZNoso 1038 1759 7 0.000000 6.916351
  run_episode 295 476 zsNo4HB9uLZ 45 73 4 0.000000 8.425889
  run_episode 1040 1761 X7HyMhZNoso 366 601 7 0.000000 6.916351
  run_episode 276 442 EU6Fwq7SyZv 888 1516 4 0.261469 11.290769
  run_episode 427 719 2azQ1b91cZZ 756 1288 5 0.853292 5.156441
  run_episode 680 1167 zsNo4HB9uLZ 612 1069 7 0.000000 12.981381
  run_episode 19 32 x8F5xyUWy9e 135 199 4 1.070148 6.361872
  run_episode 489 853 X7HyMhZNoso 1038 1759 6 0.190970 8.881821
  run_episode 491 855 X7HyMhZNoso 1038 1759 6 0.190970 3.666043
  run_episode 344 564 X7HyMhZNoso 381 634 4 0.677694 11.143211
  run_episode 187 281 EU6Fwq7SyZv 447 754 6 0.433000 10.897436
  run_episode 123 175 QUCTc6BB5sX 465 793 5 0.000000 7.752261
  run_episode 498 868 zsNo4HB9uLZ 222 352 4 0.479000 7.425987
  run_episode 93 139 2azQ1b91cZZ 579 1006 5 0.000000 13.368412
  run_episode 653 1134 Z6MFQCViBuw 336 547 4 0.000000 7.984009
  run_episode 87 127 EU6Fwq7SyZv 288 460 5 1.348777 4.614529
  run_episode 687 1177 X7HyMhZNoso 783 1336 4 0.000000 5.328553
  run_episode 355 584 x8F5xyUWy9e 3 7 5 0.083086 9.844459

  echo "Batch finished at $(date -Is)" | tee -a "${LOG_DIR}/batch.log"
}

main "$@"
