import json, math, glob
import numpy as np
from collections import defaultdict, Counter

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"

BATCHES = {
    "07-10": ("promotion_use_raw_estimates_hard11_20260710_accumulated",
              {4: "measurements/7.json", 134: "measurements/194.json", 367: "measurements/601.json",
               368: "measurements/602.json", 678: "measurements/1164.json", 994: "measurements/1699.json"}),
    "07-12": ("short_baseline_hard11_20260712_accumulated",
              {4: "measurements/7.json", 187: "measurements/280.json", 367: "measurements/601.json",
               368: "measurements/602.json", 678: "measurements/1164.json", 994: "measurements/1699.json",
               1040: "measurements/1760.json"}),
}
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


all_events = []
for batch_label, (run_tag, episodes) in BATCHES.items():
    prefix = f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{run_tag}_ep"
    for ep, meas_rel in episodes.items():
        d = f"{BASE}/{prefix}{ep}"
        try:
            meas = json.load(open(f"{d}/{meas_rel}"))
        except Exception:
            continue
        rt = meas["round_trip"]
        anchors = rt["route_memory"]["anchors"]
        anchor_world_pose = {a["index"]: a["metadata"]["world_pose"] for a in anchors if a.get("metadata", {}).get("world_pose")}
        traj_files = glob.glob(f"{d}/trajectories/*.jsonl")
        if not traj_files:
            continue
        return_rows = [json.loads(l) for l in open(traj_files[0]) if json.loads(l)["phase"] == "return"]

        cov = rt["route_relocalization_diagnostics"]["covisibility_records"]
        raw_by_attempt_anchor = {}
        for r in cov:
            if r.get("outcome") == "pose_candidate":
                raw_by_attempt_anchor[(r["attempt"], r["anchor_index"])] = r

        events = rt["route_memory"]["relocalization_events"]
        for i, ev in enumerate(events):
            attempt = i + 1
            anchor_idx = ev.get("anchor_index")
            if anchor_idx not in anchor_world_pose:
                continue
            row_idx = 0 if attempt == 1 else (attempt - 1) * INTERVAL - 1
            row_idx = min(row_idx, len(return_rows) - 1)
            row = return_rows[row_idx]
            robot_pose = list(row["position"]) + list(row["quaternion_wxyz"])
            dx_true, dy_true = body_frame_offset(robot_pose, anchor_world_pose[anchor_idx])
            true_bearing_deg = math.degrees(math.atan2(dy_true, dx_true))

            fused_bearing = ev.get("bearing_to_anchor_deg")
            fused_err = angular_diff_deg(fused_bearing, true_bearing_deg) if fused_bearing is not None else None

            raw_rec = raw_by_attempt_anchor.get((attempt, anchor_idx))
            raw_bearing = raw_rec.get("estimated_bearing_to_anchor_deg") if raw_rec else None
            raw_err = angular_diff_deg(raw_bearing, true_bearing_deg) if raw_bearing is not None else None

            all_events.append(dict(
                batch=batch_label, ep=ep, attempt=attempt, anchor=anchor_idx,
                fused_err=fused_err, raw_err=raw_err, backend=ev.get("backend"),
            ))

print(f"total events with both raw+fused available: {sum(1 for e in all_events if e['raw_err'] is not None and e['fused_err'] is not None)}")
both = [e for e in all_events if e["raw_err"] is not None and e["fused_err"] is not None]

fused_errs = np.array([e["fused_err"] for e in both])
raw_errs = np.array([e["raw_err"] for e in both])
print(f"pooled n={len(both)}: raw median={np.median(raw_errs):.2f} mean={raw_errs.mean():.2f}; "
      f"fused median={np.median(fused_errs):.2f} mean={fused_errs.mean():.2f}")
print()

corrupted = [e for e in both if e["fused_err"] > 45 and e["raw_err"] < 15]
fixed = [e for e in both if e["fused_err"] < 15 and e["raw_err"] > 45]
both_bad = [e for e in both if e["fused_err"] > 45 and e["raw_err"] > 45]
both_good = [e for e in both if e["fused_err"] < 15 and e["raw_err"] < 15]

print(f"FUSION-CORRUPTED (raw<15, fused>45): {len(corrupted)}/{len(both)} = {100*len(corrupted)/len(both):.2f}%")
print(f"FUSION-FIXED (raw>45, fused<15):     {len(fixed)}/{len(both)} = {100*len(fixed)/len(both):.2f}%")
print(f"BOTH BAD (raw>45, fused>45):         {len(both_bad)}/{len(both)} = {100*len(both_bad)/len(both):.2f}%")
print(f"BOTH GOOD (raw<15, fused<15):        {len(both_good)}/{len(both)} = {100*len(both_good)/len(both):.2f}%")
print()

print("backend tag distribution among FUSION-CORRUPTED events:")
print(Counter(e["backend"] for e in corrupted))
print()
print("backend tag distribution, ALL events:")
print(Counter(e["backend"] for e in both))
print()

for e in corrupted:
    print(f"  batch={e['batch']} ep{e['ep']} anchor{e['anchor']} attempt{e['attempt']}: raw_err={e['raw_err']:.1f} fused_err={e['fused_err']:.1f} backend={e['backend']}")

json.dump(both, open("/tmp/claude-1006/-home-teambruce/317da1c8-fb11-4286-93b7-7e49924245bb/scratchpad/fusion_check_rows.json", "w"))
