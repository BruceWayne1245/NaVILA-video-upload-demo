"""
Offline check (per investigations/2026-07-09-.../route_memory_literature_survey.md
section 2.5/2.3): for the cross-run-reproducible hard anchors found in
investigations/2026-07-13-.../FINDINGS.md, does a much denser/near-exhaustive
yaw search using the SAME production scoring function (icp_rigid_transform_2d
+ _icp_score, imported directly from the live relocalization.py -- not a
reimplementation) find a solution close to ground truth that the production
24-seed sweep misses? Or does the wrong answer remain the best-scoring
solution even under near-exhaustive search (i.e. genuine metric-level
ambiguity, not a search-density problem)?

Uses real captured point clouds from icp_replay_capture_hard11_20260706_accumulated
(ep367 anchor8, ep368 anchor12) -- ep678 anchor7 excluded, that capture's
anchors.json is corrupted (known pre-existing issue, documented since 2026-07-06).
"""
import json, math, glob, sys
import numpy as np

sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")
from relocalization import (
    icp_rigid_transform_2d, _icp_score, voxel_downsample_2d, voxel_downsample_xyz,
    quat_wxyz_to_matrix,
)

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_icp_replay_capture_hard11_20260706_accumulated_ep"

TARGETS = [(367, 8), (368, 12)]

VOXEL_SIZE_M = 0.10
MAX_POINTS = 512
CORR_THRESH_M = 0.45
PRODUCTION_SEEDS_DEG = list(range(-180, 180, 15))  # 24 seeds, matches live default
DENSE_SEEDS_DEG = list(range(-180, 180, 1))  # 360 seeds


def body_frame_offset(robot_pose, target_pose):
    rx, ry = robot_pose[0], robot_pose[1]
    tx, ty = target_pose[0], target_pose[1]
    quat = robot_pose[3:7]
    R = quat_wxyz_to_matrix(quat)
    world_offset = np.array([tx - rx, ty - ry, 0.0], dtype=np.float64)
    body_offset = R.T @ world_offset
    return float(body_offset[0]), float(body_offset[1])


def angular_diff_deg(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def best_over_seeds(anchor_xy, current_xy, seeds_deg):
    best = None
    best_score = -1.0
    for deg in seeds_deg:
        result = icp_rigid_transform_2d(
            anchor_xy, current_xy,
            initial_theta=math.radians(deg),
            max_iterations=16,
            correspondence_threshold_m=CORR_THRESH_M,
            objective="point_to_point",
        )
        if result is None:
            continue
        score = _icp_score(result, CORR_THRESH_M)
        if score > best_score:
            best_score = score
            best = result
    return best, best_score


for ep, anchor_idx in TARGETS:
    print(f"\n{'='*70}\nep{ep} anchor{anchor_idx}\n{'='*70}")
    d = f"{BASE}/{PREFIX}{ep}"
    anchors_raw = json.load(open(f"{d}/icp_replay_dataset/anchors.json"))["anchors"]
    anchor = next(a for a in anchors_raw if a["index"] == anchor_idx)
    anchor_xyz_full = np.asarray(anchor["local_map_points_xyz_body"], dtype=np.float32)
    anchor_world_pose = anchor["world_pose"]
    anchor_xy_full = anchor_xyz_full[:, :2]
    anchor_xy = voxel_downsample_2d(anchor_xy_full, voxel_size_m=VOXEL_SIZE_M, max_points=MAX_POINTS)
    print(f"anchor raw points={len(anchor_xyz_full)}, downsampled={len(anchor_xy)}")

    step_files = sorted(glob.glob(f"{d}/icp_replay_dataset/steps/*.json"))
    # subsample for speed, then filter to steps geometrically close to this anchor
    candidates = []
    for f in step_files[::5]:
        try:
            s = json.load(open(f))
        except json.JSONDecodeError:
            continue
        pts = s.get("local_map_points_xyz_body")
        if pts is None:
            continue
        dx, dy = body_frame_offset(s["robot_world_pose"], anchor_world_pose)
        dist = math.hypot(dx, dy)
        if 0.2 < dist < 2.5:
            candidates.append((s, dx, dy, dist))
    print(f"candidate return-phase steps within 2.5m of anchor: {len(candidates)}")
    # pick up to 8, spread across the available range
    if len(candidates) > 8:
        idxs = np.linspace(0, len(candidates) - 1, 8).astype(int)
        candidates = [candidates[i] for i in idxs]

    for s, dx_true, dy_true, true_dist in candidates:
        true_bearing = math.degrees(math.atan2(dy_true, dx_true))
        current_xyz_full = np.asarray(s["local_map_points_xyz_body"], dtype=np.float32)
        current_xy_full = current_xyz_full[:, :2]
        current_xy = voxel_downsample_2d(current_xy_full, voxel_size_m=VOXEL_SIZE_M, max_points=MAX_POINTS)

        prod_best, prod_score = best_over_seeds(anchor_xy, current_xy, PRODUCTION_SEEDS_DEG)
        dense_best, dense_score = best_over_seeds(anchor_xy, current_xy, DENSE_SEEDS_DEG)

        # seed exactly at ground truth theta (dtheta unknown a priori in the real
        # pipeline, but here we approximate ground truth yaw as the bearing
        # implied by dx/dy is NOT the same as ground truth ROTATION between the
        # anchor and current frames -- we need the actual relative yaw, computed
        # from the two world_pose quaternions directly.
        def yaw_from_quat(q):
            w, x, y, z = q
            return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        true_yaw = yaw_from_quat(s["robot_world_pose"][3:7]) - yaw_from_quat(anchor_world_pose[3:7])
        true_yaw_deg = math.degrees(math.atan2(math.sin(true_yaw), math.cos(true_yaw)))

        truth_seeded = icp_rigid_transform_2d(
            anchor_xy, current_xy, initial_theta=math.radians(true_yaw_deg),
            max_iterations=16, correspondence_threshold_m=CORR_THRESH_M, objective="point_to_point",
        )
        truth_score = _icp_score(truth_seeded, CORR_THRESH_M) if truth_seeded is not None else None

        prod_bearing_est = math.degrees(math.atan2(prod_best["translation"][1], prod_best["translation"][0])) if prod_best else None
        prod_err = angular_diff_deg(math.degrees(prod_best["theta"]), true_yaw_deg) if prod_best else None
        dense_err = angular_diff_deg(math.degrees(dense_best["theta"]), true_yaw_deg) if dense_best else None
        truth_seeded_err = angular_diff_deg(math.degrees(truth_seeded["theta"]), true_yaw_deg) if truth_seeded else None

        print(f"  step={s['step']:6d} true_dist={true_dist:.2f}m true_yaw={true_yaw_deg:7.1f}  |  "
              f"24seed: theta_err={prod_err:6.1f} score={prod_score:.3f}  |  "
              f"360seed: theta_err={dense_err:6.1f} score={dense_score:.3f}  |  "
              f"truth-seeded: theta_err={truth_seeded_err:6.1f} score={truth_score:.3f}")
