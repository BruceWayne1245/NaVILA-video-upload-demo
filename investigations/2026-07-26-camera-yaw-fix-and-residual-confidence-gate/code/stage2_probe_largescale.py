#!/usr/bin/env python3
"""Larger-scale Stage-2 validation of the camera_rotation_to_body_yaw fix
found via the 10-sample probe (stage2_probe.py): the function's final
atan2(v[1], v[0]) reads the wrong axis pair for this project's actual
camera_rotation_body convention (v[1] is analytically ~0 for pure yaw,
collapsing every result to ~0 deg / ~180 deg), and is additionally missing a
sign flip when the "current" side uses the rear view. This script applies
BOTH the buggy (production, unmodified relocalization.py) and the fixed
formula to a large stratified sample and reports the full error distribution
for each, without touching relocalization.py itself yet.
"""
import json
import math
import os
import random
import sys
import time

import numpy as np

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
sys.path.insert(0, os.path.join(BENCH, "scripts"))

import relocalization as reloc  # noqa: E402

RUN_TAG = "reliability_v11_decision_shadow_rgbd_100ep_20260724"
DATASET_PATH = "/tmp/navila-private-main-20260726/investigations/2026-07-25-representative-stage1-wrong-picks-under-1m/data/representative_dataset.json"
OUT_PATH = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/stage2_largescale_results.json"
PROGRESS_LOG = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/stage2_largescale.progress.log"


def log(msg):
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(line + "\n")


def result_dir(ep):
    return (
        f"{BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_"
        f"2024-09-25_23-22-02_{RUN_TAG}_ep{ep}/icp_replay_dataset"
    )


def load_npz(path):
    with np.load(path) as data:
        return {k: data[k] for k in data.files}


def angdiff(a, b):
    return math.degrees(math.atan2(math.sin(math.radians(a - b)), math.cos(math.radians(a - b))))


_ANCHOR_CACHE = {}


def get_anchor_rgbd(ep, anchor_idx):
    key = (ep, anchor_idx)
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key]
    d = result_dir(ep)
    with open(os.path.join(d, "anchors.json")) as f:
        anchors = json.load(f)["anchors"]
    for a in anchors:
        if int(a["index"]) == anchor_idx:
            val = load_npz(os.path.join(d, a["rgbd_file"]))
            _ANCHOR_CACHE[key] = val
            return val
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
        return {"available": False, "reason": "too_few_loftr_matches"}

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
    if inlier_count < 6:
        return {"available": False, "reason": "too_few_3d_inliers", "loftr_matches": int(len(anchor_uv)),
                "inlier_count": inlier_count}

    # PRODUCTION (buggy) formula, exactly as camera_rotation_to_body_yaw computes it today
    buggy_dtheta = math.degrees(
        reloc.camera_rotation_to_body_yaw(rotation, current_view, anchor_view)
    )

    # FIXED formula: same body composition, correct axis pair (index 2, index 0)
    # instead of (index 1, index 0), plus sign flip when current side is rear.
    current_R_bc, _ = reloc.descriptor_camera_to_body(current_view)
    anchor_R_bc, _ = reloc.descriptor_camera_to_body(anchor_view)
    R_final = current_R_bc @ rotation @ anchor_R_bc.T
    col0 = R_final[:, 0]
    fixed_dtheta = math.degrees(math.atan2(float(col0[2]), float(col0[0])))
    if current_view.get("view") == "rear":
        fixed_dtheta = -fixed_dtheta

    residual = np.linalg.norm(
        (rotation @ anchor_pts[inliers].T).T + translation - current_pts[inliers], axis=1
    )

    return {
        "available": True,
        "loftr_matches": int(len(anchor_uv)),
        "inlier_count": inlier_count,
        "median_residual_m": float(np.median(residual)),
        "buggy_dtheta_deg": buggy_dtheta,
        "fixed_dtheta_deg": fixed_dtheta,
    }


def select_samples(n_total=250, seed=42):
    data = json.load(open(DATASET_PATH))

    def class_sum(combo_matches):
        if not combo_matches or any(v is None for v in combo_matches.values()):
            return None
        aligned = combo_matches["anchorFront_currentFront"] + combo_matches["anchorRear_currentRear"]
        opposite = combo_matches["anchorFront_currentRear"] + combo_matches["anchorRear_currentFront"]
        return aligned, opposite

    def cls(combo):
        return "aligned" if combo in ("anchorFront_currentFront", "anchorRear_currentRear") else "opposite"

    candidates = []
    for r in data:
        cs = class_sum(r["combo_matches"])
        if cs is None:
            continue
        aligned, opposite = cs
        total = aligned + opposite
        if total == 0:
            continue
        margin = abs(aligned - opposite) / total
        picked_class = "aligned" if aligned >= opposite else "opposite"
        if picked_class == cls(r["gt_best_combo"]) and margin >= 0.4:
            candidates.append(r)

    buckets = {"0-1": [], "1-2": [], "2-3": [], "3+": []}
    for r in candidates:
        d = r["gt_distance"]
        if d < 1:
            buckets["0-1"].append(r)
        elif d < 2:
            buckets["1-2"].append(r)
        elif d < 3:
            buckets["2-3"].append(r)
        else:
            buckets["3+"].append(r)

    random.seed(seed)
    counts = {"0-1": int(n_total * 0.35), "1-2": int(n_total * 0.30),
              "2-3": int(n_total * 0.20), "3+": int(n_total * 0.15)}
    selected = []
    for k, n in counts.items():
        pool = buckets[k][:]
        random.shuffle(pool)
        take = min(n, len(pool))
        selected.extend(pool[:take])
        log(f"bucket {k}: pool={len(pool)}, selected={take}")
    random.shuffle(selected)
    return selected


def main():
    n_total = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    samples = select_samples(n_total=n_total)
    log(f"Total selected samples: {len(samples)}")

    results = []
    t0 = time.time()
    for i, s in enumerate(samples):
        ep, anchor_idx, step, combo = s["episode"], s["anchor"], s["step"], s["gt_best_combo"]
        try:
            anchor_front = get_anchor_rgbd(ep, anchor_idx)
            current_front = get_current_rgbd(ep, step)
        except Exception as exc:
            continue
        a_view, c_view = combo_views(anchor_front, current_front, combo)
        try:
            r = stage2_compute(a_view, c_view)
        except Exception as exc:
            log(f"ERROR ep{ep} anchor{anchor_idx} step{step}: {exc}")
            continue
        r.update({"episode": ep, "anchor": anchor_idx, "step": step,
                   "gt_distance": s["gt_distance"], "gt_dtheta_deg": s["gt_dtheta_deg"], "combo": combo})
        results.append(r)
        if (i + 1) % 25 == 0:
            elapsed = time.time() - t0
            log(f"{i+1}/{len(samples)} done, {elapsed:.1f}s elapsed, {elapsed/(i+1):.2f}s/sample")
            with open(OUT_PATH, "w") as f:
                json.dump(results, f)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f)
    log(f"DONE. {len(results)} results written to {OUT_PATH}")

    # summary
    avail = [r for r in results if r["available"]]
    log(f"available: {len(avail)}/{len(results)}")
    buggy_errs = [abs(angdiff(r["buggy_dtheta_deg"], r["gt_dtheta_deg"])) for r in avail]
    fixed_errs = [abs(angdiff(r["fixed_dtheta_deg"], r["gt_dtheta_deg"])) for r in avail]

    def stats(errs):
        s = sorted(errs)
        n = len(s)
        return {
            "median": s[n // 2],
            "mean": sum(s) / n,
            "p90": s[int(n * 0.9)],
            "frac_under_5deg": sum(1 for e in s if e < 5) / n,
            "frac_under_15deg": sum(1 for e in s if e < 15) / n,
            "frac_under_30deg": sum(1 for e in s if e < 30) / n,
        }

    log(f"BUGGY (production):  {stats(buggy_errs)}")
    log(f"FIXED:                {stats(fixed_errs)}")

    # by distance bin, fixed only
    for lo, hi, name in [(0, 1, "0-1m"), (1, 2, "1-2m"), (2, 3, "2-3m"), (3, 999, "3m+")]:
        subset = [r for r in avail if lo <= r["gt_distance"] < hi]
        if not subset:
            continue
        errs = [abs(angdiff(r["fixed_dtheta_deg"], r["gt_dtheta_deg"])) for r in subset]
        log(f"FIXED by distance {name}: n={len(subset)}, {stats(errs)}")


if __name__ == "__main__":
    main()
