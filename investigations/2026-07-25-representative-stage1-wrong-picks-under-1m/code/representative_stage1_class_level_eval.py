#!/usr/bin/env python3
"""Corrected Stage-1 (camera-pairing) evaluation on the representative
dataset (representative_dataset.json, 9244 samples / 676 anchors / 58
episodes), after discovering the 4-way ground truth is mathematically
degenerate (see README.md CORRECTION section).

`angdiff(a, b)` is invariant to shifting BOTH arguments by 180 deg together
(sin/cos of x+180 and x-180 are identical), so:
    anchorFront_currentFront === anchorRear_currentRear   (the "aligned" class)
    anchorFront_currentRear  === anchorRear_currentFront  (the "opposite" class)
always, exactly (verified: max deviation 1.1e-13 deg over all 9244 samples,
pure float noise). There is no valid single-of-4 ground truth; the only
answerable question is which CLASS (aligned vs opposite heading) is
correct.

This script reports, all at class level:
1. selector A: argmax single combo by raw LoFTR match count, then take its class.
2. selector B: sum match counts within each class (aligned = FF+RR,
   opposite = FR+RF), pick the higher-sum class. Uses more of the
   available per-sample data than committing to one (possibly noisy)
   single combo.
3. selector B + confidence gating: same as B, but abstain when the
   relative margin |aligned-opposite|/(aligned+opposite) is below a
   threshold. Reports the accuracy/coverage tradeoff, both pooled and by
   distance bin, and one fixed universal threshold (0.4) broken down by
   distance bin.
"""

import json

with open("representative_dataset.json") as f:
    DATA = json.load(f)

CLASS = {
    "anchorFront_currentFront": "aligned", "anchorRear_currentRear": "aligned",
    "anchorFront_currentRear": "opposite", "anchorRear_currentFront": "opposite",
}
KEYS = list(CLASS.keys())
BINS = [(0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, float("inf"))]


def true_class(r):
    return CLASS[r["gt_best_combo"]]


def pick_argmax_single(r):
    cm = {k: v for k, v in r["combo_matches"].items() if v is not None}
    if not cm:
        return None
    return CLASS[max(cm, key=lambda k: cm[k])]


def pick_class_sum_and_margin(r):
    cm = r["combo_matches"]
    if any(cm.get(k) is None for k in KEYS):
        return None, None
    aligned = cm["anchorFront_currentFront"] + cm["anchorRear_currentRear"]
    opposite = cm["anchorFront_currentRear"] + cm["anchorRear_currentFront"]
    total = aligned + opposite
    if total == 0:
        return None, None
    margin = abs(aligned - opposite) / total
    return ("aligned" if aligned >= opposite else "opposite"), margin


def bin_label(lo, hi):
    return f"{lo}-{hi if hi < 999 else 'inf'}m"


def eval_by_bin(pick_fn, label):
    print(f"\n=== {label} ===")
    out = {}
    all_n, all_c = 0, 0
    for lo, hi in BINS:
        subset = [r for r in DATA if lo <= r["gt_distance"] < hi]
        n, c = 0, 0
        for r in subset:
            p = pick_fn(r)
            if isinstance(p, tuple):
                p = p[0]
            if p is None:
                continue
            n += 1
            if p == true_class(r):
                c += 1
        acc = c / n * 100 if n else float("nan")
        out[bin_label(lo, hi)] = {"n": n, "correct": c, "accuracy_pct": acc}
        all_n += n
        all_c += c
        print(f"  {bin_label(lo, hi):>8}: n={n:5d} accuracy={acc:5.1f}%")
    acc = all_c / all_n * 100
    out["full"] = {"n": all_n, "correct": all_c, "accuracy_pct": acc}
    print(f"  {'full':>8}: n={all_n:5d} accuracy={acc:5.1f}%  (chance=50%)")
    return out


results = {}
results["selector_A_argmax_single"] = eval_by_bin(pick_argmax_single, "selector A: argmax single combo -> class")
results["selector_B_class_sum"] = eval_by_bin(lambda r: pick_class_sum_and_margin(r)[0], "selector B: class-sum")

print("\n=== selector B + confidence gating: pooled threshold sweep ===")
scored = []
for r in DATA:
    pick, margin = pick_class_sum_and_margin(r)
    if pick is None:
        continue
    scored.append((margin, pick == true_class(r), r["gt_distance"]))

sweep = {}
for thresh in [0.0, 0.2, 0.3, 0.4, 0.5, 0.6]:
    kept = [s for s in scored if s[0] >= thresh]
    acc = sum(c for _, c, _ in kept) / len(kept) * 100 if kept else float("nan")
    coverage = len(kept) / len(scored) * 100
    sweep[thresh] = {"coverage_pct": coverage, "n": len(kept), "accuracy_pct": acc}
    print(f"  margin>={thresh}: coverage={coverage:5.1f}% (n={len(kept):5d})  accuracy={acc:.1f}%")
results["selector_B_gated_pooled_sweep"] = sweep

print("\n=== selector B + fixed threshold margin>=0.4, by distance bin ===")
fixed = {}
for lo, hi in BINS:
    kept = [s for s in scored if lo <= s[2] < hi and s[0] >= 0.4]
    all_b = [s for s in scored if lo <= s[2] < hi]
    acc = sum(c for _, c, _ in kept) / len(kept) * 100 if kept else float("nan")
    cov = len(kept) / len(all_b) * 100 if all_b else float("nan")
    fixed[bin_label(lo, hi)] = {"coverage_pct": cov, "n": len(kept), "n_total": len(all_b), "accuracy_pct": acc}
    print(f"  {bin_label(lo, hi):>8}: coverage={cov:5.1f}% (n={len(kept)}/{len(all_b)})  accuracy={acc:.1f}%")
results["selector_B_gated_margin0.4_by_distance"] = fixed

with open("representative_stage1_class_level_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nwrote representative_stage1_class_level_results.json")
