#!/usr/bin/env python3
"""Render all 4 camera-pairing combos for 10 cases where GT distance < 1m
(genuinely close, real overlap should be easy) but the match-count selector
still picked the wrong combo -- from the representative (all-676-anchor)
dataset, one case per distinct episode for diversity.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
sys.path.insert(0, os.path.join(BENCH, "scripts"))

import relocalization as reloc  # noqa: E402

RUN_TAG = "reliability_v11_decision_shadow_rgbd_100ep_20260724"
OUT_DIR = os.path.join(os.path.dirname(__file__), "wrong_pick_under1m_grids")
os.makedirs(OUT_DIR, exist_ok=True)


def result_dir(ep: int) -> str:
    return (
        f"{BENCH}/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_"
        f"2024-09-25_23-22-02_{RUN_TAG}_ep{ep}/icp_replay_dataset"
    )


def load_npz(path):
    with np.load(path) as d:
        return {k: d[k] for k in d.files}


def render_case(idx: int, rec: dict):
    ep, anchor_idx, step = rec["episode"], rec["anchor"], rec["step"]
    anchor_desc = load_npz(os.path.join(result_dir(ep), "anchor_rgbd", f"anchor{anchor_idx:03d}.npz"))
    current_desc = load_npz(os.path.join(result_dir(ep), "rgbd", f"rgbd_step{step:06d}.npz"))

    anchor_front = anchor_desc
    anchor_rear = reloc.build_rear_view_descriptor(anchor_desc)
    current_front = current_desc
    current_rear = reloc.build_rear_view_descriptor(current_desc)

    combo_views = {
        "anchorFront_currentFront": (anchor_front, current_front),
        "anchorFront_currentRear": (anchor_front, current_rear),
        "anchorRear_currentFront": (anchor_rear, current_front),
        "anchorRear_currentRear": (anchor_rear, current_rear),
    }
    combo_labels = {
        "anchorFront_currentFront": "anchor-FRONT | current-FRONT",
        "anchorFront_currentRear": "anchor-FRONT | current-REAR",
        "anchorRear_currentFront": "anchor-REAR | current-FRONT",
        "anchorRear_currentRear": "anchor-REAR | current-REAR",
    }

    gt_combo = rec["gt_best_combo"]
    picked_combo = rec["match_count_pick"]

    fig, axes = plt.subplots(4, 2, figsize=(11, 20))
    for row, combo_key in enumerate(combo_views.keys()):
        a_view, c_view = combo_views[combo_key]
        label = combo_labels[combo_key]
        tag = ""
        if combo_key == gt_combo:
            tag += "  [GROUND TRUTH]"
        if combo_key == picked_combo:
            tag += "  [ALGORITHM PICKED]"
        axes[row, 0].imshow(np.asarray(a_view["rgb"])[:, :, :3])
        axes[row, 0].axis("off")
        axes[row, 1].imshow(np.asarray(c_view["rgb"])[:, :, :3])
        axes[row, 1].axis("off")
        axes[row, 0].set_title(f"{label}{tag}  (anchor side)", fontsize=10)
        axes[row, 1].set_title("(current side)", fontsize=10)

    fig.suptitle(
        f"Case {idx}: ep{ep} anchor{anchor_idx} step{step}  |  GT distance={rec['gt_distance']:.3f}m\n"
        f"GT best combo (pure geometry) = {gt_combo}   |   match-count selector picked = {picked_combo}\n"
        f"(rows top-to-bottom: FF, FR, RF, RR camera pairing combos)",
        fontsize=12,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    out_path = os.path.join(OUT_DIR, f"case{idx:02d}_ep{ep}_anchor{anchor_idx}_step{step}.png")
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    with open(os.path.join(os.path.dirname(__file__), "wrong_pick_under1m_selection.json")) as f:
        selection = json.load(f)
    for i, rec in enumerate(selection, start=1):
        try:
            render_case(i, rec)
        except Exception as exc:
            print(f"ERROR case {i} ep{rec['episode']} anchor{rec['anchor']} step{rec['step']}: {exc}")


if __name__ == "__main__":
    main()
