"""2026-07-16: does the true 3D (height) structure discriminate the known
confidently-wrong-yaw hard-anchor cases, or is the aliasing genuine in 3D too
(not just an artifact of flattening to 2D before matching)?

For each known bad (ep, anchor, step) case from GLOBAL_REGISTRATION_CHECK.md
(2026-07-13), computes the TRUE relative transform (from ground-truth world
poses) and the ICP-preferred WRONG transform (via a real 24-seed sweep, same
production function), applies both to the anchor's own raw 3D point cloud,
and compares height (z) residuals against the current scan's 3D points under
nearest-2D-neighbor correspondence -- i.e. holding xy alignment quality fixed,
does z alignment quality differ between the true and wrong transform?
"""
import json
import math
import sys

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
sys.path.insert(0, SCRIPTS_DIR)

import numpy as np  # noqa: E402
from relocalization import (  # noqa: E402
    icp_seed_sweep_2d, voxel_downsample_2d, voxel_downsample_xyz,
    _apply_transform_2d, _nearest_neighbor_2d,
)

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
BATCH = "icp_replay_capture_hard11_20260706_accumulated"


def wrap_deg(a):
    return (a + 180) % 360 - 180


def pose_yaw(pose):
    q0, q1, q2, q3 = pose[3], pose[4], pose[5], pose[6]
    return math.atan2(2 * (q1 * q2 + q0 * q3), q0**2 + q1**2 - q2**2 - q3**2)


def load(ep, anchor_index, step_num):
    epdir = f"{BASE}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{BATCH}_ep{ep}/icp_replay_dataset"
    anchors = json.load(open(f"{epdir}/anchors.json"))["anchors"]
    anchor = [a for a in anchors if a["index"] == anchor_index][0]
    step = json.load(open(f"{epdir}/steps/frame_step{step_num:06d}.json"))
    return anchor, step


def true_relative_transform(anchor_world_pose, robot_world_pose):
    """True (dtheta, dx_body, dy_body) s.t. rotating+translating the anchor's
    own body-frame points by this transform aligns them with the current
    scan's body frame (both already captured in each's own body frame)."""
    ax, ay = anchor_world_pose[0], anchor_world_pose[1]
    rx, ry = robot_world_pose[0], robot_world_pose[1]
    a_yaw = pose_yaw(anchor_world_pose)
    r_yaw = pose_yaw(robot_world_pose)
    dtheta = r_yaw - a_yaw  # rotation from anchor's frame to robot's frame... see below, sign handled by direct search
    # World-frame offset of anchor origin relative to robot origin, expressed in the ROBOT's body frame
    dx_world = ax - rx
    dy_world = ay - ry
    cos_r, sin_r = math.cos(r_yaw), math.sin(r_yaw)
    dx_body = cos_r * dx_world + sin_r * dy_world
    dy_body = -sin_r * dx_world + cos_r * dy_world
    return dtheta, dx_body, dy_body


def height_residuals(anchor_xyz, current_xyz, theta, translation):
    """Applies (theta, translation) to anchor_xyz's xy, finds nearest 2D
    neighbor in current_xyz, returns z residuals for inlier (<0.45m) pairs."""
    anchor_xy = anchor_xyz[:, :2].astype(np.float32)
    current_xy = current_xyz[:, :2].astype(np.float32)
    transformed = _apply_transform_2d(anchor_xy, theta, np.asarray(translation, dtype=np.float32))
    nearest, dist2d = _nearest_neighbor_2d(transformed, current_xy)
    inliers = dist2d < 0.45
    if inliers.sum() < 8:
        return None, None
    z_anchor = anchor_xyz[inliers, 2]
    z_current = current_xyz[nearest[inliers], 2]
    z_resid = np.abs(z_anchor - z_current)
    return float(np.median(z_resid)), float(inliers.sum())


CASES = [
    (367, 8, 1925, 134.2), (367, 8, 2040, 145.3), (367, 8, 2155, 166.7), (367, 8, 2270, -177.1),
    (367, 8, 2520, 140.2), (367, 8, 2635, 134.1), (367, 8, 2750, 102.4), (367, 8, 2870, 82.9),
    (368, 12, 2245, 109.9), (368, 12, 2305, 111.9), (368, 12, 2365, 114.1), (368, 12, 2430, 139.7),
    (368, 12, 2490, 168.5), (368, 12, 2555, 173.2), (368, 12, 2615, 174.7), (368, 12, 2680, 177.0),
]

print(f"{'ep':>4} {'anc':>4} {'step':>6} {'ref_true_yaw':>12} {'computed_true_yaw':>17} {'sign_ok?':>9} {'icp_yaw':>9} {'yaw_err':>8} "
      f"{'z_resid_true':>13} {'z_resid_icp':>12} {'n_true':>7} {'n_icp':>6}")

results = []
for ep, anchor_idx, step_num, true_yaw_deg in CASES:
    anchor, step = load(ep, anchor_idx, step_num)
    anchor_xyz = np.asarray(anchor["local_map_points_xyz_body"], dtype=np.float32)
    current_xyz = np.asarray(step["local_map_points_xyz_body"], dtype=np.float32)
    if len(anchor_xyz) < 20 or len(current_xyz) < 20:
        continue
    anchor_xy_ds = voxel_downsample_xyz(anchor_xyz, voxel_size_m=0.10, max_points=512)
    current_xy_ds = voxel_downsample_xyz(current_xyz, voxel_size_m=0.10, max_points=512)

    # True transform, computed directly from ground truth world poses
    dtheta_true, dx_true, dy_true = true_relative_transform(anchor["world_pose"], step["robot_world_pose"])

    # ICP-preferred (possibly wrong) transform: real 24-seed sweep, same as production
    yaw_seeds = [math.radians(d) for d in range(-180, 180, 15)]
    scored, summaries, metrics = icp_seed_sweep_2d(
        anchor_xy_ds[:, :2], current_xy_ds[:, :2], yaw_seeds,
        max_iterations=16, correspondence_threshold_m=0.45, objective="point_to_point",
    )
    if not summaries:
        continue
    best = summaries[0]
    icp_theta = math.radians(best["estimated_anchor_dtheta_deg"])
    icp_translation = [best["estimated_anchor_dx_m"], best["estimated_anchor_dy_m"]]
    icp_yaw_deg = math.degrees(icp_theta)

    z_true, n_true = height_residuals(anchor_xyz, current_xyz, dtheta_true, [dx_true, dy_true])
    z_icp, n_icp = height_residuals(anchor_xyz, current_xyz, icp_theta, icp_translation)

    computed_true_yaw_deg = math.degrees(dtheta_true)
    sign_ok = abs(wrap_deg(computed_true_yaw_deg - true_yaw_deg)) < 5.0
    yaw_err = abs(wrap_deg(icp_yaw_deg - true_yaw_deg))
    print(f"{ep:>4} {anchor_idx:>4} {step_num:>6} {true_yaw_deg:>12.1f} {computed_true_yaw_deg:>17.1f} "
          f"{str(sign_ok):>9} {icp_yaw_deg:>9.1f} {yaw_err:>8.1f} "
          f"{z_true if z_true is not None else -1:>13.3f} {z_icp if z_icp is not None else -1:>12.3f} "
          f"{n_true or 0:>7.0f} {n_icp or 0:>6.0f}", flush=True)
    results.append(dict(ep=ep, anchor=anchor_idx, step=step_num, yaw_err=yaw_err, z_true=z_true, z_icp=z_icp))

print()
big_err = [r for r in results if r["yaw_err"] > 20 and r["z_true"] is not None and r["z_icp"] is not None]
print(f"n cases with real >20deg yaw error and both z residuals computed: {len(big_err)}")
if big_err:
    better = sum(1 for r in big_err if r["z_true"] < r["z_icp"] * 0.8)
    similar = sum(1 for r in big_err if abs(r["z_true"] - r["z_icp"]) <= 0.02)
    worse = sum(1 for r in big_err if r["z_true"] > r["z_icp"] * 1.2)
    print(f"true-transform height residual clearly BETTER than icp-wrong: {better}/{len(big_err)}")
    print(f"roughly SIMILAR (within 2cm): {similar}/{len(big_err)}")
    print(f"true-transform height residual clearly WORSE (icp wins even in z): {worse}/{len(big_err)}")
