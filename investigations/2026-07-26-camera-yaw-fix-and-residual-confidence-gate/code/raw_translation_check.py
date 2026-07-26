#!/usr/bin/env python3
"""Verify: does the RAW (pre-body-conversion, camera-local) RANSAC translation
magnitude cleanly separate the 45 near-zero-distance failures from the 78
correctly-solved confidently_wrong cases at non-zero distance? If so, this is
a cheap, directly implementable extra gate.
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


def raw_translation_norm(ep, anchor_idx, step, gt_dtheta_deg):
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
    match_points, match_counts = {}, {}
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
    computed_dtheta = math.degrees(reloc.camera_rotation_to_body_yaw(rotation, c_view, a_view))
    err = abs(angdiff(computed_dtheta, gt_dtheta_deg))
    return float(np.linalg.norm(translation)), err


def main():
    data = json.load(open(DATASET_PATH))
    near_zero_wrong = [r for r in data if r.get("confidently_wrong") and r["gt_distance"] < 0.01]

    # control: confidently_wrong AND gt_distance >= 0.01 -- sample same size for a fair check
    import random
    random.seed(3)
    far_cw = [r for r in data if r.get("confidently_wrong") and r["gt_distance"] >= 0.01]
    control = random.sample(far_cw, min(len(near_zero_wrong) * 2, len(far_cw)))

    print(f"{'group':>10} {'ep':>5} {'anc':>4} {'raw_trans_norm':>15} {'err_deg':>8}")
    near_zero_norms = []
    for s in near_zero_wrong:
        try:
            norm, err = raw_translation_norm(s["episode"], s["anchor"], s["step"], s["gt_dtheta_deg"])
        except Exception as exc:
            continue
        near_zero_norms.append((norm, err))
        print(f"{'nearzero':>10} {s['episode']:>5} {s['anchor']:>4} {norm:>15.4f} {err:>8.1f}")

    control_norms = []
    for s in control:
        try:
            norm, err = raw_translation_norm(s["episode"], s["anchor"], s["step"], s["gt_dtheta_deg"])
        except Exception as exc:
            continue
        control_norms.append((norm, err, s["gt_distance"]))

    print()
    nz = sorted(n for n, e in near_zero_norms)
    print(f"NEAR-ZERO-DISTANCE failures: n={len(nz)} raw_translation_norm median={nz[len(nz)//2]:.4f} "
          f"max={nz[-1]:.4f} p90={nz[int(len(nz)*0.9)]:.4f}")

    ctrl_good = [(n, e, d) for n, e, d in control_norms if e < 5]
    ctrl_bad = [(n, e, d) for n, e, d in control_norms if e >= 5]
    if ctrl_good:
        vals = sorted(n for n, e, d in ctrl_good)
        print(f"CONTROL (dist>=0.01m) accurate cases: n={len(vals)} raw_translation_norm median={vals[len(vals)//2]:.4f} min={vals[0]:.4f}")
    if ctrl_bad:
        vals = sorted(n for n, e, d in ctrl_bad)
        print(f"CONTROL (dist>=0.01m) INaccurate cases: n={len(vals)} raw_translation_norm median={vals[len(vals)//2]:.4f}")

    # threshold sweep: reject if raw_translation_norm < threshold
    print("\n--- threshold sweep on raw_translation_norm (reject below) ---")
    all_labeled = [(n, e, "nearzero") for n, e in near_zero_norms] + [(n, e, "control") for n, e, d in control_norms]
    for thresh in [0.02, 0.03, 0.05, 0.08, 0.10, 0.12]:
        kept = [(n, e, lbl) for n, e, lbl in all_labeled if n >= thresh]
        rejected_nearzero = sum(1 for n, e, lbl in all_labeled if n < thresh and lbl == "nearzero")
        rejected_control_good = sum(1 for n, e, lbl in all_labeled if n < thresh and lbl == "control" and e < 5)
        kept_accurate = sum(1 for n, e, lbl in kept if e < 5)
        print(f"thresh={thresh:.2f}: kept={len(kept)}/{len(all_labeled)}, kept_frac_accurate={kept_accurate/len(kept):.1%} "
              f"| rejected {rejected_nearzero}/{len(near_zero_norms)} nearzero-bad, "
              f"rejected {rejected_control_good} previously-good control (false rejects)")


if __name__ == "__main__":
    main()
