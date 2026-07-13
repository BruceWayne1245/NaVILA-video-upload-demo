"""
Correlative occupancy-grid yaw verifier (survey's "Option B", Cartographer/
Olson-style), offline-only per investigations/2026-07-13-.../GLOBAL_REGISTRATION_CHECK.md's
recommendation: this is a genuinely DIFFERENT scoring function (2D occupancy-grid
FFT cross-correlation, not point-to-point nearest-neighbor residual), not another
search strategy layered on the same ICP metric that check already ruled out.

For a fixed yaw, occupancy-grid cross-correlation gives the GLOBALLY best
translation for that yaw directly (the correlation peak), not an iteratively-
refined local one -- so combined with a yaw sweep this is a genuinely global
search over the full (yaw, dx, dy) space, using a different cost (grid-cell
overlap count) than ICP's inlier/residual metric.
"""
import json, math, glob, sys
import numpy as np
from scipy.signal import fftconvolve
from scipy.ndimage import gaussian_filter

sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")
from relocalization import voxel_downsample_2d, quat_wxyz_to_matrix, icp_rigid_transform_2d, _icp_score

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_icp_replay_capture_hard11_20260706_accumulated_ep"

TARGETS = [(367, 8), (368, 12)]

VOXEL_SIZE_M = 0.10
MAX_POINTS = 512
GRID_EXTENT_M = 6.0
GRID_RES_M = 0.06
YAW_STEP_DEG = 2.0
GRID_N = int(round(2 * GRID_EXTENT_M / GRID_RES_M))
BLUR_SIGMA_CELLS = 0.45 / GRID_RES_M / 2.0  # ~half the ICP correspondence threshold, in grid cells


def rasterize(points_xy):
    grid = np.zeros((GRID_N, GRID_N), dtype=np.float32)
    idx = np.floor((points_xy + GRID_EXTENT_M) / GRID_RES_M).astype(np.int64)
    valid = (idx[:, 0] >= 0) & (idx[:, 0] < GRID_N) & (idx[:, 1] >= 0) & (idx[:, 1] < GRID_N)
    idx = idx[valid]
    grid[idx[:, 0], idx[:, 1]] = 1.0
    return gaussian_filter(grid, sigma=BLUR_SIGMA_CELLS)


def rotate_points(points_xy, theta):
    c, s = math.cos(theta), math.sin(theta)
    R = np.array([[c, -s], [s, c]], dtype=np.float64)
    return (R @ points_xy.T).T


def correlative_yaw_search(anchor_xy, current_xy, yaw_seeds_deg):
    current_grid = rasterize(current_xy)
    current_occupied = float(current_grid.sum())
    best = None  # (score, theta_rad, dx_m, dy_m)
    curve = []
    for deg in yaw_seeds_deg:
        theta = math.radians(deg)
        rotated = rotate_points(anchor_xy, theta)
        anchor_grid = rasterize(rotated)
        anchor_occupied = float(anchor_grid.sum())
        if anchor_occupied == 0 or current_occupied == 0:
            curve.append((deg, 0.0))
            continue
        # cross-correlation: corr[i,j] = sum_{u,v} current_grid[u,v] * anchor_grid[u-i+c, v-j+c]
        corr = fftconvolve(current_grid, anchor_grid[::-1, ::-1], mode="same")
        peak_idx = np.unravel_index(np.argmax(corr), corr.shape)
        peak_val = float(corr[peak_idx])
        score = peak_val / min(anchor_occupied, current_occupied)
        # peak_idx is the shift (in grid cells) of anchor_grid's center-of-frame
        # relative to current_grid's, in the "same"-mode convolution convention:
        # a peak at the grid's own center means zero translation.
        center = GRID_N // 2
        dx_m = (peak_idx[0] - center) * GRID_RES_M
        dy_m = (peak_idx[1] - center) * GRID_RES_M
        curve.append((deg, score))
        if best is None or score > best[0]:
            best = (score, theta, dx_m, dy_m)
    return best, curve


def angular_diff_deg(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def yaw_from_quat(q):
    w, x, y, z = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


for ep, anchor_idx in TARGETS:
    print(f"\n{'='*90}\nep{ep} anchor{anchor_idx}\n{'='*90}")
    d = f"{BASE}/{PREFIX}{ep}"
    anchors_raw = json.load(open(f"{d}/icp_replay_dataset/anchors.json"))["anchors"]
    anchor = next(a for a in anchors_raw if a["index"] == anchor_idx)
    anchor_xyz_full = np.asarray(anchor["local_map_points_xyz_body"], dtype=np.float32)
    anchor_world_pose = anchor["world_pose"]
    anchor_xy = voxel_downsample_2d(anchor_xyz_full[:, :2], voxel_size_m=VOXEL_SIZE_M, max_points=MAX_POINTS)

    step_files = sorted(glob.glob(f"{d}/icp_replay_dataset/steps/*.json"))
    candidates = []
    for f in step_files[::5]:
        try:
            s = json.load(open(f))
        except json.JSONDecodeError:
            continue
        pts = s.get("local_map_points_xyz_body")
        if pts is None:
            continue
        rx, ry = s["robot_world_pose"][0], s["robot_world_pose"][1]
        ax, ay = anchor_world_pose[0], anchor_world_pose[1]
        R = quat_wxyz_to_matrix(s["robot_world_pose"][3:7])
        world_offset = np.array([ax - rx, ay - ry, 0.0])
        body_offset = R.T @ world_offset
        dist = math.hypot(body_offset[0], body_offset[1])
        if 0.2 < dist < 2.5:
            candidates.append(s)
    if len(candidates) > 8:
        idxs = np.linspace(0, len(candidates) - 1, 8).astype(int)
        candidates = [candidates[i] for i in idxs]

    for s in candidates:
        current_xyz_full = np.asarray(s["local_map_points_xyz_body"], dtype=np.float32)
        current_xy = voxel_downsample_2d(current_xyz_full[:, :2], voxel_size_m=VOXEL_SIZE_M, max_points=MAX_POINTS)

        true_yaw = yaw_from_quat(s["robot_world_pose"][3:7]) - yaw_from_quat(anchor_world_pose[3:7])
        true_yaw_deg = math.degrees(math.atan2(math.sin(true_yaw), math.cos(true_yaw)))

        yaw_seeds = list(np.arange(-180, 180, YAW_STEP_DEG))
        corr_best, curve = correlative_yaw_search(anchor_xy, current_xy, yaw_seeds)
        corr_score, corr_theta, corr_dx, corr_dy = corr_best
        corr_err = angular_diff_deg(math.degrees(corr_theta), true_yaw_deg)

        # ICP 24-seed baseline for direct comparison, same as global_registration_check
        icp_seeds_deg = list(range(-180, 180, 15))
        icp_best, icp_best_score = None, -1.0
        for deg in icp_seeds_deg:
            r = icp_rigid_transform_2d(anchor_xy, current_xy, initial_theta=math.radians(deg),
                                        max_iterations=16, correspondence_threshold_m=0.45, objective="point_to_point")
            if r is None:
                continue
            sc = _icp_score(r, 0.45)
            if sc > icp_best_score:
                icp_best_score = sc
                icp_best = r
        icp_err = angular_diff_deg(math.degrees(icp_best["theta"]), true_yaw_deg) if icp_best else None

        print(f"  step={s['step']:6d} true_yaw={true_yaw_deg:7.1f}  |  "
              f"ICP(24seed): err={icp_err:6.1f} score={icp_best_score:.3f}  |  "
              f"CORRELATIVE: err={corr_err:6.1f} score={corr_score:.3f}  dx={corr_dx:+.2f} dy={corr_dy:+.2f}")
