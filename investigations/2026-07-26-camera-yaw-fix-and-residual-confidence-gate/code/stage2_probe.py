#!/usr/bin/env python3
"""Stage-2 probe: given 10 (episode, anchor, step) samples where Stage-1
(camera-pairing combo selection) is already known-correct at high confidence,
run the actual LoFTR-match -> 3D-backproject -> RANSAC/Kabsch -> body-yaw
pipeline for the correct combo and compare the computed relative yaw against
ground truth (gt_dtheta_deg from representative_dataset.json).

Reuses production functions unmodified from relocalization.py:
build_rear_view_descriptor, descriptor_rgb_gray, descriptor_depth,
descriptor_intrinsics, backproject_points, ransac_rigid_transform,
camera_rotation_to_body_yaw, loftr_match_points.
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
SAMPLES_PATH = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/stage2_selected_samples.json"


def result_dir(ep):
    return (
        f"{BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_"
        f"2024-09-25_23-22-02_{RUN_TAG}_ep{ep}/icp_replay_dataset"
    )


def load_npz(path):
    with np.load(path) as data:
        return {k: data[k] for k in data.files}


def angdiff(a_deg, b_deg):
    return math.degrees(math.atan2(
        math.sin(math.radians(a_deg - b_deg)), math.cos(math.radians(a_deg - b_deg))
    ))


def get_anchor_rgbd(ep, anchor_idx):
    d = result_dir(ep)
    with open(os.path.join(d, "anchors.json")) as f:
        anchors = json.load(f)["anchors"]
    for a in anchors:
        if int(a["index"]) == anchor_idx:
            return load_npz(os.path.join(d, a["rgbd_file"]))
    raise KeyError(f"anchor {anchor_idx} not found in ep{ep}")


def get_current_rgbd(ep, step):
    d = result_dir(ep)
    path = os.path.join(d, "rgbd", f"rgbd_step{step:06d}.npz")
    return load_npz(path)


def combo_views(anchor_front, current_front, combo_name):
    anchor_rear = reloc.build_rear_view_descriptor(anchor_front)
    current_rear = reloc.build_rear_view_descriptor(current_front)
    mapping = {
        "anchorFront_currentFront": (anchor_front, current_front),
        "anchorFront_currentRear": (anchor_front, current_rear),
        "anchorRear_currentFront": (anchor_rear, current_front),
        "anchorRear_currentRear": (anchor_rear, current_rear),
    }
    return mapping[combo_name]


def stage2_compute(anchor_view, current_view):
    anchor_gray = reloc.descriptor_rgb_gray(anchor_view)
    current_gray = reloc.descriptor_rgb_gray(current_view)
    anchor_depth = reloc.descriptor_depth(anchor_view)
    current_depth = reloc.descriptor_depth(current_view)
    if anchor_gray is None or current_gray is None or anchor_depth is None or current_depth is None:
        return {"available": False, "reason": "missing_gray_or_depth"}

    anchor_uv, current_uv, match_meta = reloc.loftr_match_points(anchor_gray, current_gray)
    if anchor_uv is None or len(anchor_uv) < 8:
        return {"available": False, "reason": "too_few_loftr_matches", **match_meta}

    anchor_k = reloc.descriptor_intrinsics(anchor_view, anchor_gray.shape[1], anchor_gray.shape[0])
    current_k = reloc.descriptor_intrinsics(current_view, current_gray.shape[1], current_gray.shape[0])
    anchor_pts_all, anchor_valid = reloc.backproject_points(anchor_uv, anchor_depth, anchor_k)
    current_pts_all, current_valid = reloc.backproject_points(current_uv, current_depth, current_k)
    valid = sorted(set(anchor_valid).intersection(current_valid))
    if len(valid) < 8:
        return {"available": False, "reason": "too_few_depth_valid", "loftr_matches": int(len(anchor_uv))}

    a_idx = {m: i for i, m in enumerate(anchor_valid)}
    c_idx = {m: i for i, m in enumerate(current_valid)}
    anchor_pts = np.asarray([anchor_pts_all[a_idx[i]] for i in valid], dtype=np.float32)
    current_pts = np.asarray([current_pts_all[c_idx[i]] for i in valid], dtype=np.float32)

    rotation, translation, inliers = reloc.ransac_rigid_transform(anchor_pts, current_pts, threshold_m=0.35)
    if rotation is None:
        return {"available": False, "reason": "ransac_failed", "loftr_matches": int(len(anchor_uv)),
                "depth_valid_matches": int(len(valid))}
    inlier_count = int(inliers.sum())

    computed_dtheta = math.degrees(
        reloc.camera_rotation_to_body_yaw(rotation, current_view, anchor_view)
    )
    # diagnostic: yaw implied directly by the raw Kabsch rotation matrix about
    # the camera's own local Y (down) axis, i.e. the *measured* relative
    # camera-to-camera rotation before any body-frame composition
    raw_cam_yaw_deg = math.degrees(math.atan2(float(rotation[0, 2]), float(rotation[2, 2])))
    residual = np.linalg.norm(
        (rotation @ anchor_pts[inliers].T).T + translation - current_pts[inliers], axis=1
    )
    # planarity check on the inlier anchor points (in anchor camera frame):
    # smallest singular value relative to largest ~0 means near-planar/degenerate config
    pts = anchor_pts[inliers]
    pts_c = pts - pts.mean(axis=0)
    if len(pts_c) >= 3:
        s = np.linalg.svd(pts_c, compute_uv=False)
        planarity = float(s[-1] / (s[0] + 1e-9))  # ~0 = flat/degenerate, ~1 = well-spread 3D
    else:
        planarity = None

    return {
        "available": True,
        "loftr_matches": int(len(anchor_uv)),
        "depth_valid_matches": int(len(valid)),
        "inlier_count": inlier_count,
        "median_residual_m": float(np.median(residual)),
        "computed_dtheta_deg": computed_dtheta,
        "raw_cam_yaw_deg": raw_cam_yaw_deg,
        "planarity_ratio": planarity,
    }


def main():
    with open(SAMPLES_PATH) as f:
        samples = json.load(f)

    print(f"{'ep':>5} {'anc':>4} {'step':>6} {'dist':>6} {'combo':>22} {'gt_dth':>8} "
          f"{'comp_dth':>9} {'raw_cam':>9} {'err':>7} {'matches':>7} {'inl':>4} {'resid':>7} {'planar':>7}")
    results = []
    for s in samples:
        ep, anchor_idx, step = s["episode"], s["anchor"], s["step"]
        combo = s["gt_best_combo"]
        try:
            anchor_front = get_anchor_rgbd(ep, anchor_idx)
            current_front = get_current_rgbd(ep, step)
        except Exception as exc:
            print(f"ep{ep} anchor{anchor_idx} step{step}: LOAD FAILED {exc}")
            continue
        a_view, c_view = combo_views(anchor_front, current_front, combo)
        r = stage2_compute(a_view, c_view)
        r.update({"episode": ep, "anchor": anchor_idx, "step": step,
                   "gt_distance": s["gt_distance"], "gt_dtheta_deg": s["gt_dtheta_deg"], "combo": combo})
        results.append(r)
        if r["available"]:
            err = abs(angdiff(r["computed_dtheta_deg"], s["gt_dtheta_deg"]))
            print(f"{ep:>5} {anchor_idx:>4} {step:>6} {s['gt_distance']:>6.2f} {combo:>22} "
                  f"{s['gt_dtheta_deg']:>8.1f} {r['computed_dtheta_deg']:>9.1f} {r['raw_cam_yaw_deg']:>9.1f} {err:>7.1f} "
                  f"{r['loftr_matches']:>7} {r['inlier_count']:>4} {r['median_residual_m']:>7.3f} "
                  f"{r['planarity_ratio']:>7.3f}")
        else:
            print(f"{ep:>5} {anchor_idx:>4} {step:>6} {s['gt_distance']:>6.2f} {combo:>22} "
                  f"UNAVAILABLE: {r.get('reason')}")

    out_path = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/stage2_probe_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=lambda x: None)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
