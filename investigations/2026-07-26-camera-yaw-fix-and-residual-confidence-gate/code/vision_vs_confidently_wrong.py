#!/usr/bin/env python3
"""Does the generalized vision Stage1+Stage2 gate (now live in
relocalization.py's _loftr_rear_yaw_check) catch cases where ICP is
confidently wrong? Uses representative_dataset.json's already-computed
`confidently_wrong` flag (genuine 24-seed icp_seed_sweep_2d methodology) as
the target, plus a same-size random control sample of confidently_wrong=False
cases to check the gate doesn't just fire indiscriminately.
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
OUT_PATH = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/vision_vs_confidently_wrong_results.json"
PROGRESS_LOG = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/vision_vs_confidently_wrong.progress.log"


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
    return load_npz(os.path.join(d, "rgbd", f"rgbd_step{step:06d}.npz"))


def angdiff(a, b):
    return math.degrees(math.atan2(math.sin(math.radians(a - b)), math.cos(math.radians(a - b))))


def main():
    data = json.load(open(DATASET_PATH))
    confidently_wrong = [r for r in data if r.get("confidently_wrong")]
    not_wrong = [r for r in data if not r.get("confidently_wrong")]
    log(f"confidently_wrong: {len(confidently_wrong)}, not_wrong pool: {len(not_wrong)}")

    random.seed(7)
    control = random.sample(not_wrong, min(len(confidently_wrong), len(not_wrong)))

    def process(sample_list, label):
        results = []
        t0 = time.time()
        for i, s in enumerate(sample_list):
            ep, anchor_idx, step = s["episode"], s["anchor"], s["step"]
            try:
                anchor_rgbd = get_anchor_rgbd(ep, anchor_idx)
                current_rgbd = get_current_rgbd(ep, step)
            except Exception as exc:
                continue
            try:
                r = reloc._loftr_rear_yaw_check(anchor_rgbd, current_rgbd, icp_theta_rad=0.0)
            except Exception as exc:
                log(f"ERROR {label} ep{ep} anchor{anchor_idx} step{step}: {exc}")
                continue
            r["episode"] = ep
            r["anchor"] = anchor_idx
            r["step"] = step
            r["gt_distance"] = s["gt_distance"]
            r["gt_dtheta_deg"] = s["gt_dtheta_deg"]
            r["confidently_wrong"] = s["confidently_wrong"]
            results.append(r)
            if (i + 1) % 25 == 0:
                log(f"{label}: {i+1}/{len(sample_list)}, {time.time()-t0:.1f}s")
        return results

    cw_results = process(confidently_wrong, "confidently_wrong")
    ctrl_results = process(control, "control")

    with open(OUT_PATH, "w") as f:
        json.dump({"confidently_wrong": cw_results, "control": ctrl_results}, f)
    log(f"DONE. cw={len(cw_results)} control={len(ctrl_results)} saved to {OUT_PATH}")

    def summarize(results, label):
        n = len(results)
        gate_pass = [r for r in results if r.get("vision_gate_passed")]
        log(f"--- {label} (n={n}) ---")
        log(f"  vision_gate_passed: {len(gate_pass)}/{n} = {len(gate_pass)/n:.1%}")
        if gate_pass:
            errs = [abs(angdiff(r["loftr_rear_dtheta_deg"], r["gt_dtheta_deg"])) for r in gate_pass]
            errs.sort()
            m = len(errs)
            frac5 = sum(1 for e in errs if e < 5) / m
            frac15 = sum(1 for e in errs if e < 15) / m
            log(f"  among gate-passed: median_err={errs[m//2]:.2f} frac<5deg={frac5:.1%} frac<15deg={frac15:.1%}")
        reasons = {}
        for r in results:
            if not r.get("available") and not r.get("vision_gate_passed"):
                reasons[r.get("reason", "gate_failed")] = reasons.get(r.get("reason", "gate_failed"), 0) + 1
            elif r.get("available") and not r.get("vision_gate_passed"):
                reasons["stage2_gate_failed"] = reasons.get("stage2_gate_failed", 0) + 1
        log(f"  non-pass reasons: {reasons}")

    summarize(cw_results, "CONFIDENTLY_WRONG (ICP known bad)")
    summarize(ctrl_results, "CONTROL (ICP not flagged wrong)")


if __name__ == "__main__":
    main()
