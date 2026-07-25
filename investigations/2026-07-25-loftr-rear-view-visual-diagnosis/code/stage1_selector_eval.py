#!/usr/bin/env python3
"""Evaluate every selector tried this session against the pure-geometry
Stage-1 ground truth (stage1_ground_truth.json), binned by distance.
"""

import json
import numpy as np

with open("stage1_ground_truth.json") as f:
    gt_records = json.load(f)
gt_lookup = {(r["episode"], r["anchor"], r["step"]): r for r in gt_records}

with open("loftr_four_pairings_results.json") as f:
    four = json.load(f)
four_lookup = {(r["episode"], r["anchor"], r["step"]): r for r in four if r["group"] == "confidently_wrong"}

selector_files = {
    "SALAD": ("salad_scene_similarity_results.json", "global_sim"),
    "AnyLoc-VLAD": ("anyloc_vlad_similarity_results.json", "vlad_sim"),
    "ResNet18": ("global_scene_similarity_results.json", "global_sim"),
    "DINOv2-CLS": ("raw_dinov2_similarity_results.json", "global_sim"),
    "DINOv2-patchmean": ("raw_dinov2_patchmean_similarity_results.json", "global_sim"),
}

BINS = [(0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 999)]


def bin_label(d):
    for lo, hi in BINS:
        if lo <= d < hi:
            return f"{lo}-{hi if hi < 999 else 'inf'}m"
    return "?"


def evaluate(name, picks_fn):
    per_bin = {bin_label((lo+hi)/2 if hi<999 else lo+0.5): [] for lo, hi in BINS}
    for key, gt in gt_lookup.items():
        pick = picks_fn(key)
        if pick is None:
            continue
        correct = pick == gt["gt_best_combo"]
        b = bin_label(gt["distance"])
        per_bin[b].append(correct)
    print(f"\n=== {name} ===")
    total_n, total_correct = 0, 0
    for lo, hi in BINS:
        b = bin_label((lo+hi)/2 if hi < 999 else lo+0.5)
        vals = per_bin[b]
        n = len(vals)
        c = sum(vals)
        total_n += n
        total_correct += c
        acc = c/n*100 if n else float("nan")
        print(f"  {b:>10}: n={n:3d}  accuracy={acc:5.1f}%")
    print(f"  {'ALL':>10}: n={total_n:3d}  accuracy={total_correct/total_n*100:5.1f}%")


# match-count selector (from four_lookup directly)
def match_count_pick(key):
    r = four_lookup.get(key)
    if r is None:
        return None
    avail = {k: v for k, v in r["combos"].items() if v.get("available")}
    if not avail:
        return None
    return max(avail, key=lambda k: avail[k].get("loftr_matches", 0))

evaluate("match-count selector", match_count_pick)

for name, (fn, key_field) in selector_files.items():
    with open(fn) as f:
        data = json.load(f)
    lookup = {(r["episode"], r["anchor"], r["step"]): r for r in data}

    def picks_fn(key, lookup=lookup, key_field=key_field):
        r = lookup.get(key)
        if r is None:
            return None
        sims = {k: v for k, v in r[key_field].items() if v is not None}
        if not sims:
            return None
        return max(sims, key=lambda k: sims[k])

    evaluate(name, picks_fn)

# distance distribution per bin, for context
print("\n=== case count per distance bin ===")
dist_by_bin = {}
for r in gt_records:
    b = bin_label(r["distance"])
    dist_by_bin.setdefault(b, 0)
    dist_by_bin[b] += 1
for lo, hi in BINS:
    b = bin_label((lo+hi)/2 if hi < 999 else lo+0.5)
    print(f"  {b}: {dist_by_bin.get(b,0)}")
