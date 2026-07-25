#!/usr/bin/env python3
"""Build a REPRESENTATIVE Stage-1 evaluation dataset across ALL anchors in
ALL 58 usable episodes of the 2026-07-24 100ep run (reliability_v11_decision_
shadow_rgbd_100ep_20260724) -- not just the 21 pre-selected "known
confidently-wrong" anchors used earlier this session, which the user
correctly flagged as an unrepresentative, heavily-anchor-imbalanced sample
(76% of all "confidently_wrong" data points came from a single anchor,
785/8).

For every (anchor, sampled return-phase step) pair, this computes THREE
independent things, matching the user's requested two-phase plan:
  1. Pure-geometry Stage-1 ground truth (which of the 4 camera-pairing
     combos has the smallest world-heading alignment angle) -- reuses
     stage1_ground_truth_eval.py's method exactly, no vision involved.
  2. The actual Stage-1 selector outputs to evaluate against that ground
     truth: LoFTR match-count pick (cheap, always computed) across the 4
     combos.
  3. Whether THIS (anchor, step) is a genuine LiDAR "confidently_wrong" ICP
     case (full 24-seed icp_seed_sweep_2d, exact same production
     methodology as replay.py earlier this session) -- so the final
     analysis can report Stage-1 accuracy BOTH on the full representative
     sample AND restricted to the confidently-wrong subset within it, for
     a fair apples-to-apples comparison (per the user's explicit request:
     build the general baseline FIRST, then look at what the known-hard
     cases look like inside it -- not the reverse).

Runs fully unattended: designed to be launched via `systemd-run --user`
(survives session disconnect, per this project's established practice --
see memory feedback_long_jobs_need_tmux.md) and checkpoints incrementally
(writes the output file after every anchor, not just at the end) so a
crash partway through does not lose completed work and the job is
resumable.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
sys.path.insert(0, os.path.join(BENCH, "scripts"))

from relocalization import icp_seed_sweep_2d, voxel_downsample_2d  # noqa: E402
import relocalization as reloc  # noqa: E402
from route_memory_agent import relative_delta, world_pose_7_to_2d  # noqa: E402

RUN_TAG = "reliability_v11_decision_shadow_rgbd_100ep_20260724"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(OUT_DIR, "representative_dataset.json")
PROGRESS_LOG = os.path.join(OUT_DIR, "representative_dataset_build.progress.log")

YAW_SEEDS = [math.radians(float(d)) for d in range(-180, 180, 15)]  # 24 seeds, matches production
STEPS_PER_ANCHOR = 15
BEARING_ERR_TOL_DEG = 30.0
CONFIDENT_THRESHOLD = 0.9


def log(msg):
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(line + "\n")


def result_dir(ep: int) -> str:
    return (
        f"{BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_"
        f"2024-09-25_23-22-02_{RUN_TAG}_ep{ep}/icp_replay_dataset"
    )


def load_npz_descriptor(path: str):
    if not os.path.isfile(path):
        return None
    try:
        with np.load(path) as data:
            return {k: data[k] for k in data.files}
    except Exception:
        return None


def bearing_deg(dx, dy):
    return math.degrees(math.atan2(dy, dx))


def angdiff_unsigned(a, b):
    return abs(math.degrees(math.atan2(math.sin(math.radians(a - b)), math.cos(math.radians(a - b)))))


def confidence_of(result):
    overlap = float(result["overlap_ratio"])
    residual = float(result["median_residual_m"])
    return min(1.0, overlap * max(0.0, 1.0 - residual / 0.45) * 1.5)


def list_all_episodes():
    summary = f"{BENCH}/batch_logs/{RUN_TAG}/summary.tsv"
    episodes = []
    seen = set()
    with open(summary) as f:
        f.readline()
        for line in f:
            parts = line.strip().split("\t")
            ep = int(parts[0])
            if ep not in seen:
                seen.add(ep)
                episodes.append(ep)
    return episodes


def get_anchors_for_episode(ep):
    path = os.path.join(result_dir(ep), "anchors.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data["anchors"]
    except (json.JSONDecodeError, KeyError):
        return None


def get_step_files(ep, cap=STEPS_PER_ANCHOR):
    steps_dir = os.path.join(result_dir(ep), "steps")
    if not os.path.isdir(steps_dir):
        return []
    import glob
    files = sorted(glob.glob(os.path.join(steps_dir, "frame_step*.json")))
    files = files[::5]  # mirror relocalization cadence
    if len(files) > cap:
        idx = np.linspace(0, len(files) - 1, cap).astype(int)
        files = [files[i] for i in idx]
    return files


def load_step_data(fp):
    try:
        with open(fp) as f:
            frame = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    pts = frame.get("local_map_points_xyz_body")
    if not pts:
        return None
    return {
        "step": int(frame["step"]),
        "pose2d": world_pose_7_to_2d(frame["robot_world_pose"]),
        "points_xyz": np.asarray(pts, dtype=np.float32),
    }


def process_anchor(ep, anchor_rec, step_cache):
    anchor_idx = int(anchor_rec["index"])
    anchor_pts = anchor_rec.get("local_map_points_xyz_body")
    anchor_world_pose = anchor_rec.get("world_pose")
    rgbd_file = anchor_rec.get("rgbd_file")
    if not anchor_pts or anchor_world_pose is None or not rgbd_file:
        return []

    anchor_pose2d = world_pose_7_to_2d(anchor_world_pose)
    anchor_pts_xyz = np.asarray(anchor_pts, dtype=np.float32)
    anchor_pts_2d = voxel_downsample_2d(anchor_pts_xyz, voxel_size_m=0.10, max_points=512)
    if len(anchor_pts_2d) < 12:
        return []

    anchor_rgbd = load_npz_descriptor(os.path.join(result_dir(ep), rgbd_file))
    if anchor_rgbd is None or "rgb" not in anchor_rgbd:
        return []
    anchor_front = anchor_rgbd
    anchor_rear = reloc.build_rear_view_descriptor(anchor_rgbd)

    results = []
    for step_data in step_cache:
        if step_data is None:
            continue
        cur_pose2d = step_data["pose2d"]
        cur_pts_2d = voxel_downsample_2d(step_data["points_xyz"], voxel_size_m=0.10, max_points=512)
        if len(cur_pts_2d) < 12:
            continue

        # --- ground truth (pure geometry) ---
        gt_dx, gt_dy, gt_dtheta = relative_delta(cur_pose2d, anchor_pose2d)
        gt_bearing = bearing_deg(gt_dx, gt_dy)
        gt_distance = math.hypot(gt_dx, gt_dy)
        ayaw_deg = math.degrees(anchor_pose2d[2])
        cyaw_deg = math.degrees(cur_pose2d[2])
        align_angles = {
            "anchorFront_currentFront": angdiff_unsigned(ayaw_deg, cyaw_deg),
            "anchorFront_currentRear": angdiff_unsigned(ayaw_deg, cyaw_deg + 180.0),
            "anchorRear_currentFront": angdiff_unsigned(ayaw_deg + 180.0, cyaw_deg),
            "anchorRear_currentRear": angdiff_unsigned(ayaw_deg + 180.0, cyaw_deg + 180.0),
        }
        gt_best_combo = min(align_angles, key=lambda k: align_angles[k])

        # --- ICP 24-seed confidently-wrong flag ---
        confidently_wrong = False
        icp_top1_confident = None
        icp_top1_pose_bad = None
        scored, _summ, _metrics = icp_seed_sweep_2d(
            anchor_pts_2d, cur_pts_2d, YAW_SEEDS,
            max_iterations=16, correspondence_threshold_m=0.45, objective="point_to_point",
        )
        if scored:
            ranked = sorted(scored, key=lambda item: -item[0])
            top1_result = ranked[0][1]
            top1_conf = confidence_of(top1_result)
            tdx, tdy = float(top1_result["translation"][0]), float(top1_result["translation"][1])
            top1_bearing_err = angdiff_unsigned(bearing_deg(tdx, tdy), gt_bearing)
            top1_distance_err = abs(math.hypot(tdx, tdy) - gt_distance)
            icp_top1_pose_bad = (top1_bearing_err > BEARING_ERR_TOL_DEG) or (top1_distance_err > 0.5)
            icp_top1_confident = top1_conf >= CONFIDENT_THRESHOLD
            confidently_wrong = bool(icp_top1_confident and icp_top1_pose_bad)

        # --- Stage-1 selectors: match-count pick across the 4 combos ---
        current_front = step_data.get("rgbd_desc")
        combo_matches = {}
        if current_front is not None:
            current_rear = reloc.build_rear_view_descriptor(current_front)
            combo_views = {
                "anchorFront_currentFront": (anchor_front, current_front),
                "anchorFront_currentRear": (anchor_front, current_rear),
                "anchorRear_currentFront": (anchor_rear, current_front),
                "anchorRear_currentRear": (anchor_rear, current_rear),
            }
            for name, (a_view, c_view) in combo_views.items():
                a_gray = reloc.descriptor_rgb_gray(a_view)
                c_gray = reloc.descriptor_rgb_gray(c_view)
                if a_gray is None or c_gray is None:
                    combo_matches[name] = None
                    continue
                a_uv, c_uv, _meta = reloc.loftr_match_points(a_gray, c_gray)
                combo_matches[name] = int(len(a_uv)) if a_uv is not None else 0

        match_count_pick = None
        valid_counts = {k: v for k, v in combo_matches.items() if v is not None}
        if valid_counts:
            match_count_pick = max(valid_counts, key=lambda k: valid_counts[k])

        results.append({
            "episode": ep, "anchor": anchor_idx, "step": step_data["step"],
            "gt_distance": gt_distance, "gt_dtheta_deg": math.degrees(gt_dtheta),
            "gt_best_combo": gt_best_combo, "alignment_angles": align_angles,
            "confidently_wrong": confidently_wrong,
            "match_count_pick": match_count_pick, "combo_matches": combo_matches,
        })
    return results


def main():
    episodes = list_all_episodes()
    log(f"Total episodes in run: {len(episodes)}")

    if os.path.isfile(OUT_PATH):
        with open(OUT_PATH) as f:
            all_results = json.load(f)
        done_anchors = {(r["episode"], r["anchor"]) for r in all_results}
        log(f"Resuming: {len(all_results)} samples already done, {len(done_anchors)} anchors covered")
    else:
        all_results = []
        done_anchors = set()

    n_episodes_processed = 0
    for ep in episodes:
        anchors = get_anchors_for_episode(ep)
        if anchors is None:
            continue
        n_episodes_processed += 1

        step_files = get_step_files(ep)
        if not step_files:
            log(f"ep{ep}: no step files, skipping episode ({len(anchors)} anchors)")
            continue
        step_cache = []
        for fp in step_files:
            sd = load_step_data(fp)
            if sd is not None:
                step_num = sd["step"]
                rgbd_path = os.path.join(result_dir(ep), "rgbd", f"rgbd_step{step_num:06d}.npz")
                sd["rgbd_desc"] = load_npz_descriptor(rgbd_path)
            step_cache.append(sd)

        t0 = time.time()
        n_new = 0
        for anchor_rec in anchors:
            anchor_idx = int(anchor_rec["index"])
            key = (ep, anchor_idx)
            if key in done_anchors:
                continue
            try:
                results = process_anchor(ep, anchor_rec, step_cache)
            except Exception as exc:
                log(f"ERROR ep{ep} anchor{anchor_idx}: {exc}")
                results = []
            all_results.extend(results)
            done_anchors.add(key)
            n_new += 1

        if n_new > 0:
            with open(OUT_PATH, "w") as f:
                json.dump(all_results, f)
            log(f"ep{ep}: {n_new} new anchors processed ({len(anchors)} total), "
                f"{time.time()-t0:.1f}s, total_samples={len(all_results)}, total_anchors_done={len(done_anchors)}")

    log(f"DONE. episodes_processed={n_episodes_processed}, total_anchors={len(done_anchors)}, "
        f"total_samples={len(all_results)}")


if __name__ == "__main__":
    main()
