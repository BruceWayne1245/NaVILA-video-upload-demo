"""Step 3 of the Oracle->Shadow hint-source swap plan: offline-calibrate
hint_action_arbiter's new min_relocalization_confidence threshold using
today's Variant-1 (no-fusion) ep368 run's already-logged
route_memory.relocalization_events (the reported/fused per-attempt estimate
the arbiter actually consumes), checked against ground truth. No new live
run needed -- this run already had --route_hint_source=oracle (real
navigation) with sequential_pair computed in parallel as the shadow.
"""
import json, math, glob
import numpy as np

D = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_no_fusion_ep368_20260713_accumulated_ep368"
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


def body_frame_offset(robot_pose, target_pose):
    R = quat_wxyz_to_matrix(robot_pose[3:7])
    wo = np.array(target_pose[:3]) - np.array(robot_pose[:3])
    result = R.T @ wo
    return float(result[0]), float(result[1])


def angular_diff_deg(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


events = rt["route_memory"]["relocalization_events"]
rows = []
for i, ev in enumerate(events):
    attempt = i + 1
    aidx = ev.get("anchor_index")
    if aidx not in anchor_world_pose:
        continue
    ridx = 0 if attempt == 1 else (attempt - 1) * INTERVAL - 1
    ridx = min(ridx, len(return_rows) - 1)
    row = return_rows[ridx]
    robot_pose = list(row["position"]) + list(row["quaternion_wxyz"])
    dx_true, dy_true = body_frame_offset(robot_pose, anchor_world_pose[aidx])
    true_bearing = math.degrees(math.atan2(dy_true, dx_true))
    est_bearing = ev.get("bearing_to_anchor_deg")
    conf = ev.get("confidence")
    if est_bearing is None or conf is None:
        continue
    rows.append(dict(err=angular_diff_deg(est_bearing, true_bearing), conf=conf))

errs = np.array([r["err"] for r in rows])
confs = np.array([r["conf"] for r in rows])
print(f"n={len(rows)}, pooled median={np.median(errs):.2f} mean={errs.mean():.2f}")

print("\nconfidence histogram:")
for lo, hi in [(0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 0.99), (0.99, 1.01)]:
    m = (confs >= lo) & (confs < hi)
    if m.sum():
        print(f"  [{lo},{hi}): n={m.sum()} ({100*m.mean():.1f}%), mean={errs[m].mean():.1f} median={np.median(errs[m]):.1f}")

print("\nthreshold sweep:")
for thr in [0.0, 0.5, 0.7, 0.8, 0.85, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98, 0.99]:
    keep = errs[confs >= thr]
    drop = errs[confs < thr]
    print(f"  thr={thr:.2f}: kept={100*len(keep)/len(errs):.1f}% mean={keep.mean():.2f} median={np.median(keep):.2f} "
          f"| dropped n={len(drop)} mean={(drop.mean() if len(drop) else float('nan')):.1f}")
