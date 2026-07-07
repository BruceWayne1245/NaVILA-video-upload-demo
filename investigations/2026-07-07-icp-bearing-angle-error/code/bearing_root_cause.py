"""Re-run ICP against captured point clouds for specific (episode, anchor) pairs
flagged as high-bearing-error, capturing full diagnostics (match_class,
icp_basin_count, near_tie_basin_count, overlap_ratio, confidence) to test
whether errors come from (A) a tied/near-tied second yaw solution vs
(B) an inherently low-quality/low-confidence match.
"""
import json
import os
import sys

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
sys.path.insert(0, SCRIPTS_DIR)

import numpy as np  # noqa: E402
from relocalization import sequential_pair_anchor_relocalization  # noqa: E402
from route_memory_agent import RouteAnchor  # noqa: E402

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
BATCH = "icp_replay_capture_hard11_20260706_accumulated"


def find_capture_dir(ep):
    dirname = f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{BATCH}_ep{ep}"
    return os.path.join(BASE, dirname, "icp_replay_dataset")


def load_anchors(capture_dir):
    data = json.load(open(os.path.join(capture_dir, "anchors.json")))
    anchors = {}
    for a in data["anchors"]:
        pts = a.get("local_map_points_xyz_body")
        descriptor = {"local_map_points_body": np.asarray(pts, dtype=np.float32)} if pts else None
        anchors[int(a["index"])] = RouteAnchor(
            index=int(a["index"]), pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=float(a["distance_from_start_m"]),
            descriptor=descriptor, metadata={"world_pose": a.get("world_pose")},
        )
    return anchors


def load_steps(capture_dir):
    steps_dir = os.path.join(capture_dir, "steps")
    steps = {}
    for fname in os.listdir(steps_dir):
        try:
            d = json.load(open(os.path.join(steps_dir, fname)))
        except json.JSONDecodeError:
            continue
        steps[d["step"]] = d
    return steps


TARGETS = [
    (680, 7),   # low CV, mean 168.3
    (368, 12),  # low CV, mean 130.8
    (5, 11),    # mid CV, mean 88.5
    (994, 2),   # mid CV, mean 99.7
    (368, 5),   # high CV, mean 51.6
    (187, 14),  # high CV, mean 48.3
]

for ep, target_anchor in TARGETS:
    result_path = f"/tmp/claude-1006/-home-teambruce/0aebc99f-397c-4048-9147-1ceafe62fc01/scratchpad/replay_results/ep{ep}_alias_fixed.json"
    replay = json.load(open(result_path))
    attempts = [r for r in replay["results"] if r.get("accepted") and r["target_anchor_index"] == target_anchor]

    capture_dir = find_capture_dir(ep)
    anchors = load_anchors(capture_dir)
    steps = load_steps(capture_dir)
    anchor_obj = anchors[target_anchor]

    match_classes = {}
    basin_counts = []
    near_tie_counts = []
    overlaps = []
    confidences = []
    n_ok = 0
    for r in attempts:
        step = steps.get(r["step"])
        if step is None:
            continue
        pts = step.get("local_map_points_xyz_body")
        if not pts:
            continue
        descriptor = {"local_map_points_body": np.asarray(pts, dtype=np.float32)}
        diag = {}
        sequential_pair_anchor_relocalization(
            descriptor, anchor_obj, None, diagnostics=diag,
            icp_objective="point_to_point", voxel_size_m=0.10, max_points=512,
            quality_policy="diagnostic",
        )
        recs = diag.get("covisibility_records", [])
        if not recs:
            continue
        rec = recs[-1]
        n_ok += 1
        mc = rec.get("match_class", "?")
        match_classes[mc] = match_classes.get(mc, 0) + 1
        if "icp_basin_count" in rec:
            basin_counts.append(rec["icp_basin_count"])
            near_tie_counts.append(rec["icp_near_tie_basin_count"])
        if "overlap_ratio" in rec:
            overlaps.append(rec["overlap_ratio"])
        if "confidence" in rec:
            confidences.append(rec["confidence"])

    print(f"=== ep{ep} anchor{target_anchor}: n_reprocessed={n_ok}/{len(attempts)} ===")
    print(f"  match_class distribution: {match_classes}")
    if basin_counts:
        print(f"  icp_basin_count: mean={sum(basin_counts)/len(basin_counts):.2f} max={max(basin_counts)}")
        print(f"  near_tie_basin_count: mean={sum(near_tie_counts)/len(near_tie_counts):.2f} "
              f"frac>0={sum(1 for x in near_tie_counts if x>0)/len(near_tie_counts):.1%}")
    if overlaps:
        print(f"  overlap_ratio: mean={sum(overlaps)/len(overlaps):.3f} min={min(overlaps):.3f} max={max(overlaps):.3f}")
    if confidences:
        print(f"  confidence: mean={sum(confidences)/len(confidences):.3f} min={min(confidences):.3f} max={max(confidences):.3f}")
    print()
