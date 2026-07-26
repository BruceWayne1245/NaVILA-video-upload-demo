#!/usr/bin/env python3
"""Deep-dive the 45 near-zero-distance (<0.01m) confidently_wrong samples
where the vision gate passes but is wrong ~96% of the time. Recomputes the
full pipeline with extra diagnostics not in the production return dict:
planarity of the matched 3-D points (degenerate/near-planar point clouds
make Kabsch's rotation solve ill-conditioned), the Kabsch covariance
matrix's own singular-value ratio (a direct, mathematical rotation-
ambiguity signal, independent of RANSAC's inlier/residual bookkeeping),
and depth range of the matched points.
"""
import json
import math
import os
import sys

import numpy as np

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
sys.path.insert(0, os.path.join(BENCH, "scripts"))
import relocalization as reloc  # noqa: E402

RUN_TAG = "reliability_v11_decision_shadow_rgbd_100ep_20260724"
DATASET_PATH = "/tmp/navila-private-main-20260726/investigations/2026-07-25-representative-stage1-wrong-picks-under-1m/data/representative_dataset.json"


def result_dir(ep):
    return (
        f"{BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_"
        f"2024-09-25_23-22-02_{RUN_TAG}_ep{ep}/icp_replay_dataset"
    )


def load_npz(path):
    with np.load(path) as data:
        return {k: data[k] for k in data.files}


def get_anchor_rgbd(ep, anchor_idx):
    d = result_dir(ep)
    with open(os.path.join(d, "anchors.json")) as f:
        anchors = json.load(f)["anchors"]
    for a in anchors:
        if int(a["index"]) == anchor_idx:
            return load_npz(os.path.join(d, a["rgbd_file"]))
    raise KeyError


def get_current_rgbd(ep, step):
    d = result_dir(ep)
    return load_npz(os.path.join(d, "rgbd", f"rgbd_step{step:06d}.npz"))


def angdiff(a, b):
    return math.degrees(math.atan2(math.sin(math.radians(a - b)), math.cos(math.radians(a - b))))


def diagnose_one(ep, anchor_idx, step, gt_dtheta_deg):
    anchor_rgbd = get_anchor_rgbd(ep, anchor_idx)
    current_rgbd = get_current_rgbd(ep, step)

    anchor_front = anchor_rgbd
    anchor_rear = reloc.build_rear_view_descriptor(anchor_rgbd)
    current_front = current_rgbd
    current_rear = reloc.build_rear_view_descriptor(current_rgbd)
    combos = {
        "anchorFront_currentFront": (anchor_front, current_front),
        "anchorFront_currentRear": (anchor_front, current_rear),
        "anchorRear_currentFront": (anchor_rear, current_front),
        "anchorRear_currentRear": (anchor_rear, current_rear),
    }
    match_points = {}
    match_counts = {}
    for name, (a_view, c_view) in combos.items():
        a_gray = reloc.descriptor_rgb_gray(a_view)
        c_gray = reloc.descriptor_rgb_gray(c_view)
        if a_gray is None or c_gray is None:
            continue
        a_uv, c_uv, _ = reloc.loftr_match_points(a_gray, c_gray)
        if a_uv is None:
            continue
        match_points[name] = (a_uv, c_uv, a_view, c_view)
        match_counts[name] = int(len(a_uv))

    aligned = match_counts.get("anchorFront_currentFront", 0) + match_counts.get("anchorRear_currentRear", 0)
    opposite = match_counts.get("anchorFront_currentRear", 0) + match_counts.get("anchorRear_currentFront", 0)
    total = aligned + opposite
    margin = abs(aligned - opposite) / total if total else 0.0
    winning_class = ("anchorFront_currentFront", "anchorRear_currentRear") if aligned >= opposite \
        else ("anchorFront_currentRear", "anchorRear_currentFront")
    candidates = [c for c in winning_class if c in match_points]
    chosen_combo = max(candidates, key=lambda c: match_counts.get(c, 0))
    anchor_uv, current_uv, a_view, c_view = match_points[chosen_combo]

    anchor_depth = reloc.descriptor_depth(a_view)
    current_depth = reloc.descriptor_depth(c_view)
    anchor_k = reloc.descriptor_intrinsics(a_view, anchor_depth.shape[1], anchor_depth.shape[0])
    current_k = reloc.descriptor_intrinsics(c_view, current_depth.shape[1], current_depth.shape[0])
    anchor_pts_all, anchor_valid = reloc.backproject_points(anchor_uv, anchor_depth, anchor_k)
    current_pts_all, current_valid = reloc.backproject_points(current_uv, current_depth, current_k)
    valid = sorted(set(anchor_valid).intersection(current_valid))
    a_idx = {m: i for i, m in enumerate(anchor_valid)}
    c_idx = {m: i for i, m in enumerate(current_valid)}
    anchor_pts = np.asarray([anchor_pts_all[a_idx[i]] for i in valid], dtype=np.float32)
    current_pts = np.asarray([current_pts_all[c_idx[i]] for i in valid], dtype=np.float32)

    rotation, translation, inliers = reloc.ransac_rigid_transform(anchor_pts, current_pts, threshold_m=0.35)
    inlier_count = int(inliers.sum())

    computed_dtheta = math.degrees(reloc.camera_rotation_to_body_yaw(rotation, c_view, a_view))
    err = abs(angdiff(computed_dtheta, gt_dtheta_deg))

    residual = np.linalg.norm(
        (rotation @ anchor_pts[inliers].T).T + translation - current_pts[inliers], axis=1
    )
    median_residual = float(np.median(residual))

    # planarity of the INLIER anchor points (their own 3D spread, anchor-camera frame)
    pts = anchor_pts[inliers]
    pts_c = pts - pts.mean(axis=0)
    s = np.linalg.svd(pts_c, compute_uv=False)
    planarity_ratio = float(s[-1] / (s[0] + 1e-9))  # ~0 = flat, ~1 = well-spread 3D

    # Kabsch covariance matrix's own singular values (computed on inlier
    # correspondences with the FINAL rotation's centering) -- ratio of
    # smallest to largest singular value: near 0 means the rotation that
    # best aligns these two point sets is poorly constrained (multiple
    # rotations would fit nearly as well).
    src = pts
    tgt = current_pts[inliers]
    src_c = src - src.mean(axis=0)
    tgt_c = tgt - tgt.mean(axis=0)
    cov = src_c.T @ tgt_c
    sv = np.linalg.svd(cov, compute_uv=False)
    kabsch_condition_ratio = float(sv[-1] / (sv[0] + 1e-9))

    depth_vals = pts[:, 2]  # z = depth in camera-local frame
    depth_range = float(depth_vals.max() - depth_vals.min())
    depth_median = float(np.median(depth_vals))

    return {
        "episode": ep, "anchor": anchor_idx, "step": step,
        "chosen_combo": chosen_combo, "stage1_margin": margin,
        "loftr_matches": int(len(anchor_uv)), "inlier_count": inlier_count,
        "median_residual_m": median_residual,
        "gt_dtheta_deg": gt_dtheta_deg, "computed_dtheta_deg": computed_dtheta, "err_deg": err,
        "planarity_ratio": planarity_ratio,
        "kabsch_condition_ratio": kabsch_condition_ratio,
        "depth_range_m": depth_range, "depth_median_m": depth_median,
    }


def main():
    data = json.load(open(DATASET_PATH))
    cw = [r for r in data if r.get("confidently_wrong") and r["gt_distance"] < 0.01]
    print(f"near-zero confidently_wrong samples: {len(cw)}")
    results = []
    for s in cw:
        try:
            r = diagnose_one(s["episode"], s["anchor"], s["step"], s["gt_dtheta_deg"])
        except Exception as exc:
            print(f"ERROR ep{s['episode']} anchor{s['anchor']} step{s['step']}: {exc}")
            continue
        results.append(r)

    print(f"\n{'ep':>5} {'anc':>4} {'err':>7} {'planar':>7} {'kabsch_cond':>12} {'depth_rng':>10} {'depth_med':>10} {'inl':>5} {'resid':>7}")
    for r in sorted(results, key=lambda x: -x["err_deg"]):
        print(f"{r['episode']:>5} {r['anchor']:>4} {r['err_deg']:>7.1f} {r['planarity_ratio']:>7.4f} "
              f"{r['kabsch_condition_ratio']:>12.5f} {r['depth_range_m']:>10.3f} {r['depth_median_m']:>10.3f} "
              f"{r['inlier_count']:>5} {r['median_residual_m']:>7.4f}")

    with open("/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/near_zero_diagnose_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # correlation check: does planarity_ratio or kabsch_condition_ratio predict error?
    print("\n--- correlation with error ---")
    wrong = [r for r in results if r["err_deg"] >= 5]
    right = [r for r in results if r["err_deg"] < 5]
    for key in ["planarity_ratio", "kabsch_condition_ratio", "depth_range_m", "depth_median_m", "inlier_count", "median_residual_m"]:
        w = sorted(r[key] for r in wrong)
        rg = sorted(r[key] for r in right)
        wm = w[len(w)//2] if w else float('nan')
        rm = rg[len(rg)//2] if rg else float('nan')
        print(f"{key}: WRONG median={wm:.4f} (n={len(w)})  RIGHT median={rm:.4f} (n={len(rg)})")


if __name__ == "__main__":
    main()
