"""Build a per-anchor reliability-label dataset from every historical batch
that has icp_replay_dataset (anchors.json ground-truth point cloud + real
trajectory). Confirmed (2026-08-16): the SAME episode_idx produces byte-
identical outbound anchors across different batches (world_pose, point
count, point coordinates all matched exactly for ep679 across two unrelated
batches) -- outbound is deterministic regardless of which return-phase flags
a given batch used. So every batch that ever ran a given episode_idx is an
independent set of real approach trajectories/match attempts against the
SAME physical anchor point clouds, and can be pooled to get a much more
robust per-anchor reliability label than any single episode's own attempts
would give.

Label: for each (episode_idx, anchor_index), pool every covisibility_record
across every batch instance of that episode_idx, compute each attempt's
TRUE position error (ground truth anchor position vs ground-truth robot
position, compared against what the ICP estimate claimed -- same
methodology used throughout this session), and aggregate into
good_fraction = fraction of pooled attempts with position error <= 0.5m.

Output: one row per (episode_idx, anchor_index) with the anchor's own
(downsampled to 512 pts, matching live max_points) point cloud + world pose
+ route position + the aggregated label + observation count -- this is the
shared substrate for BOTH the hand-engineered-geometric-features model and
the direct point-cloud model.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
import time

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
sys.path.insert(0, SCRIPTS_DIR)
import numpy as np
from relocalization import voxel_downsample_xyz

EVAL_RESULTS = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(OUT_DIR, "anchor_labels.json")
PROGRESS_PATH = os.path.join(OUT_DIR, "build_labels_progress.log")
POS_ERR_GOOD_THRESHOLD_M = 0.5
MAX_POINTS = 512


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a") as f:
        f.write(line + "\n")


def true_delta(pos_xy, yaw_rad, anchor_xy):
    wdx = anchor_xy[0] - pos_xy[0]
    wdy = anchor_xy[1] - pos_xy[1]
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    bx = wdx * c + wdy * s
    by = -wdx * s + wdy * c
    return bx, by


def discover_instances():
    """Return {episode_idx: [run_dir, ...]} for every icp_replay_dataset found."""
    instances = {}
    for d in glob.glob(os.path.join(EVAL_RESULTS, "*", "icp_replay_dataset")):
        run_dir = os.path.dirname(d)
        base = os.path.basename(run_dir)
        m = re.search(r"_ep(\d+)(?:\.[A-Za-z].*)?$", base)
        if not m:
            continue
        eidx = int(m.group(1))
        instances.setdefault(eidx, []).append(run_dir)
    return instances


def latest_measurement(run_dir):
    matches = sorted(glob.glob(os.path.join(run_dir, "measurements", "*.json")), key=os.path.getmtime)
    return matches[-1] if matches else None


def process_episode_group(eidx, run_dirs):
    """Returns list of per-anchor label rows for this episode_idx, pooling
    across every run_dir instance."""
    # canonical anchors: any instance works (verified byte-identical); use the first
    anchors_path = os.path.join(run_dirs[0], "icp_replay_dataset", "anchors.json")
    if not os.path.exists(anchors_path):
        return []
    with open(anchors_path) as f:
        anchors_json = json.load(f)["anchors"]
    anchor_xy = {int(a["index"]): a["world_pose"][:2] for a in anchors_json}
    anchor_pts = {int(a["index"]): a for a in anchors_json}

    # pool (pos_err) observations per anchor_index across ALL run_dir instances
    pooled = {idx: [] for idx in anchor_xy}

    for run_dir in run_dirs:
        meas_path = latest_measurement(run_dir)
        traj_dir = os.path.join(run_dir, "trajectories")
        if meas_path is None or not os.path.isdir(traj_dir):
            continue
        traj_files = glob.glob(os.path.join(traj_dir, "*.jsonl"))
        if not traj_files:
            continue
        try:
            with open(meas_path) as f:
                meas = json.load(f)
        except Exception:
            continue
        covis = (meas.get("round_trip", {}).get("route_relocalization_diagnostics") or {}).get("covisibility_records") or []
        if not covis:
            continue
        try:
            with open(traj_files[0]) as f:
                traj = [json.loads(l) for l in f]
        except Exception:
            continue
        traj_return = [r for r in traj if r.get("phase") == "return"]
        if not traj_return:
            continue
        by_step = {r["step"]: r for r in traj_return}
        steps_sorted = sorted(by_step.keys())
        step_lo, step_hi = steps_sorted[0], steps_sorted[-1]

        by_attempt = {}
        for r in covis:
            by_attempt.setdefault(int(r["attempt"]), []).append(r)
        attempts_sorted = sorted(by_attempt.keys())
        n_att = len(attempts_sorted)
        if n_att == 0:
            continue

        for i, att in enumerate(attempts_sorted):
            frac = i / max(1, n_att - 1)
            approx_step = step_lo + frac * (step_hi - step_lo)
            closest_step = min(steps_sorted, key=lambda s: abs(s - approx_step))
            pos = by_step[closest_step]["position"][:2]
            yaw = by_step[closest_step].get("yaw_rad", 0.0)
            for rec in by_attempt[att]:
                aidx = int(rec["anchor_index"])
                if aidx not in anchor_xy:
                    continue
                est_dx = rec.get("estimated_anchor_dx_m")
                est_dy = rec.get("estimated_anchor_dy_m")
                if est_dx is None or est_dy is None:
                    continue
                true_bx, true_by = true_delta(pos, yaw, anchor_xy[aidx])
                pos_err = math.hypot(true_bx - est_dx, true_by - est_dy)
                pooled[aidx].append(pos_err)

    rows = []
    for aidx, errs in pooled.items():
        if not errs:
            continue
        a = anchor_pts[aidx]
        pts = np.array(a["local_map_points_xyz_body"], dtype=np.float32)
        if pts.ndim != 2 or pts.shape[0] < 12:
            continue  # empty/degenerate captured point cloud (e.g. anchor0 at a teleport moment)
        if len(pts) > MAX_POINTS:
            pts = voxel_downsample_xyz(pts, voxel_size_m=0.10, max_points=MAX_POINTS)
        good = sum(1 for e in errs if e <= POS_ERR_GOOD_THRESHOLD_M)
        errs_sorted = sorted(errs)
        rows.append(dict(
            episode_idx=eidx, anchor_index=aidx,
            n_observations=len(errs), good_fraction=good / len(errs),
            median_pos_err_m=errs_sorted[len(errs_sorted) // 2],
            distance_from_start_m=a["distance_from_start_m"],
            world_pose=a["world_pose"],
            points_xyz=pts.tolist(),
            n_source_batches=len(run_dirs),
        ))
    return rows


def main():
    log("discovering icp_replay_dataset instances...")
    instances = discover_instances()
    log(f"unique episode_idx: {len(instances)}, total instances: {sum(len(v) for v in instances.values())}")

    all_rows = []
    t0 = time.time()
    for i, (eidx, run_dirs) in enumerate(sorted(instances.items())):
        try:
            rows = process_episode_group(eidx, run_dirs)
        except Exception as exc:
            log(f"  ep{eidx} FAILED: {type(exc).__name__}: {exc}")
            rows = []
        all_rows.extend(rows)
        if (i + 1) % 20 == 0 or i == len(instances) - 1:
            elapsed = time.time() - t0
            log(f"[{i+1}/{len(instances)}] processed (elapsed {elapsed/60:.1f}min), "
                f"total anchor rows so far: {len(all_rows)}")
            with open(OUT_PATH, "w") as f:
                json.dump(all_rows, f)

    with open(OUT_PATH, "w") as f:
        json.dump(all_rows, f)
    log(f"ALL DONE. total anchor-label rows: {len(all_rows)}")


if __name__ == "__main__":
    main()
