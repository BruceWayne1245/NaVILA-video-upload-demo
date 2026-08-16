"""v3: user's proposed fix for the stage-4 stuck problem (2026-08-16). When
next is close_majority-ready to promote but its candidate is STUCK (neither
confirmed nor quarantined), treat it as if it WERE confirmed and promote
anyway. Net promotion rule becomes: promote whenever close_majority AND NOT
quarantined (quarantined candidates still correctly block promotion; only
the "stuck" limbo case gets force-through). This is a targeted change to
ONE line relative to stuck_candidate_quality.py's real, complete TieredSim
(which has the full quarantine-trend logic v2 was missing) -- reuses that
version's real-ICP-for-both-next-and-candidate methodology (the validated,
bug-fixed one), plus adds run_tiered_replay_v2.py's gap-based scoring so
results are directly comparable to the baseline and tiered_v2 numbers.

Same 85-episode set as run_tiered_replay_v2.py (all outbound-success
episodes from the source batch), for full comparability.
"""
from __future__ import annotations

import json
import math
import os
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
OUT_PATH = os.path.join(REPLAY_DIR, "tiered_v3_forcepromote_results.json")
PROGRESS_PATH = os.path.join(REPLAY_DIR, "tiered_v3_forcepromote_progress.log")

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

AMBIGUITY_RATIO_THRESHOLD = 0.75
AMBIGUITY_MIN_CONFIDENCE = 0.35
ANOMALY_MAX_BEARING_JUMP_DEG = 90.0
ANOMALY_MAX_COLLAPSE_M = 1.5
VOTE_WINDOW = 5
VOTE_MIN_VOTES = 3
CLOSE_ENOUGH_WINDOW = 5
CLOSE_ENOUGH_MIN_VOTES = 3
PROMOTION_CLOSE_RADIUS_M = 0.75
V11_MAX_P_DISTANCE_BAD = 0.5
QUARANTINE_TREND_MIN_HISTORY = 6
QUARANTINE_TREND_SPREAD_M = 1.5
QUARANTINE_TREND_BAD_FRACTION = 0.5


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a") as f:
        f.write(line + "\n")


class CandidateState:
    def __init__(self):
        self.vote_history = deque(maxlen=VOTE_WINDOW)
        self.anomaly_prev = None
        self.confirmed = False
        self.disagreement_history = deque(maxlen=64)
        self.quarantined = False


class TieredSim:
    def __init__(self, anchors, v11_bundle, v11_builder, episode_key):
        self.anchors = {a.index: a for a in anchors}
        self.current_idx = max(self.anchors.keys())
        self.quarantined_indices = set()
        self.candidate_states: dict[int, CandidateState] = {}
        self.close_history = deque(maxlen=CLOSE_ENOUGH_WINDOW)
        self.next_idx_last = None
        self.v11_bundle = v11_bundle
        self.v11_builder = v11_builder
        self.episode_key = episode_key
        self.trace = []  # (attempt, current_idx, next_idx, candidate_idx, confirmed, quarantined, promoted_via_force)
        self.n_force_promotions = 0
        self.n_normal_promotions = 0

    def next_candidate_index(self, idx):
        n = idx - 1
        while n in self.quarantined_indices and n >= 0:
            n -= 1
        return n

    def quarantine_check(self, cs, candidate_idx, candidate_est, next_est_hist):
        if candidate_est is None or next_est_hist is None:
            return
        cand_anchor = self.anchors.get(candidate_idx)
        next_anchor = self.anchors.get(self.next_idx_last)
        if cand_anchor is None or next_anchor is None:
            return
        cand_dist_to_start = candidate_est.distance_to_anchor_m + cand_anchor.route_remaining_to_start_m
        next_dist_to_start = next_est_hist.distance_to_anchor_m + next_anchor.route_remaining_to_start_m
        disagree = abs(cand_dist_to_start - next_dist_to_start) > QUARANTINE_TREND_SPREAD_M
        cs.disagreement_history.append(disagree)
        if len(cs.disagreement_history) < QUARANTINE_TREND_MIN_HISTORY:
            return
        bad_fraction = sum(1 for d in cs.disagreement_history if d) / len(cs.disagreement_history)
        if bad_fraction > QUARANTINE_TREND_BAD_FRACTION:
            cs.quarantined = True
            self.quarantined_indices.add(candidate_idx)

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

    def step(self, attempt, next_est, candidate_est, candidate_rec):
        next_idx = self.next_candidate_index(self.current_idx)
        candidate_idx = self.next_candidate_index(next_idx)
        if next_idx != self.next_idx_last:
            self.close_history.clear()
            self.next_idx_last = next_idx

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
            candidate_vote = bool(ambiguity_ok and anomaly_ok)
            if v11_ok is False:
                candidate_vote = False

            cs.vote_history.append(candidate_vote)
            votes = sum(1 for v in cs.vote_history if v)
            if votes >= VOTE_MIN_VOTES:
                cs.confirmed = True

            if not cs.confirmed and not cs.quarantined:
                self.quarantine_check(cs, candidate_idx, candidate_est, next_est)

        promoted = False
        promoted_via_force = False
        close_majority = False
        if next_est is not None:
            close = next_est.distance_to_anchor_m <= PROMOTION_CLOSE_RADIUS_M
            self.close_history.append(close)
            close_votes = sum(1 for c in self.close_history if c)
            close_majority = len(self.close_history) >= CLOSE_ENOUGH_MIN_VOTES and close_votes >= CLOSE_ENOUGH_MIN_VOTES
            # 2026-08-16 v3: user's fix -- close_majority + NOT quarantined is
            # enough to promote (quarantined still blocks; "stuck" -- neither
            # confirmed nor quarantined -- is now treated as if confirmed).
            if close_majority and not cs.quarantined:
                promoted = True
                promoted_via_force = not cs.confirmed

        self.trace.append((attempt, self.current_idx, next_idx, candidate_idx,
                            cs.confirmed, cs.quarantined, promoted_via_force))

        if promoted:
            if promoted_via_force:
                self.n_force_promotions += 1
            else:
                self.n_normal_promotions += 1
            self.current_idx = next_idx
            self.candidate_states = {k: v for k, v in self.candidate_states.items() if k < next_idx}
            self.close_history.clear()
            self.next_idx_last = None


def true_dist(pos_xy, anchor_xy):
    return math.hypot(anchor_xy[0] - pos_xy[0], anchor_xy[1] - pos_xy[1])


def load_v11():
    return PortableV11Bundle.load(V11_ARTIFACT, mode="shadow")


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
    attempts_sorted = sorted(set(int(r["attempt"]) for r in covis))
    if not attempts_sorted:
        return None

    traj_return = [r for r in traj if r["phase"] == "return"]
    if not traj_return:
        return None
    step_lo, step_hi = traj_return[0]["step"], traj_return[-1]["step"]
    n_att = len(attempts_sorted)

    available_frames = sorted(int(f.replace("frame_step", "").replace(".json", "")) for f in os.listdir(steps_dir))
    if not available_frames:
        return None

    v11_builder = CausalV11FeatureBuilder(v11_bundle.feature_names)
    v11_builder.start_episode(f"forcepromote_ep{ep}")
    sim = TieredSim(anchors, v11_bundle, v11_builder, f"forcepromote_ep{ep}")

    frame_cache = {}

    def get_current_descriptor(approx_step):
        closest_frame = min(available_frames, key=lambda s: abs(s - approx_step))
        if closest_frame not in frame_cache:
            with open(f"{steps_dir}/frame_step{closest_frame:06d}.json") as f:
                fdata = json.load(f)
            frame_cache.clear()
            frame_cache[closest_frame] = {"local_map_points_body": np.array(fdata["local_map_points_xyz_body"], dtype=np.float32)}
        return frame_cache[closest_frame], closest_frame

    for i, att in enumerate(attempts_sorted):
        frac = i / max(1, n_att - 1)
        approx_step = step_lo + frac * (step_hi - step_lo)

        next_idx = sim.next_candidate_index(sim.current_idx)
        candidate_idx = sim.next_candidate_index(next_idx)
        current_descriptor, closest_frame = get_current_descriptor(approx_step)

        next_est = None
        if next_idx in sim.anchors and next_idx >= 0:
            try:
                next_est = sequential_pair_anchor_relocalization(
                    current_descriptor, None, sim.anchors[next_idx], diagnostics={},
                    icp_objective="point_to_point", voxel_size_m=0.10, max_points=512,
                    quality_policy="diagnostic",
                )
            except Exception:
                next_est = None

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

        sim.step(att, next_est, candidate_est, candidate_rec)

    gaps = []
    for att, cur_idx, next_idx, cand_idx, confirmed, quarantined, forced in sim.trace:
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
                n_force_promotions=sim.n_force_promotions, n_normal_promotions=sim.n_normal_promotions,
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
            episodes[ep] = traj_id

    log(f"episodes to replay: {len(episodes)}")
    results = {}
    t_start = time.time()
    for i, (ep, traj_id) in enumerate(sorted(episodes.items())):
        t0 = time.time()
        try:
            r = replay_episode(ep, traj_id, v11_bundle)
        except Exception:
            r = {"error": traceback.format_exc()}
            log(f"  ep{ep} FAILED: {traceback.format_exc()[-500:]}")
        results[str(ep)] = r
        with open(OUT_PATH, "w") as f:
            json.dump(results, f)
        dt = time.time() - t0
        elapsed = time.time() - t_start
        gaps_n = len(r["gaps"]) if r and "gaps" in r else "ERR"
        nforce = r.get("n_force_promotions") if r else None
        log(f"[{i+1}/{len(episodes)}] ep{ep} done in {dt:.1f}s (elapsed {elapsed/60:.1f}min) "
            f"gaps_n={gaps_n} n_force_promotions={nforce} final_current={r.get('final_current_idx') if r else None}")

    log("ALL DONE")


if __name__ == "__main__":
    main()
