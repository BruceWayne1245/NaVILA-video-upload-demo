import json, math, glob
import numpy as np
from collections import Counter, defaultdict

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_promotion_use_raw_estimates_hard11_20260710_accumulated_ep"

EPISODES = {
    4: "measurements/7.json",
    134: "measurements/194.json",
    367: "measurements/601.json",
    368: "measurements/602.json",
    678: "measurements/1164.json",
    994: "measurements/1699.json",
    1040: "REPAIRED",
}
REPAIRED_1040 = "/tmp/claude-1006/-home-teambruce/317da1c8-fb11-4286-93b7-7e49924245bb/scratchpad/ep1040_10_repaired.json"
INTERVAL = 5


def quat_wxyz_to_matrix(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def body_frame_offset(robot_pos, robot_quat, target_pos):
    R = quat_wxyz_to_matrix(robot_quat)
    world_offset = np.array(target_pos, dtype=np.float64) - np.array(robot_pos, dtype=np.float64)
    body_offset = R.T @ world_offset
    return float(body_offset[0]), float(body_offset[1])


def angular_diff_deg(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


all_rows = []

for ep, meas_rel in EPISODES.items():
    d = f"{BASE}/{PREFIX}{ep}"
    if meas_rel == "REPAIRED":
        meas = json.load(open(REPAIRED_1040))
    else:
        meas = json.load(open(f"{d}/{meas_rel}"))
    rt = meas["round_trip"]
    anchors = rt["route_memory"]["anchors"]
    anchor_world_pose = {}
    for a in anchors:
        wp = a.get("metadata", {}).get("world_pose")
        if wp is not None:
            anchor_world_pose[a["index"]] = wp

    traj_file = glob.glob(f"{d}/trajectories/*.jsonl")[0]
    return_rows = []
    with open(traj_file) as f:
        for line in f:
            r = json.loads(line)
            if r["phase"] == "return":
                return_rows.append(r)

    cov = rt["route_relocalization_diagnostics"]["covisibility_records"]
    n_total = 0
    n_matched = 0
    for rec in cov:
        if rec.get("outcome") != "pose_candidate":
            continue
        n_total += 1
        anchor_idx = rec["anchor_index"]
        if anchor_idx not in anchor_world_pose:
            continue
        attempt = rec["attempt"]
        row_idx = 0 if attempt == 1 else (attempt - 1) * INTERVAL - 1
        if row_idx >= len(return_rows):
            row_idx = len(return_rows) - 1
        row = return_rows[row_idx]
        robot_pos = row["position"]
        robot_quat = row["quaternion_wxyz"]
        target_pos = anchor_world_pose[anchor_idx][:3]
        dx_true, dy_true = body_frame_offset(robot_pos, robot_quat, target_pos)
        true_dist = math.hypot(dx_true, dy_true)
        true_bearing = math.degrees(math.atan2(dy_true, dx_true))
        est_bearing = rec.get("estimated_bearing_to_anchor_deg")
        if est_bearing is None:
            continue
        bearing_err = angular_diff_deg(est_bearing, true_bearing)
        n_matched += 1

        yaw_curve = rec.get("yaw_curve") or {}
        localiz = rec.get("localizability") or {}
        sc = rec.get("scan_context_yaw_check") or {}

        all_rows.append(dict(
            ep=ep, anchor=anchor_idx, attempt=attempt,
            bearing_err=bearing_err, true_dist=true_dist,
            est_dist=rec.get("estimated_distance_to_anchor_m"),
            match_class=rec.get("match_class"),
            near_tie=rec.get("icp_near_tie_basin_count"),
            corridor=rec.get("corridor_degeneracy_ratio"),
            overlap=rec.get("overlap_ratio"),
            inlier=rec.get("inlier_count"),
            confidence=rec.get("confidence"),
            median_residual=rec.get("median_residual_m"),
            yaw_observability=(localiz.get("yaw_observability") if localiz else None),
            yaw_peak_width=(yaw_curve.get("yaw_peak_width_deg") if yaw_curve else None),
            yaw_norm_entropy=(yaw_curve.get("yaw_score_normalized_entropy") if yaw_curve else None),
            sc_agree=(sc.get("icp_scan_context_yaw_agreement_deg") if sc else None),
        ))
    print(f"ep{ep}: {n_total} pose_candidate records, {n_matched} with ground truth + estimate", flush=True)

print()
print(f"TOTAL readings: {len(all_rows)}")
errs = np.array([r["bearing_err"] for r in all_rows])
over10 = errs > 10.0
print(f"bearing error > 10 deg: {over10.sum()}/{len(errs)} = {100*over10.mean():.1f}%")
print(f"pooled median={np.median(errs):.2f} mean={errs.mean():.2f} p90={np.percentile(errs,90):.2f}")

json.dump(all_rows, open("/tmp/claude-1006/-home-teambruce/317da1c8-fb11-4286-93b7-7e49924245bb/scratchpad/bearing_rows_20260710.json", "w"))
