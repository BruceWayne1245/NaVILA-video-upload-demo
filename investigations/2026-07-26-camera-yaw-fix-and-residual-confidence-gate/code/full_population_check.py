#!/usr/bin/env python3
"""Does the 3-gate vision check (Stage1 margin + Stage2 residual + Stage2 min
translation) ever pass-but-mislead on the FULL, unfiltered population -- not
just the adversarially-selected confidently_wrong subset? A true random
sample of the whole representative_dataset.json (9244 samples, real
distribution -- mostly non-confidently-wrong, skewed toward longer
distances), checking specifically for gate-passed-but-wrong cases that could
corrupt an otherwise-fine ICP reading if used as a cross-check.
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
OUT_PATH = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/full_population_check_results.json"
PROGRESS_LOG = "/tmp/claude-1006/-home-teambruce/e784db94-614c-43a1-abbf-2a76d7bafcf5/scratchpad/full_population_check.progress.log"


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
    raise KeyError


def get_current_rgbd(ep, step):
    d = result_dir(ep)
    return load_npz(os.path.join(d, "rgbd", f"rgbd_step{step:06d}.npz"))


def angdiff(a, b):
    return math.degrees(math.atan2(math.sin(math.radians(a - b)), math.cos(math.radians(a - b))))


def main():
    n_total = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    data = json.load(open(DATASET_PATH))
    random.seed(11)
    sample = random.sample(data, min(n_total, len(data)))
    log(f"Full-population random sample: {len(sample)} (true distribution, no pre-filtering by confidently_wrong)")
    n_cw_in_sample = sum(1 for s in sample if s.get("confidently_wrong"))
    log(f"  of these, {n_cw_in_sample} ({n_cw_in_sample/len(sample):.1%}) happen to be confidently_wrong (matches ~2.8% base rate)")

    results = []
    t0 = time.time()
    for i, s in enumerate(sample):
        ep, anchor_idx, step = s["episode"], s["anchor"], s["step"]
        try:
            anchor_rgbd = get_anchor_rgbd(ep, anchor_idx)
            current_rgbd = get_current_rgbd(ep, step)
        except Exception:
            continue
        try:
            r = reloc._loftr_rear_yaw_check(anchor_rgbd, current_rgbd, icp_theta_rad=0.0)
        except Exception as exc:
            log(f"ERROR ep{ep} anchor{anchor_idx} step{step}: {exc}")
            continue
        r["episode"] = ep
        r["anchor"] = anchor_idx
        r["step"] = step
        r["gt_distance"] = s["gt_distance"]
        r["gt_dtheta_deg"] = s["gt_dtheta_deg"]
        r["confidently_wrong"] = s["confidently_wrong"]
        results.append(r)
        if (i + 1) % 100 == 0:
            log(f"{i+1}/{len(sample)}, {time.time()-t0:.1f}s")
            with open(OUT_PATH, "w") as f:
                json.dump(results, f)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f)
    log(f"DONE. n={len(results)} saved to {OUT_PATH}")

    n = len(results)
    passed = [r for r in results if r.get("vision_gate_passed")]
    log(f"\ngate_passed: {len(passed)}/{n} = {len(passed)/n:.1%} (on TRUE population distribution)")

    errs = []
    for r in passed:
        e = abs(angdiff(r["loftr_rear_dtheta_deg"], r["gt_dtheta_deg"]))
        r["err"] = e
        errs.append(e)
    errs.sort()
    m = len(errs)
    if m:
        log(f"among gate-passed: median_err={errs[m//2]:.2f} frac<5deg={sum(1 for e in errs if e<5)/m:.1%} "
            f"frac>=5deg={sum(1 for e in errs if e>=5)/m:.1%} max={errs[-1]:.1f}")

    misleading = [r for r in passed if r["err"] >= 5]
    log(f"\nMISLEADING cases (gate passed but wrong, >=5deg): {len(misleading)} / {n} total = {len(misleading)/n:.2%} of the FULL population")
    for r in misleading:
        log(f"  ep{r['episode']} anc{r['anchor']} step{r['step']} dist={r['gt_distance']:.3f} err={r['err']:.1f} "
            f"cw={r['confidently_wrong']} resid={r['median_3d_residual_m']:.4f} "
            f"raw_trans={r.get('raw_translation_norm_m'):.3f} margin={r['stage1_margin']:.2f} combo={r['chosen_combo']}")

    # by distance
    log("\n--- by distance bucket (full population) ---")
    for lo, hi, name in [(0,1,"0-1m"),(1,2,"1-2m"),(2,3,"2-3m"),(3,4,"3-4m"),(4,6,"4-6m"),(6,999,"6m+")]:
        sub = [r for r in results if lo<=r["gt_distance"]<hi]
        if not sub: continue
        subp = [r for r in sub if r.get("vision_gate_passed")]
        if subp:
            e = sorted(abs(angdiff(r["loftr_rear_dtheta_deg"], r["gt_dtheta_deg"])) for r in subp)
            f5 = sum(1 for x in e if x<5)/len(e)
            log(f"{name}: n={len(sub)}, gate_pass={len(subp)}({len(subp)/len(sub):.0%}), among_passed_frac<5deg={f5:.1%}")
        else:
            log(f"{name}: n={len(sub)}, gate_pass=0")


if __name__ == "__main__":
    main()
