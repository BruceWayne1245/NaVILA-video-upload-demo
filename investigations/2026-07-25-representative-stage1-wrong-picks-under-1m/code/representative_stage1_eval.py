#!/usr/bin/env python3
"""Stage-1 (camera-pairing selection) accuracy on the REPRESENTATIVE dataset
(all 676 anchors / 58 episodes, built 2026-07-25), reporting both the full
baseline and the genuine-confidently-wrong subset separately -- the two
methodology fixes requested after the earlier 21-anchor biased sample.
"""

import json

with open("representative_dataset.json") as f:
    data = json.load(f)

print(f"total samples: {len(data)}")
n_cw = sum(1 for r in data if r["confidently_wrong"])
print(f"genuine confidently-wrong samples (24-seed ICP top1 confident+wrong): {n_cw} "
      f"({n_cw/len(data)*100:.1f}%)")

n_eps = len(set(r["episode"] for r in data))
n_anchors = len(set((r["episode"], r["anchor"]) for r in data))
print(f"episodes: {n_eps}, anchors: {n_anchors}")

# anchor concentration check (the bug that broke the earlier sample)
from collections import Counter
cw_anchor_counts = Counter((r["episode"], r["anchor"]) for r in data if r["confidently_wrong"])
if cw_anchor_counts:
    top_anchor, top_n = cw_anchor_counts.most_common(1)[0]
    print(f"most-concentrated confidently-wrong anchor: {top_anchor} with {top_n} samples "
          f"({top_n/n_cw*100:.1f}% of all confidently-wrong samples)")
print(f"distinct anchors contributing >=1 confidently-wrong sample: {len(cw_anchor_counts)}")


def eval_match_count(subset, label):
    n, correct = 0, 0
    for r in subset:
        pick = r["match_count_pick"]
        if pick is None:
            continue
        n += 1
        if pick == r["gt_best_combo"]:
            correct += 1
    acc = correct / n * 100 if n else float("nan")
    print(f"\n=== match-count selector -- {label} ===")
    print(f"  n={n}  correct={correct}  accuracy={acc:.1f}%  (chance=25.0%)")
    return acc


def eval_by_distance_bins(subset, label):
    bins = [(0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, float("inf"))]
    print(f"\n=== match-count selector by distance -- {label} ===")
    for lo, hi in bins:
        b = [r for r in subset if lo <= r["gt_distance"] < hi]
        n, correct = 0, 0
        for r in b:
            pick = r["match_count_pick"]
            if pick is None:
                continue
            n += 1
            if pick == r["gt_best_combo"]:
                correct += 1
        acc = correct / n * 100 if n else float("nan")
        hi_s = f"{hi}" if hi != float("inf") else "inf"
        print(f"  {lo}-{hi_s}m: n={n:4d}  accuracy={acc:5.1f}%")


eval_match_count(data, "full representative sample")
eval_match_count([r for r in data if r["confidently_wrong"]], "confidently-wrong subset")
eval_match_count([r for r in data if not r["confidently_wrong"]], "NOT confidently-wrong subset")

eval_by_distance_bins(data, "full representative sample")
eval_by_distance_bins([r for r in data if r["confidently_wrong"]], "confidently-wrong subset")

# gt_best_combo alignment quality sanity check
angles = [r["alignment_angles"][r["gt_best_combo"]] for r in data]
angles.sort()
n = len(angles)
print(f"\nGT-best-combo alignment angle: median={angles[n//2]:.1f} deg, "
      f"p75={angles[int(n*0.75)]:.1f} deg, max={angles[-1]:.1f} deg")
print(f"fraction <=20 deg: {sum(1 for a in angles if a<=20)/n*100:.1f}%")
