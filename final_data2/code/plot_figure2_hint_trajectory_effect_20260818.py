#!/usr/bin/env python3
"""Figure 2 (revision) per investigations/数据补全/figure_spec.md: 1x4 return-trajectory
panels, baseline vs oracle_hint, on real top-down floor-slice maps extracted from each
scene's Matterport USD mesh (same extraction as build_topdown_maps.py / the 3x3 figure).

Episode set replaces ep 9 (return divergence smaller than its own outbound noise) with
ep 1006, giving all four panels outbound divergence == 0.000 m exactly (verified below
against final_data2/trajectory_divergence_outbound_baseline_vs_oracle_hint_20260818.csv).
"""
import csv
import glob
import json
import math
import os

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pxr import Usd, UsdGeom

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
FINAL2 = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/final_data2"
USD_ROOT = os.path.join(BENCH, "isaaclab_exts/omni.isaac.vlnce/assets/matterport_usd")
BASELINE_TAG = "pure_baseline_highsuccess100ep_chronological_first50_20260818"
ORACLE_TAG = "pure_oracle_hint_highsuccess100ep_20260811"
OUT_PDF = os.path.join(FINAL2, "figures", "hint_trajectory_effect.pdf")

# (episode_id, outcome-cell label) -- left-to-right order fixed by spec; panel 4
# (both fail, largest divergence) must stay rightmost, the caption calls it out.
PICKS = [
    ("500", "both succeed"),
    ("1153", "hint only"),
    ("1154", "baseline only"),
    ("1006", "both fail"),
]

BASELINE_COLOR = "#d95f02"
ORACLE_COLOR = "#1b6fd9"

RESOLUTION_M_PER_PX = 0.05
Z_MIN_ABOVE_FLOOR_M = 0.08
Z_MAX_ABOVE_FLOOR_M = 2.2
OBSTACLE_DILATION_PX = 2
MAX_SIZE_PX = 2400
NORMAL_FLOOR_THRESHOLD = 0.90
CROP_MARGIN_M = 1.0  # "small margin", not the whole floor plan (spec)


def load_tsv(path):
    with open(path) as f:
        return {r["episode_id"]: r for r in csv.DictReader(f, delimiter="\t")}


def find_traj_file(tag, episode_idx):
    pattern = os.path.join(
        BENCH, "eval_results",
        f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{tag}_ep{episode_idx}",
        "trajectories", "*.jsonl",
    )
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(pattern)
    return matches[0]


def load_positions(traj_file, phase=None):
    xs, ys, zs = [], [], []
    with open(traj_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if phase is not None and rec.get("phase") != phase:
                continue
            x, y, z = rec["position"]
            xs.append(x)
            ys.append(y)
            zs.append(z)
    return xs, ys, zs


# ---------- USD mesh extraction (same as build_topdown_maps.py) ----------

def scene_world_triangles(usd_path):
    stage = Usd.Stage.Open(usd_path)
    xform_cache = UsdGeom.XformCache()
    triangles = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points_value = mesh.GetPointsAttr().Get()
        points = np.asarray(points_value if points_value is not None else [], dtype=np.float32)
        if points.size == 0:
            continue
        counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get() or [], dtype=np.int32)
        indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get() or [], dtype=np.int32)
        if counts.size == 0 or indices.size == 0:
            continue

        transform = np.asarray(xform_cache.GetLocalToWorldTransform(prim), dtype=np.float64).T
        homog = np.concatenate([points.astype(np.float64), np.ones((points.shape[0], 1))], axis=1)
        world_points = (homog @ transform)[:, :3].astype(np.float32)

        cursor = 0
        for count in counts:
            face_indices = indices[cursor:cursor + int(count)]
            cursor += int(count)
            if face_indices.size < 3:
                continue
            for i in range(1, face_indices.size - 1):
                tri = world_points[[face_indices[0], face_indices[i], face_indices[i + 1]]]
                triangles.append(tri)
    return triangles


def triangle_is_floor(tri, floor_z, normal_floor_threshold):
    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    norm = float(np.linalg.norm(normal))
    if norm < 1e-6:
        return False
    normal = normal / norm
    mean_z = float(np.mean(tri[:, 2]))
    return abs(float(normal[2])) >= normal_floor_threshold and abs(mean_z - floor_z) <= 0.25


def world_to_pixel(x, y, meta):
    px = int(round((x - meta["min_x"]) / meta["resolution_m_per_px"]))
    py = int(round((meta["max_y"] - y) / meta["resolution_m_per_px"]))
    return px, py


def build_occupancy(scene_triangles, floor_z, min_x, max_x, min_y, max_y):
    resolution = RESOLUTION_M_PER_PX
    width = int(math.ceil((max_x - min_x) / resolution)) + 1
    height = int(math.ceil((max_y - min_y) / resolution)) + 1
    if max(width, height) > MAX_SIZE_PX:
        scale = float(max(width, height)) / float(MAX_SIZE_PX)
        resolution *= scale
        width = int(math.ceil((max_x - min_x) / resolution)) + 1
        height = int(math.ceil((max_y - min_y) / resolution)) + 1

    meta = {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y, "resolution_m_per_px": resolution}
    z_min = floor_z + Z_MIN_ABOVE_FLOOR_M
    z_max = floor_z + Z_MAX_ABOVE_FLOOR_M

    image = np.full((height, width, 3), 245, dtype=np.uint8)
    obstacle_layer = np.zeros((height, width), dtype=np.uint8)
    for tri in scene_triangles:
        if float(np.max(tri[:, 2])) < z_min or float(np.min(tri[:, 2])) > z_max:
            continue
        tri_xy = tri[:, :2]
        if (
            float(np.max(tri_xy[:, 0])) < min_x or float(np.min(tri_xy[:, 0])) > max_x
            or float(np.max(tri_xy[:, 1])) < min_y or float(np.min(tri_xy[:, 1])) > max_y
        ):
            continue
        if triangle_is_floor(tri, floor_z, NORMAL_FLOOR_THRESHOLD):
            continue
        pts = np.asarray([world_to_pixel(x, y, meta) for x, y in tri_xy], dtype=np.int32)
        pts[:, 0] = np.clip(pts[:, 0], 0, width - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, height - 1)
        cv2.fillPoly(obstacle_layer, [pts], 255)

    if OBSTACLE_DILATION_PX > 0:
        k = 2 * OBSTACLE_DILATION_PX + 1
        kernel = np.ones((k, k), dtype=np.uint8)
        obstacle_layer = cv2.dilate(obstacle_layer, kernel, iterations=1)

    image[obstacle_layer > 0] = (60, 60, 60)
    return image


# ---------- verify divergence numbers against the CSV before plotting ----------

def verify_divergence():
    expected = {
        "500": (0.000, 0.26, 0.43),
        "1153": (0.000, 3.99, 6.15),
        "1154": (0.000, 3.36, 7.28),
        "1006": (0.000, 6.54, 15.65),
    }
    outb = {r["episode_id"]: r for r in csv.DictReader(open(os.path.join(FINAL2, "trajectory_divergence_outbound_baseline_vs_oracle_hint_20260818.csv")))}
    ret = {r["episode_id"]: r for r in csv.DictReader(open(os.path.join(FINAL2, "trajectory_divergence_return_baseline_vs_oracle_hint_20260818.csv")))}
    for eid, (exp_outb, exp_mean, exp_max) in expected.items():
        got_outb = float(outb[eid]["mean_div_m"])
        got_mean = float(ret[eid]["mean_div_m"])
        got_max = float(ret[eid]["max_div_m"])
        assert abs(got_outb - exp_outb) < 1e-6, f"ep{eid} outbound div {got_outb} != {exp_outb}"
        assert abs(got_mean - exp_mean) < 0.01, f"ep{eid} return mean div {got_mean} != {exp_mean}"
        assert abs(got_max - exp_max) < 0.01, f"ep{eid} return max div {got_max} != {exp_max}"
    print("divergence values verified OK")


# ---------- main ----------

def main():
    verify_divergence()

    baseline_rows = load_tsv(os.path.join(FINAL2, f"{BASELINE_TAG}_matched50_full_results.tsv"))
    oracle_rows = load_tsv(os.path.join(FINAL2, f"{ORACLE_TAG}_matched50_full_results.tsv"))

    plt.rcParams.update({
        "font.size": 6,
        "pdf.fonttype": 42,  # embed as real text, not curves, in the PDF
        "ps.fonttype": 42,
    })

    fig, axes = plt.subplots(1, 4, figsize=(7.1, 2.05))
    fig.subplots_adjust(left=0.005, right=0.995, top=0.80, bottom=0.02, wspace=0.08)
    fig_w_in, fig_h_in = fig.get_size_inches()
    box = axes[0].get_position()
    target_ratio = (box.width * fig_w_in) / (box.height * fig_h_in)  # world dx/dy needed for a padding-free equal-aspect fit
    scene_tri_cache = {}

    for panel_idx, (ax, (eid, outcome_label)) in enumerate(zip(axes, PICKS)):
        b_row = baseline_rows[eid]
        o_row = oracle_rows[eid]
        episode_idx = b_row["episode_idx"]
        scene = b_row["scene"]

        b_traj = find_traj_file(BASELINE_TAG, episode_idx)
        o_traj = find_traj_file(ORACLE_TAG, episode_idx)

        bx_all, by_all, bz_all = load_positions(b_traj)
        bx, by, _ = load_positions(b_traj, "return")
        ox, oy, _ = load_positions(o_traj, "return")
        sx, sy, sz = bx_all[0], by_all[0], bz_all[0]

        all_x = bx + ox + [sx]
        all_y = by + oy + [sy]
        min_x, max_x = min(all_x) - CROP_MARGIN_M, max(all_x) + CROP_MARGIN_M
        min_y, max_y = min(all_y) - CROP_MARGIN_M, max(all_y) + CROP_MARGIN_M

        # Expand the world-coordinate crop (not just the plot view) to the
        # panel's target aspect ratio, so the extra space shows real floor
        # context instead of blank matplotlib background.
        cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
        dx, dy = max_x - min_x, max_y - min_y
        if dx / dy < target_ratio:
            dx = dy * target_ratio
        else:
            dy = dx / target_ratio
        min_x, max_x = cx - dx / 2, cx + dx / 2
        min_y, max_y = cy - dy / 2, cy + dy / 2

        if scene not in scene_tri_cache:
            usd_path = os.path.join(USD_ROOT, scene, f"{scene}.usd")
            print(f"loading USD mesh for scene {scene} ...")
            scene_tri_cache[scene] = scene_world_triangles(usd_path)
        occ_img = build_occupancy(scene_tri_cache[scene], sz, min_x, max_x, min_y, max_y)

        ax.imshow(occ_img, extent=(min_x, max_x, min_y, max_y), origin="upper", zorder=1)
        ax.plot(bx, by, color=BASELINE_COLOR, linewidth=1.0, linestyle="-", zorder=2)
        ax.plot(ox, oy, color=ORACLE_COLOR, linewidth=1.0, linestyle="--", zorder=3)
        ax.scatter([bx[0]], [by[0]], color=BASELINE_COLOR, marker="o", s=10, zorder=4, edgecolors="white", linewidths=0.4)
        ax.scatter([ox[0]], [oy[0]], color=ORACLE_COLOR, marker="s", s=10, zorder=4, edgecolors="white", linewidths=0.4)
        # star drawn last so it's never occluded by paths/start dots
        ax.scatter([sx], [sy], color="black", marker="*", s=60, zorder=5)

        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        ax.text(0.5, 1.14, outcome_label, transform=ax.transAxes, ha="center", va="bottom",
                fontsize=7, fontweight="bold")
        ax.text(0.5, 1.02, f"ep {eid}", transform=ax.transAxes, ha="center", va="bottom",
                fontsize=6)

        if panel_idx == 0:
            bar_len = 2.0
            x0 = min_x + CROP_MARGIN_M * 0.3
            y0 = min_y + CROP_MARGIN_M * 0.3
            ax.plot([x0, x0 + bar_len], [y0, y0], color="black", linewidth=1.2, zorder=6, solid_capstyle="butt")
            ax.text(x0 + bar_len / 2, y0 + (max_y - min_y) * 0.02, "2 m", ha="center", va="bottom",
                    fontsize=6.5, zorder=6)

    os.makedirs(os.path.dirname(OUT_PDF), exist_ok=True)
    fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.02)
    print("saved", OUT_PDF)

    png_path = OUT_PDF.replace(".pdf", "_preview.png")
    fig.savefig(png_path, dpi=200, bbox_inches="tight", pad_inches=0.02)
    print("saved", png_path)


if __name__ == "__main__":
    main()
