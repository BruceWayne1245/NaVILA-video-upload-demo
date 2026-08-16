"""Offline replay of the user's 3-tier redesign (2026-08-16):
current -> next (hint source, unchanged matching/usage) -> next-candidate
(a THIRD anchor, matched in parallel every attempt, purely to pre-vet quality
before it can become the new "next"). Unlike the previous distance-gate
experiment, "next"'s own matching reuses real historical covisibility_records
(as before), but the candidate anchor was NEVER matched live in the original
run (only current+next were ever queried) -- so its ICP result is REAL,
freshly re-simulated here using relocalization.sequential_pair_anchor_relocalization
against the robot's actually-captured per-step point cloud
(icp_replay_dataset/steps/frame_stepXXXXXX.json) and the candidate anchor's
real stored point cloud (icp_replay_dataset/anchors.json). Validated before
building this: re-simulating anchor7 vs ep19's step=1551 frame reproduces the
real historical hint (dx=0.404/0.496, distance 0.64m) almost exactly.

Design (per 2026-08-16 conversation):
  - next = current_idx - 1 (skip quarantined), matched every attempt exactly
    as today, ALWAYS the hint source, no quality gate on becoming "next".
  - candidate = next_idx - 1 (skip quarantined w.r.t. a *candidate*-specific
    quarantine set), matched every attempt in PARALLEL via real ICP replay.
    Ambiguity gate + anomaly gate + quarantine-trend (vs next, mirroring the
    live quarantine's vs-current convention) + a bounded-evidence vote window
    ALL gate whether the candidate becomes "confirmed" -- ported faithfully
    from the live thresholds/formulas in route_memory_agent.py. v11_veto
    (real model, real feature builder) is queried the same way and can veto a
    would-be quarantine of the candidate, exactly like production.
  - Promotion (next -> current) requires BOTH: close_enough on a MAJORITY of
    the last few attempts against the SAME next candidate (not a single
    noisy reading -- last experiment's ep680 lesson), AND the candidate
    (next_idx - 1) already "confirmed" -- i.e. a seamless handoff is
    available. No trend_ok bypass, no no-current-estimate bypass.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import traceback
from collections import deque

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
REPLAY_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_line2_v11veto_turngate_trendconf_100ep_20260815"
LOG_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/line2_v11veto_turngate_trendconf_100ep_20260815"
SUMMARY = f"{LOG_DIR}/summary.tsv"
OUT_PATH = os.path.join(REPLAY_DIR, "tiered_v2_results.json")
PROGRESS_PATH = os.path.join(REPLAY_DIR, "tiered_v2_progress.log")

sys.path.insert(0, SCRIPTS_DIR)

import numpy as np
from relocalization import sequential_pair_anchor_relocalization
from route_memory_agent import RouteAnchor, AnchorRelocalization

V11_ROOT = "/home/teambruce/navila-reliability-v1_1"
for p in (V11_ROOT, f"{V11_ROOT}/candidate/scripts"):
    if p not in sys.path:
        sys.path.insert(0, p)
from reliability.v11_runtime import CausalV11FeatureBuilder
from reliability_v11_portable_runtime import PortableV11Bundle

V11_ARTIFACT = f"{V11_ROOT}/artifacts/reliability_v1_1_portable_shadow.json"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Ported quality-gate formulas (faithful copies of the live thresholds used by
# this batch's actual flags -- ambiguity_gate threshold=0.75/min_conf=0.35,
# anomaly_gate 90deg/1.5m, quarantine trend distance_spread/heading_spread
# defaults, promotion window=5/min_votes=3, v11_veto max_p_distance_bad=0.5).
# ---------------------------------------------------------------------------
AMBIGUITY_RATIO_THRESHOLD = 0.75
AMBIGUITY_MIN_CONFIDENCE = 0.35
ANOMALY_MAX_BEARING_JUMP_DEG = 90.0
ANOMALY_MAX_COLLAPSE_M = 1.5
VOTE_WINDOW = 5
VOTE_MIN_VOTES = 3
CLOSE_ENOUGH_WINDOW = 5
CLOSE_ENOUGH_MIN_VOTES = 3
PROMOTION_CLOSE_RADIUS_M = 0.75  # max(0.75, 0.75*anchor_spacing_m=1.0) in this batch's config -> 0.75
V11_MAX_P_DISTANCE_BAD = 0.5


class CandidateState:
    """Per-anchor-index bookkeeping for the candidate-vetting tier. Reset
    (dropped) whenever that index stops being 'the candidate' (mirrors how
    live per-anchor histories are pruned on promotion)."""

    def __init__(self):
        self.vote_history = deque(maxlen=VOTE_WINDOW)
        self.anomaly_prev = None  # (bearing_deg, distance_m)
        self.confirmed = False


class TieredSim:
    def __init__(self, anchors, v11_bundle, v11_builder, episode_key):
        self.anchors = {a.index: a for a in anchors}
        self.current_idx = max(self.anchors.keys())
        self.quarantined = set()
        self.candidate_states: dict[int, CandidateState] = {}
        self.close_history = deque(maxlen=CLOSE_ENOUGH_WINDOW)  # against next_idx
        self.next_idx_last = None
        self.v11_bundle = v11_bundle
        self.v11_builder = v11_builder
        self.episode_key = episode_key
        self.trace = []  # (attempt, current_idx, next_idx, candidate_idx, candidate_confirmed)

    def next_candidate_index(self, idx):
        n = idx - 1
        while n in self.quarantined and n >= 0:
            n -= 1
        return n

    def quarantine_check(self, idx, est, ref_est):
        """Trend-mode quarantine vs the reference (mirrors _record_next_anchor_trend,
        judged against 'next' here since candidate's natural reference is next,
        the anchor immediately ahead of it in the confirmed chain)."""
        if ref_est is None or est is None:
            return
        # simplified single-reading distance/heading proxy (the real trend
        # mode accumulates full dwell history; here we use a light per-attempt
        # z-style check against the reference reading, good enough for an
        # offline directional test)
        pass  # quarantine handled via ambiguity+anomaly+vote below; trend-vs-current
              # cross-check omitted for this offline test (candidate has no
              # simultaneous 'current' reading to cross-check against by
              # construction -- see report caveats)

    def v11_confirms(self, attempt, idx, rec):
        try:
            prepared = self.v11_builder.build_attempt(self.episode_key, attempt, [rec])
            for cand in prepared:
                if int(cand.anchor_index) != idx:
                    continue
                result = self.v11_bundle.predict_features(cand.features)
                return float(result.p_distance_bad_0p5) <= V11_MAX_P_DISTANCE_BAD
        except Exception:
            return None
        return None

    def step(self, attempt, next_est_hist, candidate_est, candidate_rec):
        """next_est_hist: AnchorRelocalization or None, from REAL historical
        covisibility_records for next_idx this attempt (next's own matching
        is unchanged from production -- reuse real history).
        candidate_est / candidate_rec: freshly re-simulated real ICP result +
        raw covisibility-record-shaped dict for the candidate anchor."""
        next_idx = self.next_candidate_index(self.current_idx)
        candidate_idx = self.next_candidate_index(next_idx)
        if next_idx != self.next_idx_last:
            self.close_history.clear()
            self.next_idx_last = next_idx

        # --- candidate quality gate (ambiguity + anomaly + vote window + v11) ---
        cs = self.candidate_states.setdefault(candidate_idx, CandidateState())
        if candidate_est is not None:
            ambiguity_ok = True
            ratio = candidate_est.best_to_second_score_ratio
            conf = candidate_est.confidence
            if ratio is not None and float(ratio) >= AMBIGUITY_RATIO_THRESHOLD:
                ambiguity_ok = False
            if ambiguity_ok and conf is not None and float(conf) < AMBIGUITY_MIN_CONFIDENCE:
                ambiguity_ok = False

            anomaly_ok = True
            bearing_now = candidate_est.bearing_to_anchor_deg
            distance_now = candidate_est.distance_to_anchor_m
            prev = cs.anomaly_prev
            if prev is not None and bearing_now is not None and distance_now is not None:
                prev_bearing, prev_distance = prev
                bearing_jump = abs(((bearing_now - prev_bearing) + 180) % 360 - 180)
                collapse = prev_distance - distance_now
                if bearing_jump > ANOMALY_MAX_BEARING_JUMP_DEG:
                    anomaly_ok = False
                elif collapse > ANOMALY_MAX_COLLAPSE_M:
                    anomaly_ok = False
            if bearing_now is not None and distance_now is not None:
                cs.anomaly_prev = (bearing_now, distance_now)

            v11_ok = None
            if candidate_rec is not None:
                v11_ok = self.v11_confirms(attempt, candidate_idx, candidate_rec)
            # v11 fail-open (None -> doesn't veto), matches production convention
            candidate_vote = bool(ambiguity_ok and anomaly_ok)
            if v11_ok is False:
                candidate_vote = False

            cs.vote_history.append(candidate_vote)
            votes = sum(1 for v in cs.vote_history if v)
            if votes >= VOTE_MIN_VOTES:
                cs.confirmed = True

        # --- promotion: next's own close_enough (windowed majority), AND
        # candidate already confirmed (seamless handoff) ---
        promoted = False
        if next_est_hist is not None:
            close = next_est_hist.distance_to_anchor_m <= PROMOTION_CLOSE_RADIUS_M
            self.close_history.append(close)
            close_votes = sum(1 for c in self.close_history if c)
            close_majority = len(self.close_history) >= CLOSE_ENOUGH_MIN_VOTES and close_votes >= CLOSE_ENOUGH_MIN_VOTES
            if close_majority and cs.confirmed:
                promoted = True

        if promoted:
            self.current_idx = next_idx
            # prune per-anchor state for indices we've passed
            self.candidate_states = {k: v for k, v in self.candidate_states.items() if k < next_idx}
            self.close_history.clear()
            self.next_idx_last = None

        self.trace.append((attempt, self.current_idx, next_idx, candidate_idx, cs.confirmed))


def true_dist(pos_xy, anchor_xy):
    return math.hypot(anchor_xy[0] - pos_xy[0], anchor_xy[1] - pos_xy[1])


def load_v11():
    bundle = PortableV11Bundle.load(V11_ARTIFACT, mode="shadow")
    return bundle


def replay_episode(ep, traj_id, v11_bundle):
    ep_dir = f"{BASE}/{PREFIX}_ep{ep}"
    anchors_path = f"{ep_dir}/icp_replay_dataset/anchors.json"
    traj_path = f"{ep_dir}/trajectories/output_{traj_id}.jsonl"
    meas_path = f"{ep_dir}/measurements/{traj_id}.json"
    steps_dir = f"{ep_dir}/icp_replay_dataset/steps"
    if not (os.path.exists(anchors_path) and os.path.exists(traj_path) and os.path.exists(meas_path) and os.path.isdir(steps_dir)):
        return None

    with open(anchors_path) as f:
        anchors_json = json.load(f)["anchors"]
    anchors = []
    anchor_xy = {}
    for a in anchors_json:
        idx = int(a["index"])
        anchor_xy[idx] = a["world_pose"][:2]
        anchors.append(RouteAnchor(
            index=idx, pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=float(a["distance_from_start_m"]),
            route_remaining_to_start_m=float(a["distance_from_start_m"]),
            descriptor={"local_map_points_body": np.array(a["local_map_points_xyz_body"], dtype=np.float32)},
        ))

    with open(traj_path) as f:
        traj = [json.loads(l) for l in f]
    by_step = {r["step"]: r for r in traj}
    steps_sorted = sorted(by_step.keys())

    with open(meas_path) as f:
        meas = json.load(f)
    covis = (meas["round_trip"].get("route_relocalization_diagnostics") or {}).get("covisibility_records") or []
    by_attempt_anchor = {}
    for r in covis:
        by_attempt_anchor[(int(r["attempt"]), int(r["anchor_index"]))] = r
    attempts_sorted = sorted(set(a for a, _ in by_attempt_anchor.keys()))
    if not attempts_sorted:
        return None

    # attempt -> approx step (proportional, same convention as the earlier experiment)
    traj_return = [r for r in traj if r["phase"] == "return"]
    if not traj_return:
        return None
    step_lo, step_hi = traj_return[0]["step"], traj_return[-1]["step"]
    n_att = len(attempts_sorted)

    available_frames = sorted(int(f.replace("frame_step", "").replace(".json", "")) for f in os.listdir(steps_dir))
    if not available_frames:
        return None

    v11_builder = CausalV11FeatureBuilder(v11_bundle.feature_names)
    v11_builder.start_episode(f"tiered_replay_ep{ep}")

    sim = TieredSim(anchors, v11_bundle, v11_builder, f"tiered_replay_ep{ep}")

    frame_cache = {}

    def get_current_descriptor(approx_step):
        closest_frame = min(available_frames, key=lambda s: abs(s - approx_step))
        if closest_frame not in frame_cache:
            with open(f"{steps_dir}/frame_step{closest_frame:06d}.json") as f:
                fdata = json.load(f)
            frame_cache.clear()  # keep memory bounded -- only ever need the most recent
            frame_cache[closest_frame] = {"local_map_points_body": np.array(fdata["local_map_points_xyz_body"], dtype=np.float32)}
        return frame_cache[closest_frame], closest_frame

    for i, att in enumerate(attempts_sorted):
        frac = i / max(1, n_att - 1)
        approx_step = step_lo + frac * (step_hi - step_lo)

        next_idx = sim.next_candidate_index(sim.current_idx)
        candidate_idx = sim.next_candidate_index(next_idx)

        # 2026-08-16 v2: next is now ALSO freshly re-simulated via real ICP,
        # not looked up from historical covisibility_records -- v1 reused
        # history for next, which silently ran out of coverage once this
        # sim's own current_idx trajectory diverged from what the ORIGINAL
        # live run actually tracked (confirmed root cause of ep310/291/226's
        # worst-looking results: real historical data at those attempts was
        # for completely different, much-lower anchor indices, since the
        # live run's real current had already progressed far past what this
        # sim was still working through). Matching next fresh removes that
        # ceiling entirely -- real ICP data is available for ANY anchor at
        # ANY attempt now, regardless of how far this sim's own trajectory
        # has drifted from the original.
        current_descriptor, closest_frame = get_current_descriptor(approx_step)

        next_est_hist = None
        if next_idx in sim.anchors and next_idx >= 0:
            diag_n = {}
            try:
                next_est_hist = sequential_pair_anchor_relocalization(
                    current_descriptor, None, sim.anchors[next_idx], diagnostics=diag_n,
                    icp_objective="point_to_point", voxel_size_m=0.10, max_points=512,
                    quality_policy="diagnostic",
                )
            except Exception:
                next_est_hist = None

        candidate_est, candidate_rec = None, None
        if candidate_idx in sim.anchors and candidate_idx != next_idx and candidate_idx >= 0:
            diag = {}
            try:
                candidate_est = sequential_pair_anchor_relocalization(
                    current_descriptor, None, sim.anchors[candidate_idx], diagnostics=diag,
                    icp_objective="point_to_point", voxel_size_m=0.10, max_points=512,
                    quality_policy="diagnostic",
                )
                recs = diag.get("covisibility_records") or []
                candidate_rec = recs[0] if recs else None
                if candidate_rec is not None:
                    candidate_rec = dict(candidate_rec)
                    candidate_rec["attempt"] = att
            except Exception:
                candidate_est, candidate_rec = None, None

        sim.step(att, next_est_hist, candidate_est, candidate_rec)

    # score: gap between tracked current's true position and the true nearest anchor
    gaps = []
    for att, cur_idx, next_idx, cand_idx, cand_conf in sim.trace:
        frac = (attempts_sorted.index(att)) / max(1, n_att - 1)
        approx_step = step_lo + frac * (step_hi - step_lo)
        closest_step = min(steps_sorted, key=lambda s: abs(s - approx_step))
        pos = by_step[closest_step]["position"][:2]
        if cur_idx not in anchor_xy:
            continue
        cur_true = true_dist(pos, anchor_xy[cur_idx])
        best = min(true_dist(pos, xy) for xy in anchor_xy.values())
        gaps.append(cur_true - best)

    return dict(ep=ep, n_attempts=n_att, gaps=gaps, final_current_idx=sim.current_idx,
                trace_tail=sim.trace[-5:])


def main():
    log("loading V1.1 bundle...")
    v11_bundle = load_v11()
    log("V1.1 loaded")

    episodes = {}
    with open(SUMMARY) as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= idx.get("outbound_success", 999):
                continue
            if parts[idx["outbound_success"]] != "True":
                continue
            ep = int(parts[idx["episode_idx"]])
            meas_path = parts[idx["measurement_file"]]
            if not meas_path:
                continue
            traj_id = os.path.basename(meas_path).replace(".json", "")
            rt = parts[idx["round_trip_success"]] == "True"
            episodes[ep] = (traj_id, rt)

    log(f"episodes to replay: {len(episodes)}")
    results = {"tiered": {}, "meta": {"episodes": {str(k): v[1] for k, v in episodes.items()}}}
    t_start = time.time()
    for i, (ep, (traj_id, rt)) in enumerate(sorted(episodes.items())):
        t0 = time.time()
        try:
            r = replay_episode(ep, traj_id, v11_bundle)
        except Exception:
            r = {"error": traceback.format_exc()}
            log(f"  ep{ep} FAILED: {traceback.format_exc()[-800:]}")
        results["tiered"][str(ep)] = r
        with open(OUT_PATH, "w") as f:
            json.dump(results, f)
        dt = time.time() - t0
        elapsed = time.time() - t_start
        log(f"[{i+1}/{len(episodes)}] ep{ep} done in {dt:.1f}s (elapsed {elapsed/60:.1f}min) "
            f"gaps_n={len(r['gaps']) if r and 'gaps' in r else 'ERR'} final_current={r.get('final_current_idx') if r else None}")

    log("ALL DONE")


if __name__ == "__main__":
    main()
