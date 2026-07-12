import json, math, glob, sys, time, argparse
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("episode", type=int)
parser.add_argument("--scripts-dir", required=True,
                     help="Primary scripts directory to import relocalization.py/route_memory_agent.py from")
parser.add_argument("--out-dir", required=True)
args = parser.parse_args()

# Primary scripts dir first (so it wins for relocalization.py/route_memory_agent.py),
# live NaVILA-Bench/scripts appended as a fallback for anything NOT overridden in a
# snapshot dir (e.g. scan_context.py, which neither track modifies).
sys.path.insert(0, args.scripts_dir)
sys.path.append("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")

from relocalization import sequential_pair_anchor_relocalization, quat_wxyz_to_matrix
from route_memory_agent import RouteAnchor, RouteMemoryAgent

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_icp_replay_capture_hard11_20260706_accumulated_ep"

# 2026-07-12 final config, after two corrections this session (see
# investigations/2026-07-10-.../PROGRESS.md for the full account):
#   1. geometry_source=oracle, not accumulated -- this capture has no outbound
#      odometry-accumulator state to reconstruct edge_from_previous from, so
#      accumulated left every anchor-to-anchor edge at its degenerate [0,0,0]
#      default. Each RouteAnchor's metadata["world_pose"] (ground truth) is fed
#      in below so _oracle_edge_between can compute real anchor-to-anchor
#      geometry directly.
#   2. promotion_mode=bounded_evidence + alias_aware + trust_aware_guard +
#      promotion_use_pre_closure_estimates, NOT this capture's own original
#      immediate mode -- immediate mode is the pre-2026-07-06 config with the
#      documented "lead-lock cascade on repeating structure" bug; replaying
#      with it reproduces wrong ANCHOR IDENTITY (93-98% mismatch measured
#      directly against ground truth in the worst episodes), which has
#      nothing to do with the rotational-ambiguity question this replay
#      exists to test. Using the latest validated production config instead
#      isolates that question properly.
# Also: each episode is processed as ONE contiguous, temporally-ordered serial
# pass (no intra-episode chunking) -- an earlier attempt split each episode
# into round-robin-interleaved "chunks" for more parallelism, which broke
# sequential_pair's core invariant (advances one anchor at a time, needs a
# temporally continuous run of steps to track identity) and was caught only
# by a first-3-vs-rest sanity check showing the wrong direction of effect.
# Parallelism now comes only from running multiple EPISODES at once.
AGENT_KWARGS = dict(
    enabled=True,
    hint_mode="compact",
    relocalization_interval_updates=1,  # external stride-based subsampling below instead
    sequential_pair_geometry_source="oracle",
    sequential_pair_closure_check_enabled=True,
    sequential_pair_closure_mode="belief",
    sequential_pair_closure_belief_trust_aware_guard=True,
    sequential_pair_quarantine_enabled=True,
    sequential_pair_quarantine_mode="trend",
    sequential_pair_promotion_mode="bounded_evidence",
    sequential_pair_promotion_window=5,
    sequential_pair_promotion_min_votes=3,
    sequential_pair_promotion_alias_aware=True,
    sequential_pair_promotion_use_pre_closure_estimates=True,
)

STRIDE = 5  # matches this project's relocalization_interval_updates=5 convention


def body_frame_offset(robot_world_pose, target_world_pose):
    rx, ry, rz = robot_world_pose[:3]
    tx, ty, tz = target_world_pose[:3]
    quat = robot_world_pose[3:7]
    R = quat_wxyz_to_matrix(quat)
    world_offset = np.array([tx - rx, ty - ry, tz - rz], dtype=np.float64)
    body_offset = R.T @ world_offset
    return float(body_offset[0]), float(body_offset[1])


def angular_diff_deg(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def process_episode(ep):
    t0 = time.time()
    d = f"{BASE}/{PREFIX}{ep}/icp_replay_dataset"
    anchors_raw = json.load(open(f"{d}/anchors.json"))["anchors"]
    anchors_by_idx = {a["index"]: a for a in anchors_raw if a.get("local_map_points_xyz_body") is not None}
    n_indices = sorted(anchors_by_idx.keys())

    route_anchors = []
    for idx in n_indices:
        a = anchors_by_idx[idx]
        pts = np.asarray(a["local_map_points_xyz_body"], dtype=np.float32)
        route_anchors.append(RouteAnchor(
            index=idx, pose_from_start=[0, 0, 0],
            distance_from_start_m=float(a["distance_from_start_m"]),
            descriptor={"local_map_points_body": pts},
            metadata={"world_pose": list(a["world_pose"])},
        ))

    steps = []
    n_corrupt = 0
    for f in sorted(glob.glob(f"{d}/steps/*.json")):
        try:
            s = json.load(open(f))
        except json.JSONDecodeError:
            n_corrupt += 1
            continue
        steps.append(s)
    steps.sort(key=lambda s: s["step"])
    steps = steps[::STRIDE]

    per_attempt_diag = {}

    def relocalizer(descriptor, _anchors_unused):
        current_a, next_a = agent.sequential_target_anchor_pair()
        return sequential_pair_anchor_relocalization(
            descriptor, current_a, next_a,
            diagnostics=per_attempt_diag,
            return_candidates=True,
            icp_objective="point_to_point",
            voxel_size_m=0.10,
            max_points=512,
            quality_policy="diagnostic",
        )

    agent = RouteMemoryAgent(relocalizer=relocalizer, **AGENT_KWARGS)
    agent.anchors = route_anchors
    agent.finalize_outbound()

    results = []
    n_accepted = 0
    for s in steps:
        robot_pose = s["robot_world_pose"]
        current_points_xyz = s.get("local_map_points_xyz_body")
        if current_points_xyz is None:
            continue
        current_points_xyz = np.asarray(current_points_xyz, dtype=np.float32)
        if len(current_points_xyz) < 12:
            continue

        per_attempt_diag.clear()
        estimate = agent.update_relocalization(
            local_descriptor={"local_map_points_body": current_points_xyz},
        )
        if estimate is None:
            continue
        n_accepted += 1

        role_anchor_idx = int(estimate.anchor_index)
        if role_anchor_idx not in anchors_by_idx:
            continue
        target_world_pose = anchors_by_idx[role_anchor_idx]["world_pose"]
        dx_true, dy_true = body_frame_offset(robot_pose, target_world_pose)
        true_dist = math.hypot(dx_true, dy_true)
        true_bearing = math.degrees(math.atan2(dy_true, dx_true))
        bearing_err = angular_diff_deg(estimate.bearing_to_anchor_deg, true_bearing)
        dist_err = abs(estimate.distance_to_anchor_m - true_dist)

        recs = [r for r in per_attempt_diag.get("covisibility_records", [])
                if r.get("outcome") == "pose_candidate" and r.get("anchor_index") == role_anchor_idx]
        yaw_curve = recs[0].get("yaw_curve", {}) if recs else {}
        localizability = recs[0].get("localizability", {}) if recs else {}
        scan_context_check = recs[0].get("scan_context_yaw_check", {}) if recs else {}

        results.append({
            "ep": ep, "anchor": role_anchor_idx, "step": s["step"],
            "backend": estimate.backend,
            "bearing_err_deg": bearing_err, "dist_err_m": dist_err, "true_dist_m": true_dist,
            "match_class": estimate.match_class,
            "near_tie_basin_count": estimate.near_tie_basin_count,
            "yaw_observability": localizability.get("yaw_observability"),
            "yaw_normalized_marginal_information": localizability.get("yaw_normalized_marginal_information"),
            "yaw_peak_width_deg": yaw_curve.get("yaw_peak_width_deg"),
            "yaw_top1_next_distinct_score_ratio": yaw_curve.get("yaw_top1_next_distinct_score_ratio"),
            "yaw_score_normalized_entropy": yaw_curve.get("yaw_score_normalized_entropy"),
            "scan_context_similarity": scan_context_check.get("scan_context_similarity"),
            "scan_context_region_ratio": scan_context_check.get("scan_context_region_ratio"),
            "icp_scan_context_yaw_agreement_deg": scan_context_check.get("icp_scan_context_yaw_agreement_deg"),
            "had_matching_covisibility_record": bool(recs),
        })

    out_path = f"{args.out_dir}/ep{ep}.json"
    json.dump(results, open(out_path, "w"))
    elapsed = time.time() - t0
    print(f"ep{ep}: DONE in {elapsed:.0f}s -- {len(steps)} steps ({n_corrupt} corrupt skipped), "
          f"{n_accepted} accepted events, {len(results)} readings -> {out_path}", flush=True)


if __name__ == "__main__":
    process_episode(args.episode)
