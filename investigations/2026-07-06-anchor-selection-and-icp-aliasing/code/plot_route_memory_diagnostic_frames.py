"""Render route-memory diagnostic frames captured by
round_trip_eval.py's --capture_route_memory_diagnostic_frames.

For each captured frame (~4 per episode, sampled at fixed fractions of
return-journey progress remaining -- see
route_memory_agent.diagnostic_frame_thresholds_to_fire), produces:

1. An occupancy-map overview: the episode's route_maps/output_*_routes.png
   overlay (reference path, outbound/return trajectories, start/goal/final and
   anchor markers -- falls back to the bare occupancy.png if routes.png isn't
   present) with the robot's world position + heading and the actual
   world-projected footprint of both the current local map and every anchor's
   local map drawn on top.
2. A clean scatter of the current local map alone (no overlay).
3. A clean scatter of each anchor's local map alone (generated once per anchor
   and reused across frames, since anchor maps are static).
4. A current-vs-every-anchor ICP match plot (reuses
   plot_anchor_match_diagnostics.py's rendering), computed fresh here against
   *every* recorded anchor, not just whichever one the live backend selected.
5. A current-vs-every-anchor Scan Context match plot: the polar-grid descriptor
   comparison (build_scan_context + column_shift_search_with_region) this
   project's scan_context backend actually runs, distinct from #4's from-scratch
   ICP sweep.

Pure numpy/matplotlib/cv2 -- no Isaac Sim dependency, run this after a batch
with --capture_route_memory_diagnostic_frames --topdown_route_map.

Run with:
    python3 scripts/plot_route_memory_diagnostic_frames.py \
        --result_dir eval_results/round_trip_..._epNNN \
        --episode_output_id 280
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from relocalization import build_local_map_match_snapshot, icp_rigid_transform_2d
from plot_anchor_match_diagnostics import _plot_one_match
from scan_context import (
    build_scan_context,
    column_shift_search_with_region,
    largest_connected_agreement_mask,
    shift_to_yaw_rad,
)
from topdown_route_map import world_to_pixel

YAW_SEEDS_DEG = list(range(-180, 180, 15))


def _quat_wxyz_to_yaw(quat_wxyz) -> float:
    w, x, y, z = [float(v) for v in quat_wxyz]
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _rotation_2d(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.asarray([[c, -s], [s, c]], dtype=np.float32)


def _body_points_to_world(points_body, world_pose) -> np.ndarray:
    points_body = np.asarray(points_body, dtype=np.float32)
    if points_body.size == 0:
        return points_body.reshape(0, 2)
    position = np.asarray(world_pose[:2], dtype=np.float32)
    yaw = _quat_wxyz_to_yaw(world_pose[3:7])
    return points_body[:, :2] @ _rotation_2d(yaw).T + position


def _best_icp_fit(anchor_points: np.ndarray, current_points: np.ndarray) -> dict | None:
    best = None
    for deg in YAW_SEEDS_DEG:
        result = icp_rigid_transform_2d(
            anchor_points, current_points, initial_theta=math.radians(deg),
            max_iterations=16, correspondence_threshold_m=0.45,
        )
        if result is None:
            continue
        score = (
            result["overlap_ratio"] * max(0.0, 1.0 - result["median_residual_m"] / 0.45)
            * math.sqrt(max(1, result["inlier_count"]))
        )
        if best is None or score > best[0]:
            best = (score, result)
    return best[1] if best is not None else None


def _plot_scan_context_match(
    current_xyz: np.ndarray,
    anchor_xyz: np.ndarray,
    anchor_idx: int,
    step: int,
    out_path: str,
    min_similarity: float = 0.2,
    min_connected_region_cells: int = 3,
) -> None:
    """Render the Scan Context descriptor comparison itself -- distinct from
    _best_icp_fit's from-scratch ICP sweep above, this is the polar-grid
    similarity + connected-region computation
    relocalization.py::scan_context_anchor_relocalization actually runs to
    pick an anchor's *identity*, before any ICP refinement ever happens.

    Two panels: (left) the two descriptor grids overlaid, with the winning
    connected-agreement region outlined; (right) a coarse point-cloud
    alignment using only Scan Context's own implied yaw, no translation --
    Scan Context alone never estimates one, unlike match_vs_anchor{idx}.png's
    ICP-refined pose.

    ``min_similarity``/``min_connected_region_cells`` mirror
    scan_context_anchor_relocalization's own defaults, annotated here only to
    show whether this anchor would individually clear them -- the third
    production gate (margin over the runner-up anchor) needs every candidate
    at once and isn't reproduced here, since this plots one anchor at a time.
    """
    current_sc = build_scan_context(current_xyz)
    anchor_sc = build_scan_context(anchor_xyz)
    similarity, shift, region_size = column_shift_search_with_region(current_sc, anchor_sc)
    mask = largest_connected_agreement_mask(current_sc, anchor_sc, shift)
    shifted_anchor_sc = np.roll(anchor_sc, shift, axis=1)
    yaw = shift_to_yaw_rad(shift, current_sc.shape[1])

    fig, (ax_grid, ax_points) = plt.subplots(1, 2, figsize=(12, 6))

    ax_grid.imshow(np.maximum(current_sc, shifted_anchor_sc), origin="lower", aspect="auto", cmap="viridis")
    region_rows, region_cols = np.where(mask)
    ax_grid.scatter(
        region_cols, region_rows, s=14, facecolors="none", edgecolors="red",
        linewidths=1.2, label=f"largest connected region (n={region_size})",
    )
    ax_grid.set_title("Scan Context grids: max(current, anchor rolled by best shift)", fontsize=8.5)
    ax_grid.set_xlabel("sector")
    ax_grid.set_ylabel("ring")
    ax_grid.legend(fontsize=7, loc="upper right")

    current_xy = np.asarray(current_xyz, dtype=np.float32)[:, :2]
    anchor_xy = np.asarray(anchor_xyz, dtype=np.float32)[:, :2]
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.asarray([[c, -s], [s, c]], dtype=np.float32)
    anchor_rotated = anchor_xy @ rotation.T
    ax_points.scatter(current_xy[:, 0], current_xy[:, 1], s=8, c="#1f77b4", alpha=0.7,
                       label=f"current local map (n={len(current_xy)})")
    ax_points.scatter(anchor_rotated[:, 0], anchor_rotated[:, 1], s=8, c="#ff7f0e", alpha=0.5,
                       label=f"anchor, yaw-only align (n={len(anchor_rotated)})")
    ax_points.scatter([0], [0], s=90, c="#2ca02c", marker="^", zorder=5, label="robot origin")
    ax_points.set_title("Coarse yaw-only alignment (no translation)", fontsize=8.5)
    ax_points.set_xlabel("x (m, body frame)")
    ax_points.set_ylabel("y (m, body frame)")
    ax_points.set_aspect("equal", adjustable="datalim")
    ax_points.legend(fontsize=7, loc="best")
    ax_points.grid(True, alpha=0.25)

    passes_gates = similarity >= min_similarity and region_size >= min_connected_region_cells
    fig.suptitle(
        f"anchor {anchor_idx}  |  backend=scan_context  |  step={step}\n"
        f"similarity={similarity:.2f}  region_size={region_size}  implied_yaw={math.degrees(yaw):.1f} deg  "
        f"clears_similarity+region_gates={passes_gates}",
        fontsize=9,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _draw_overview(
    topdown_png_path: str, meta: dict, frame: dict, out_path: str, legend_y_start: int = 20,
) -> None:
    image = cv2.imread(topdown_png_path)
    if image is None:
        raise FileNotFoundError(f"Could not read occupancy image: {topdown_png_path}")

    robot_pose = frame["robot_world_pose"]
    robot_xy = robot_pose[:2]
    robot_yaw = _quat_wxyz_to_yaw(robot_pose[3:7])

    # Current local map footprint (world-projected), orange dots.
    current_points = frame.get("current_local_map_points_body")
    if current_points:
        world_pts = _body_points_to_world(current_points, robot_pose)
        for x, y in world_pts:
            px, py = world_to_pixel((x, y), meta)
            if 0 <= px < image.shape[1] and 0 <= py < image.shape[0]:
                cv2.circle(image, (px, py), 1, (0, 140, 255), -1, lineType=cv2.LINE_AA)

    # Each anchor's own local map footprint (world-projected), cyan dots. Anchor
    # position + "A{idx}" label are NOT drawn here -- when the base image is
    # routes.png (render_route_overlay), those markers are already present in
    # the same color; re-drawing them here would just duplicate/clutter.
    for anchor in frame["anchors"]:
        if anchor["world_pose"] is None:
            continue
        anchor_points = anchor.get("local_map_points_body")
        if anchor_points:
            world_pts = _body_points_to_world(anchor_points, anchor["world_pose"])
            for x, y in world_pts:
                px, py = world_to_pixel((x, y), meta)
                if 0 <= px < image.shape[1] and 0 <= py < image.shape[0]:
                    cv2.circle(image, (px, py), 1, (255, 200, 0), -1, lineType=cv2.LINE_AA)

    # Robot marker + heading arrow.
    rpx, rpy = world_to_pixel(robot_xy, meta)
    tip_world = (robot_xy[0] + 0.6 * math.cos(robot_yaw), robot_xy[1] + 0.6 * math.sin(robot_yaw))
    tpx, tpy = world_to_pixel(tip_world, meta)
    cv2.arrowedLine(image, (rpx, rpy), (tpx, tpy), (35, 35, 230), 2, tipLength=0.4, line_type=cv2.LINE_AA)
    cv2.circle(image, (rpx, rpy), 6, (35, 35, 230), -1, lineType=cv2.LINE_AA)
    cv2.circle(image, (rpx, rpy), 7, (20, 20, 20), 1, lineType=cv2.LINE_AA)

    legend = [
        ((35, 35, 230), "robot (pos + heading)"),
        ((0, 220, 255), "anchor position"),
        ((0, 140, 255), "current local map"),
        ((255, 200, 0), "anchor local map"),
    ]
    # Small maps (this project's occupancy images are often only ~250x300 px)
    # pack real scene content (LiDAR dots, anchor labels) right where the
    # top-left legend goes, on top of both this legend and routes.png's own --
    # a translucent backing plate keeps this legend legible regardless of
    # what's underneath, without needing to know the room layout in advance.
    legend_box_y0 = max(0, legend_y_start - 14)
    legend_box_y1 = min(image.shape[0], legend_y_start + len(legend) * 20 + 2)
    legend_box_x1 = min(image.shape[1], 190)
    if legend_box_y1 > legend_box_y0:
        overlay = image.copy()
        cv2.rectangle(overlay, (6, legend_box_y0), (legend_box_x1, legend_box_y1), (255, 255, 255), -1)
        cv2.addWeighted(overlay, 0.75, image, 0.25, 0, dst=image)
    for i, (color, label) in enumerate(legend):
        y = legend_y_start + i * 20
        cv2.line(image, (12, y), (36, y), color, 4, cv2.LINE_AA)
        cv2.putText(image, label, (44, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)


def _plot_clean_points(points_body, title: str, out_path: str) -> None:
    points_body = np.asarray(points_body, dtype=np.float32) if points_body else np.zeros((0, 2), dtype=np.float32)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(points_body[:, 0], points_body[:, 1], s=10, c="#1f77b4")
    ax.scatter([0], [0], s=90, c="#2ca02c", marker="^", zorder=5, label="robot/anchor origin")
    ax.set_title(f"{title} (n={len(points_body)})", fontsize=10)
    ax.set_xlabel("x (m, body frame)")
    ax.set_ylabel("y (m, body frame)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def render_diagnostic_frames(result_dir: str, episode_output_id: int, output_dir: str | None) -> None:
    frames_dir = os.path.join(result_dir, "route_memory_diagnostic_frames")
    frame_paths = sorted(glob.glob(os.path.join(frames_dir, "frame_step*.json")))
    if not frame_paths:
        raise SystemExit(f"No diagnostic frames found under {frames_dir}")

    # Prefer routes.png (render_route_overlay: reference path, outbound/return
    # dashed trajectories, start/goal/final markers, anchor markers already
    # drawn) over the bare occupancy.png -- routes.png only exists once
    # save_topdown_route_map runs at episode end, so fall back gracefully for
    # older/incomplete runs.
    routes_path = os.path.join(result_dir, "route_maps", f"output_{episode_output_id}_routes.png")
    occupancy_path = os.path.join(result_dir, "route_maps", f"output_{episode_output_id}_occupancy.png")
    meta_path = os.path.join(result_dir, "route_maps", f"output_{episode_output_id}_map_meta.json")
    using_routes_png = os.path.exists(routes_path)
    base_map_path = routes_path if using_routes_png else occupancy_path
    have_overview = os.path.exists(base_map_path) and os.path.exists(meta_path)
    meta = json.load(open(meta_path)) if have_overview else None
    # routes.png already has its own legend baked in at the same top-left
    # corner (render_route_overlay, legend_x=12, legend_y=20, 5 items) --
    # start this overview's legend below it instead of overlapping.
    legend_y_start = 120 if using_routes_png else 20

    if output_dir is None:
        output_dir = os.path.join(result_dir, "route_memory_diagnostic_plots")
    anchors_dir = os.path.join(output_dir, "anchors")
    os.makedirs(anchors_dir, exist_ok=True)
    rendered_anchors = set()

    for frame_path in frame_paths:
        with open(frame_path) as f:
            frame = json.load(f)
        step = frame["step"]
        frame_dir = os.path.join(output_dir, f"step{step:06d}")
        os.makedirs(frame_dir, exist_ok=True)

        if have_overview:
            _draw_overview(
                base_map_path, meta, frame, os.path.join(frame_dir, "overview_map.png"),
                legend_y_start=legend_y_start,
            )

        current_points = frame.get("current_local_map_points_body")
        _plot_clean_points(current_points, f"current local map (step {step})",
                            os.path.join(frame_dir, "current_local_map.png"))

        current_arr = np.asarray(current_points, dtype=np.float32) if current_points else None
        current_xyz = frame.get("current_local_map_points_xyz_body")
        current_xyz_arr = np.asarray(current_xyz, dtype=np.float32) if current_xyz else None
        for anchor in frame["anchors"]:
            idx = anchor["index"]
            anchor_points = anchor.get("local_map_points_body")
            if idx not in rendered_anchors:
                _plot_clean_points(anchor_points, f"anchor {idx} local map",
                                    os.path.join(anchors_dir, f"anchor{idx}_local_map.png"))
                rendered_anchors.add(idx)

            # Scan Context match (polar-grid descriptor comparison), independent
            # of the ICP block below -- guarded the same >= 12 point convention
            # used by scan_context_anchor_relocalization itself. Only available
            # if the frame was captured after the 2026-07-04 xyz-field addition.
            anchor_xyz = anchor.get("local_map_points_xyz_body")
            if (
                anchor_xyz and current_xyz_arr is not None and len(current_xyz_arr) >= 12
                and len(anchor_xyz) >= 12
            ):
                _plot_scan_context_match(
                    current_xyz_arr, np.asarray(anchor_xyz, dtype=np.float32), idx, step,
                    os.path.join(frame_dir, f"scan_context_vs_anchor{idx}.png"),
                )

            if not anchor_points or current_arr is None or len(current_arr) < 12:
                continue
            anchor_arr = np.asarray(anchor_points, dtype=np.float32)
            if len(anchor_arr) < 12:
                continue
            fit = _best_icp_fit(anchor_arr, current_arr)
            if fit is None:
                continue
            snapshot = build_local_map_match_snapshot(anchor_arr, current_arr, fit["theta"], fit["translation"])
            record = {
                "anchor_index": idx,
                "attempt": step,
                "matcher_backend": "offline_icp_all_anchors",
                "overlap_ratio": fit["overlap_ratio"],
                "median_residual_m": fit["median_residual_m"],
                "confidence": min(1.0, fit["overlap_ratio"] * max(0.0, 1.0 - fit["median_residual_m"] / 0.45)),
                "estimated_anchor_dtheta_deg": math.degrees(fit["theta"]),
                "estimated_bearing_to_anchor_deg": math.degrees(math.atan2(fit["translation"][1], fit["translation"][0])),
                "estimated_distance_to_anchor_m": float(np.hypot(*fit["translation"])),
                "match_snapshot": snapshot,
            }
            _plot_one_match(record, "offline_all_anchors", os.path.join(frame_dir, f"match_vs_anchor{idx}.png"))

        print(f"step {step}: rendered overview + current map + {len(frame['anchors'])} anchor matches -> {frame_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--result_dir", required=True, help="Episode result_dir (e.g. eval_results/round_trip_..._epNNN).")
    parser.add_argument("--episode_output_id", type=int, required=True, help="Episode output id, matching route_maps/output_<id>_*.")
    parser.add_argument("--output_dir", default=None, help="Default: <result_dir>/route_memory_diagnostic_plots/")
    args = parser.parse_args()
    render_diagnostic_frames(args.result_dir, args.episode_output_id, args.output_dir)


if __name__ == "__main__":
    main()
