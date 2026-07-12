import json, math, glob, sys, time, argparse
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("episode", type=int)
parser.add_argument("--out-dir", required=True)
args = parser.parse_args()

sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")

from relocalization import sequential_pair_anchor_relocalization, quat_wxyz_to_matrix
from route_memory_agent import RouteAnchor, RouteMemoryAgent, relative_delta, world_pose_7_to_2d

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_icp_replay_capture_hard11_20260706_accumulated_ep"

# Same corrected config as replay_worker_step4_ab_20260712.py (oracle geometry,
# bounded_evidence+alias_aware+trust_aware_guard+promotion_use_pre_closure_estimates,
# one contiguous serial pass per episode -- see that file's header comment for
# the full account of why), plus the new short-baseline disambiguation flag
# under test.
AGENT_KWARGS = dict(
    enabled=True,
    hint_mode="compact",
    relocalization_interval_updates=1,
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
    sequential_pair_short_baseline_disambiguation=True,
    sequential_pair_short_baseline_min_travel_m=0.3,
    sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0,
)

STRIDE = 5


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
    n_downgraded = 0
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
        if not estimate.anchor_heading_reliable:
            n_downgraded += 1

        role_anchor_idx = int(estimate.anchor_index)
        if role_anchor_idx not in anchors_by_idx:
            continue
        target_world_pose = anchors_by_idx[role_anchor_idx]["world_pose"]
        dx_true, dy_true = body_frame_offset(robot_pose, target_world_pose)
        true_dist = math.hypot(dx_true, dy_true)
        true_bearing = math.degrees(math.atan2(dy_true, dx_true))
        bearing_err = angular_diff_deg(estimate.bearing_to_anchor_deg, true_bearing)
        dist_err = abs(estimate.distance_to_anchor_m - true_dist)

        results.append({
            "ep": ep, "anchor": role_anchor_idx, "step": s["step"],
            "backend": estimate.backend,
            "bearing_err_deg": bearing_err, "dist_err_m": dist_err, "true_dist_m": true_dist,
            "match_class": estimate.match_class,
            "near_tie_basin_count": estimate.near_tie_basin_count,
            "anchor_heading_reliable": bool(estimate.anchor_heading_reliable),
        })

    out_path = f"{args.out_dir}/ep{ep}.json"
    json.dump(results, open(out_path, "w"))
    elapsed = time.time() - t0
    print(f"ep{ep}: DONE in {elapsed:.0f}s -- {len(steps)} steps ({n_corrupt} corrupt skipped), "
          f"{n_accepted} accepted events ({n_downgraded} heading-downgraded), {len(results)} readings "
          f"-> {out_path}", flush=True)


if __name__ == "__main__":
    process_episode(args.episode)
