import json, math, glob
import numpy as np
from collections import defaultdict

D = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_loftr_rear_yaw_check_20260713_ep368_accumulated_ep368"
meas = json.load(open(glob.glob(f"{D}/measurements/*.json")[0]))
rt = meas["round_trip"]
anchors = rt["route_memory"]["anchors"]
anchor_world_pose = {a["index"]: a["metadata"]["world_pose"] for a in anchors if a.get("metadata", {}).get("world_pose")}

traj_file = glob.glob(f"{D}/trajectories/*.jsonl")[0]
return_rows = [json.loads(l) for l in open(traj_file) if json.loads(l)["phase"] == "return"]
INTERVAL = 5


def quat_wxyz_to_matrix(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def yaw_from_quat(q):
    w, x, y, z = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def angular_diff_deg(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


cov = rt["route_relocalization_diagnostics"]["covisibility_records"]
rows = []
for rec in cov:
    if rec.get("outcome") != "pose_candidate":
        continue
    aidx = rec["anchor_index"]
    if aidx not in anchor_world_pose:
        continue
    attempt = rec["attempt"]
    ridx = 0 if attempt == 1 else (attempt - 1) * INTERVAL - 1
    ridx = min(ridx, len(return_rows) - 1)
    row = return_rows[ridx]
    robot_pose = list(row["position"]) + list(row["quaternion_wxyz"])
    true_yaw = yaw_from_quat(robot_pose[3:7]) - yaw_from_quat(anchor_world_pose[aidx][3:7])
    true_yaw_deg = math.degrees(math.atan2(math.sin(true_yaw), math.cos(true_yaw)))

    icp_theta = rec.get("estimated_anchor_dtheta_deg")
    lrc = rec.get("loftr_rear_yaw_check") or {}
    loftr_theta = lrc.get("loftr_rear_dtheta_deg") if lrc.get("available") else None

    icp_err = angular_diff_deg(icp_theta, true_yaw_deg) if icp_theta is not None else None
    loftr_err = angular_diff_deg(loftr_theta, true_yaw_deg) if loftr_theta is not None else None

    rows.append(dict(
        anchor=aidx, attempt=attempt, true_yaw=true_yaw_deg,
        icp_err=icp_err, loftr_err=loftr_err,
        loftr_available=lrc.get("available"), loftr_reason=lrc.get("reason"),
        loftr_inliers=lrc.get("inlier_count"), loftr_matches=lrc.get("loftr_matches"),
    ))

avail = [r for r in rows if r["loftr_available"]]
print(f"total pose_candidate readings: {len(rows)}, loftr_rear available: {len(avail)}")

icp_all = np.array([r["icp_err"] for r in avail])
loftr_all = np.array([r["loftr_err"] for r in avail])
print(f"ALL anchors pooled, n={len(avail)}: ICP mean={icp_all.mean():.1f} median={np.median(icp_all):.1f}; "
      f"LoFTR-rear mean={loftr_all.mean():.1f} median={np.median(loftr_all):.1f}; "
      f"LoFTR beats ICP {100*(loftr_all<icp_all).mean():.1f}%")

by_anchor = defaultdict(list)
for r in avail:
    by_anchor[r["anchor"]].append(r)
print("\nper-anchor: anchor, n, icp_mean, loftr_mean")
for a in sorted(by_anchor):
    rs = by_anchor[a]
    icp = np.array([r["icp_err"] for r in rs])
    loftr = np.array([r["loftr_err"] for r in rs])
    print(f"  {a:>3} {len(rs):>4} {icp.mean():>8.1f} {loftr.mean():>10.1f}")

inliers = np.array([r["loftr_inliers"] for r in avail])
loftr_err = np.array([r["loftr_err"] for r in avail])
print("\nLoFTR inlier_count vs its own accuracy:")
for lo, hi in [(0, 50), (50, 150), (150, 400), (400, 2000)]:
    m = (inliers >= lo) & (inliers < hi)
    if m.sum() == 0:
        continue
    print(f"  inlier_count [{lo},{hi}): n={m.sum()}, mean_err={loftr_err[m].mean():.1f}, median={np.median(loftr_err[m]):.1f}")
