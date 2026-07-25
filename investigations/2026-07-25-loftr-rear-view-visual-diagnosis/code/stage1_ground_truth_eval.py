#!/usr/bin/env python3
"""Rigorous, vision-independent Stage-1 (camera-pairing selection) evaluation.

Ground truth for "which of the 4 combos looks toward the same place" is
computed PURELY from oracle position/orientation data -- never from any
LoFTR match, RANSAC fit, or bearing-error computation. This is the method
error the user flagged: this session's earlier "selector accuracy" numbers
used bearing-error-<=30-deg as the correctness label, which conflates
Stage 1 (picked the right camera pairing) with Stage 2 (computed the
precise angle correctly given that pairing) -- a combo can be the
genuinely-correct pairing (real overlap) while its RANSAC-solved rotation
is still off by >30 deg (confirmed today on cases with 500-1300+ inliers).
This script re-does the evaluation with a clean, independent ground truth.

Ground truth construction (pure geometry, no matching):
  A rigid body's REAR camera is, by the simulator's fixed extrinsics
  (verified numerically this session: relative rotation 179.97 deg),
  exactly 180 deg rotated from its FRONT camera in the body frame. So each
  view's WORLD heading is just the body's own world yaw (+180 deg for the
  rear view). For a candidate pairing (anchor_view, current_view), define
  its "alignment angle" as the absolute angular difference between the two
  views' world headings (0 = pointing the same way in the world, most
  likely to share overlapping content at short range; 180 = pointing
  opposite ways). The combo with the SMALLEST alignment angle is the
  ground-truth-predicted correct pairing.

  This is deliberately independent of position: alignment angle alone
  predicts "if these two cameras are close enough together, which pairing
  would see the same place." Distance is handled separately as the
  near/far split, per the user's request, since at long range even a
  perfectly-aligned pairing may not have real overlap.

Near/far split: straight-line distance between anchor and current body
positions (oracle ground truth), reported at a couple of thresholds for
transparency.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
sys.path.insert(0, os.path.join(BENCH, "scripts"))

from route_memory_agent import world_pose_7_to_2d  # noqa: E402

RUN_TAG = "reliability_v11_decision_shadow_rgbd_100ep_20260724"


def result_dir(ep: int) -> str:
    return (
        f"{BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_"
        f"2024-09-25_23-22-02_{RUN_TAG}_ep{ep}/icp_replay_dataset"
    )


def load_anchor_pose2d(ep: int, anchor_idx: int):
    with open(os.path.join(result_dir(ep), "anchors.json")) as f:
        data = json.load(f)
    for a in data["anchors"]:
        if int(a["index"]) == anchor_idx:
            return world_pose_7_to_2d(a["world_pose"])
    return None


def load_step_pose2d(ep: int, step: int):
    path = os.path.join(result_dir(ep), "steps", f"frame_step{step:06d}.json")
    try:
        with open(path) as f:
            frame = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return world_pose_7_to_2d(frame["robot_world_pose"])


def angdiff_unsigned(a_deg, b_deg):
    """Unsigned angular difference in [0, 180]."""
    d = abs(math.degrees(math.atan2(
        math.sin(math.radians(a_deg - b_deg)), math.cos(math.radians(a_deg - b_deg))
    )))
    return d


def ground_truth_best_combo(anchor_pose2d, current_pose2d):
    """Returns (best_combo_name, dict of all 4 alignment angles, position_distance).
    Pure geometry -- no vision, no matching, no bearing-error computation."""
    ax, ay, ayaw = anchor_pose2d
    cx, cy, cyaw = current_pose2d
    ayaw_deg = math.degrees(ayaw)
    cyaw_deg = math.degrees(cyaw)

    views = {
        "anchorFront": ayaw_deg,
        "anchorRear": ayaw_deg + 180.0,
        "currentFront": cyaw_deg,
        "currentRear": cyaw_deg + 180.0,
    }
    combos = {
        "anchorFront_currentFront": angdiff_unsigned(views["anchorFront"], views["currentFront"]),
        "anchorFront_currentRear": angdiff_unsigned(views["anchorFront"], views["currentRear"]),
        "anchorRear_currentFront": angdiff_unsigned(views["anchorRear"], views["currentFront"]),
        "anchorRear_currentRear": angdiff_unsigned(views["anchorRear"], views["currentRear"]),
    }
    best = min(combos, key=lambda k: combos[k])
    distance = math.hypot(cx - ax, cy - ay)
    return best, combos, distance


def main():
    with open(os.path.join(os.path.dirname(__file__), "candidate_reachability_results.json")) as f:
        episodes = json.load(f)

    records = []
    for ep_entry in episodes:
        ep, anchor_idx = ep_entry["episode"], ep_entry["anchor"]
        anchor_pose2d = load_anchor_pose2d(ep, anchor_idx)
        if anchor_pose2d is None:
            continue
        for s in ep_entry["steps"]:
            if not s["confidently_wrong"]:
                continue
            step = s["step"]
            cur_pose2d = load_step_pose2d(ep, step)
            if cur_pose2d is None:
                continue
            best, combos, distance = ground_truth_best_combo(anchor_pose2d, cur_pose2d)
            records.append({
                "episode": ep, "anchor": anchor_idx, "step": step,
                "distance": distance, "gt_best_combo": best, "alignment_angles": combos,
            })

    with open(os.path.join(os.path.dirname(__file__), "stage1_ground_truth.json"), "w") as f:
        json.dump(records, f, indent=2)

    dists = np.array([r["distance"] for r in records])
    print(f"n={len(records)}")
    print(f"distance distribution: min={dists.min():.2f} p25={np.percentile(dists,25):.2f} "
          f"median={np.median(dists):.2f} p75={np.percentile(dists,75):.2f} max={dists.max():.2f}")

    # report the ground-truth best combo's own alignment angle -- a sanity
    # check that "best" really is well-aligned (near 0) vs. just "least bad"
    best_angles = np.array([r["alignment_angles"][r["gt_best_combo"]] for r in records])
    print(f"\nGT-best-combo's own alignment angle (0=perfectly parallel headings): "
          f"median={np.median(best_angles):.1f} deg, p75={np.percentile(best_angles,75):.1f} deg, "
          f"max={best_angles.max():.1f} deg")
    print(f"fraction with GT-best alignment <= 20 deg (clearly one dominant direction): "
          f"{(best_angles<=20).mean()*100:.1f}%")
    print(f"fraction with GT-best alignment <= 45 deg: {(best_angles<=45).mean()*100:.1f}%")


if __name__ == "__main__":
    main()
