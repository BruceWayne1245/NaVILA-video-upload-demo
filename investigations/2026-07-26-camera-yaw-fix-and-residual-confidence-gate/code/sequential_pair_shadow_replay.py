#!/usr/bin/env python3
"""Stage-1-style shadow validation of the new vision_disagrees_with_confident_icp
diagnostic, calling the REAL production entry point
(sequential_pair_anchor_relocalization, not a scratch reimplementation) on
real captured (anchor, current) pairs. For each sample: does the flag fire,
and when it does, was ICP's own theta actually wrong vs. ground truth?
"""
import json
import math
import os
import random
import sys
import time
from types import SimpleNamespace

import numpy as np

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
sys.path.insert(0, os.path.join(BENCH, "scripts"))
import relocalization as reloc  # noqa: E402

RUN_TAG = "reliability_v11_decision_shadow_rgbd_100ep_20260724"
DATASET_PATH = "/tmp/navila-private-main-20260726/investigations/2026-07-25-representative-stage1-wrong-picks-under-1m/data/representative_dataset.json"
OUT_PATH = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/sequential_pair_shadow_replay_results.json"
PROGRESS_LOG = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/sequential_pair_shadow_replay.progress.log"


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


_ANCHOR_CACHE = {}
_ANCHOR_META_CACHE = {}


def get_anchor_rgbd_and_points(ep, anchor_idx):
    key = (ep, anchor_idx)
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key], _ANCHOR_META_CACHE[key]
    d = result_dir(ep)
    with open(os.path.join(d, "anchors.json")) as f:
        anchors = json.load(f)["anchors"]
    for a in anchors:
        if int(a["index"]) == anchor_idx:
            rgbd = load_npz(os.path.join(d, a["rgbd_file"]))
            pts = np.asarray(a["local_map_points_xyz_body"], dtype=np.float32)
            _ANCHOR_CACHE[key] = rgbd
            _ANCHOR_META_CACHE[key] = pts
            return rgbd, pts
    raise KeyError


def get_current_rgbd_and_points(ep, step):
    d = result_dir(ep)
    rgbd = load_npz(os.path.join(d, "rgbd", f"rgbd_step{step:06d}.npz"))
    with open(os.path.join(d, "steps", f"frame_step{step:06d}.json")) as f:
        frame = json.load(f)
    pts = np.asarray(frame["local_map_points_xyz_body"], dtype=np.float32)
    return rgbd, pts


def angdiff(a, b):
    return math.degrees(math.atan2(math.sin(math.radians(a - b)), math.cos(math.radians(a - b))))


def main():
    n_total = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    data = json.load(open(DATASET_PATH))
    random.seed(23)
    # oversample confidently_wrong (rare, 2.8%) so the flag has real targets
    # to catch, alongside a normal random sample -- matches the earlier
    # "adversarial + control" methodology used all day.
    cw = [r for r in data if r.get("confidently_wrong")]
    others = [r for r in data if not r.get("confidently_wrong")]
    n_cw = min(len(cw), n_total // 2)
    sample = random.sample(cw, n_cw) + random.sample(others, n_total - n_cw)
    random.shuffle(sample)
    log(f"sample: {len(sample)} ({n_cw} confidently_wrong + {len(sample)-n_cw} other)")

    results = []
    t0 = time.time()
    for i, s in enumerate(sample):
        ep, anchor_idx, step = s["episode"], s["anchor"], s["step"]
        try:
            anchor_rgbd, anchor_pts = get_anchor_rgbd_and_points(ep, anchor_idx)
            current_rgbd, current_pts = get_current_rgbd_and_points(ep, step)
        except Exception:
            continue

        anchor_descriptor = dict(anchor_rgbd)
        anchor_descriptor["local_map_points_body"] = anchor_pts
        current_descriptor = dict(current_rgbd)
        current_descriptor["local_map_points_body"] = current_pts

        anchor_obj = SimpleNamespace(
            index=anchor_idx, distance_from_start_m=0.0, route_remaining_to_start_m=0.0,
            descriptor=anchor_descriptor,
        )
        diagnostics: dict = {}
        try:
            candidates = reloc.sequential_pair_anchor_relocalization(
                current_descriptor, anchor_obj, None,
                diagnostics=diagnostics, loftr_rear_yaw_check=True, return_candidates=True,
            )
        except Exception as exc:
            log(f"ERROR ep{ep} anchor{anchor_idx} step{step}: {exc}")
            continue
        if not candidates:
            continue
        cand = candidates[0]
        icp_theta_deg = math.degrees(cand.anchor_dtheta_rad)
        icp_err = abs(angdiff(icp_theta_deg, s["gt_dtheta_deg"]))

        records = diagnostics.get("covisibility_records", [])
        rec = records[0] if records else {}
        vision_check = rec.get("loftr_rear_yaw_check", {}) or {}
        flag = bool(vision_check.get("vision_disagrees_with_confident_icp"))
        icp_precond = bool(vision_check.get("icp_confidently_wrong_precondition"))

        results.append({
            "episode": ep, "anchor": anchor_idx, "step": step,
            "gt_distance": s["gt_distance"], "gt_dtheta_deg": s["gt_dtheta_deg"],
            "confidently_wrong_label": s["confidently_wrong"],
            "icp_confidence": rec.get("confidence"),
            "icp_theta_deg": icp_theta_deg, "icp_err_deg": icp_err,
            "icp_confidently_wrong_precondition": icp_precond,
            "vision_gate_passed": vision_check.get("vision_gate_passed"),
            "vision_disagrees_with_confident_icp": flag,
            "vision_dtheta_deg": vision_check.get("loftr_rear_dtheta_deg"),
        })
        if (i + 1) % 50 == 0:
            log(f"{i+1}/{len(sample)}, {time.time()-t0:.1f}s")
            with open(OUT_PATH, "w") as f:
                json.dump(results, f)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f)
    log(f"DONE. n={len(results)}")

    n = len(results)
    icp_high_conf = [r for r in results if r["icp_confidently_wrong_precondition"]]
    icp_high_conf_wrong = [r for r in icp_high_conf if r["icp_err_deg"] >= 30]
    log(f"\nICP self-reports confidence>=0.9: {len(icp_high_conf)}/{n} = {len(icp_high_conf)/n:.1%}")
    if icp_high_conf:
        log(f"  of these, ICP actually wrong (>=30deg): {len(icp_high_conf_wrong)}/{len(icp_high_conf)} = {len(icp_high_conf_wrong)/len(icp_high_conf):.1%}")

    flagged = [r for r in results if r["vision_disagrees_with_confident_icp"]]
    log(f"\nvision_disagrees_with_confident_icp fired: {len(flagged)}/{n} = {len(flagged)/n:.2%}")
    if flagged:
        flagged_and_icp_actually_wrong = [r for r in flagged if r["icp_err_deg"] >= 30]
        log(f"  PRECISION -- of flagged, ICP actually wrong (>=30deg): "
            f"{len(flagged_and_icp_actually_wrong)}/{len(flagged)} = {len(flagged_and_icp_actually_wrong)/len(flagged):.1%}")
        flagged_and_vision_right = [r for r in flagged if abs(angdiff(r["vision_dtheta_deg"], r["gt_dtheta_deg"])) < 15]
        log(f"  of flagged, vision itself was right (<15deg): "
            f"{len(flagged_and_vision_right)}/{len(flagged)} = {len(flagged_and_vision_right)/len(flagged):.1%}")

    if icp_high_conf_wrong:
        recalled = [r for r in icp_high_conf_wrong if r["vision_disagrees_with_confident_icp"]]
        log(f"\nRECALL -- of ICP-confident-but-actually-wrong cases, flag caught: "
            f"{len(recalled)}/{len(icp_high_conf_wrong)} = {len(recalled)/len(icp_high_conf_wrong):.1%}")


if __name__ == "__main__":
    main()
