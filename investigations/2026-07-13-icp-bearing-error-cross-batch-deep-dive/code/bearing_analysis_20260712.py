import json, math, os, glob
import numpy as np
from collections import Counter, defaultdict

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_short_baseline_hard11_20260712_accumulated_ep"

# only the 7 round-trip-succeeded episodes (from summary.tsv), matching this
# project's established practice of restricting bearing-accuracy analysis to
# usable episodes (measurement JSON + relocalization events present)
EPISODES = {
    4: "measurements/7.json",
    187: "measurements/280.json",
    367: "measurements/601.json",
    368: "measurements/602.json",
    678: "measurements/1164.json",
    994: "measurements/1699.json",
    1040: "measurements/1760.json",
}

INTERVAL = 5  # route_relocalization_interval_updates for this batch


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
heading_reliable_rows = []

for ep, meas_rel in EPISODES.items():
    d = f"{BASE}/{PREFIX}{ep}"
    meas = json.load(open(f"{d}/{meas_rel}"))
    rt = meas["round_trip"]
    anchors = rt["route_memory"]["anchors"]
    anchor_world_pose = {}
    for a in anchors:
        wp = a.get("metadata", {}).get("world_pose")
        if wp is not None:
            anchor_world_pose[a["index"]] = wp

    traj_files = glob.glob(f"{d}/trajectories/*.jsonl")
    traj_file = traj_files[0]
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
            match_class=rec.get("match_class"),
            near_tie=rec.get("icp_near_tie_basin_count"),
            corridor=rec.get("corridor_degeneracy_ratio"),
            yaw_observability=localiz.get("yaw_observability"),
            yaw_peak_width=yaw_curve.get("yaw_peak_width_deg"),
            yaw_norm_entropy=yaw_curve.get("yaw_score_normalized_entropy"),
            sc_agree=sc.get("icp_scan_context_yaw_agreement_deg"),
        ))
    print(f"ep{ep}: {n_total} pose_candidate records, {n_matched} with ground truth + estimate", flush=True)

    # anchor_heading_reliable from the actually-reported/fused events (step 5's target)
    for ev in rt["route_memory"]["relocalization_events"]:
        heading_reliable_rows.append(dict(ep=ep, reliable=ev.get("anchor_heading_reliable")))

print()
print(f"TOTAL readings: {len(all_rows)}")

errs = np.array([r["bearing_err"] for r in all_rows])
over10 = errs > 10.0
print(f"bearing error > 10 deg: {over10.sum()}/{len(errs)} = {100*over10.mean():.1f}%")
print(f"pooled median={np.median(errs):.2f} mean={errs.mean():.2f} p90={np.percentile(errs,90):.2f}")
print()

bucket = [r for r, o in zip(all_rows, over10) if o]
print(f"--- Breakdown of the {len(bucket)} readings with bearing_err > 10 deg ---")

flagged_matchclass = [r for r in bucket if r["match_class"] in ("ambiguous_high_confidence", "partial_pose_degenerate", "height_inconsistent_2p5d")]
flagged_neartie = [r for r in bucket if (r["near_tie"] or 0) > 0]
flagged_corridor = [r for r in bucket if (r["corridor"] or 0) < 0.15]
flagged_yawobs_weak = [r for r in bucket if r["yaw_observability"] == "weak"]
clean_confidently_wrong = [r for r in bucket if r["match_class"] == "clean_full_pose" and (r["near_tie"] or 0) == 0]

print(f"match_class self-flagged (ambiguous/degenerate/height-inconsistent): {len(flagged_matchclass)} ({100*len(flagged_matchclass)/len(bucket):.1f}%)")
print(f"icp_near_tie_basin_count > 0: {len(flagged_neartie)} ({100*len(flagged_neartie)/len(bucket):.1f}%)")
print(f"corridor_degeneracy_ratio < 0.15 (skip-threshold): {len(flagged_corridor)} ({100*len(flagged_corridor)/len(bucket):.1f}%)")
print(f"yaw_observability == 'weak': {len(flagged_yawobs_weak)} ({100*len(flagged_yawobs_weak)/len(bucket):.1f}%)")
print(f"'confidently wrong' (clean_full_pose + near_tie==0, no diagnostic fires): {len(clean_confidently_wrong)} ({100*len(clean_confidently_wrong)/len(bucket):.1f}%)")
print()

any_flag = [r for r in bucket if (r["match_class"] in ("ambiguous_high_confidence", "partial_pose_degenerate", "height_inconsistent_2p5d")) or ((r["near_tie"] or 0) > 0) or (r["yaw_observability"] == "weak")]
print(f"Any-of-(match_class flag OR near_tie>0 OR yaw_observability=weak) explains: {len(any_flag)}/{len(bucket)} = {100*len(any_flag)/len(bucket):.1f}%")
print(f"UNEXPLAINED (none of the above fire): {len(bucket)-len(any_flag)}/{len(bucket)} = {100*(len(bucket)-len(any_flag))/len(bucket):.1f}%")
print()

match_class_counts = Counter(r["match_class"] for r in bucket)
print("match_class distribution within >10 deg bucket:", dict(match_class_counts))
print()

# per-episode breakdown
print("--- per-episode >10deg rate ---")
by_ep = defaultdict(list)
for r in all_rows:
    by_ep[r["ep"]].append(r["bearing_err"])
for ep in sorted(by_ep):
    arr = np.array(by_ep[ep])
    print(f"ep{ep}: n={len(arr)}, >10deg={100*(arr>10).mean():.1f}%, median={np.median(arr):.2f}, mean={arr.mean():.2f}")
print()

# per-(ep,anchor) group concentration, mirroring the 2026-07-08 methodology
print("--- (episode,anchor) groups with mean bearing error > 45 deg ---")
by_group = defaultdict(list)
for r in all_rows:
    by_group[(r["ep"], r["anchor"])].append(r["bearing_err"])
bad_groups = []
for k, v in by_group.items():
    arr = np.array(v)
    if arr.mean() > 45:
        bad_groups.append((k, len(arr), arr.mean()))
bad_groups.sort(key=lambda x: -x[2])
n_bad_readings = sum(c for _, c, _ in bad_groups)
print(f"{len(bad_groups)}/{len(by_group)} groups have mean bearing error > 45 deg, covering {n_bad_readings}/{len(all_rows)} = {100*n_bad_readings/len(all_rows):.1f}% of readings")
for k, c, m in bad_groups:
    print(f"  ep{k[0]} anchor{k[1]}: n={c}, mean={m:.1f} deg")
print()

# step 5 (short-baseline) live result
rel = [r["reliable"] for r in heading_reliable_rows]
n_false = sum(1 for x in rel if x is False)
n_true = sum(1 for x in rel if x is True)
n_none = sum(1 for x in rel if x is None)
print(f"--- step 5 (short-baseline disambiguation) live result: anchor_heading_reliable across {len(rel)} reported/fused events ---")
print(f"True={n_true} ({100*n_true/len(rel):.1f}%), False={n_false} ({100*n_false/len(rel):.1f}%), None={n_none}")

json.dump(all_rows, open("/tmp/claude-1006/-home-teambruce/317da1c8-fb11-4286-93b7-7e49924245bb/scratchpad/bearing_rows_20260712.json", "w"))
