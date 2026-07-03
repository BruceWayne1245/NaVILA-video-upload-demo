"""Render route-memory diagnostic frames captured by
round_trip_eval.py's --capture_route_memory_diagnostic_frames.

For each captured frame (~4 per episode, sampled at fixed fractions of
return-journey progress remaining -- see
route_memory_agent.diagnostic_frame_thresholds_to_fire), produces:

1. An occupancy-map overview: the episode's USD floor-slice occupancy image
   (from --topdown_route_map) with the robot's world position + heading, every
   recorded anchor's world position, and the actual world-projected footprint
   of both the current local map and every anchor's local map drawn on top.
2. A clean scatter of the current local map alone (no overlay).
3. A clean scatter of each anchor's local map alone (generated once per anchor
   and reused across frames, since anchor maps are static).
4. A current-vs-every-anchor ICP match plot (reuses
   plot_anchor_match_diagnostics.py's rendering), computed fresh here against
   *every* recorded anchor, not just whichever one the live backend selected.

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


def _draw_overview(topdown_png_path: str, meta: dict, frame: dict, out_path: str) -> None:
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

    # Each anchor's own local map footprint (world-projected), cyan dots, plus a labeled marker.
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
        ax, ay = anchor["world_pose"][:2]
        apx, apy = world_to_pixel((ax, ay), meta)
        if 0 <= apx < image.shape[1] and 0 <= apy < image.shape[0]:
            cv2.circle(image, (apx, apy), 5, (0, 220, 255), -1, lineType=cv2.LINE_AA)
            cv2.circle(image, (apx, apy), 6, (20, 20, 20), 1, lineType=cv2.LINE_AA)
            cv2.putText(image, f"A{anchor['index']}", (apx + 8, apy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(image, f"A{anchor['index']}", (apx + 8, apy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 255), 1, cv2.LINE_AA)

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
    for i, (color, label) in enumerate(legend):
        y = 20 + i * 20
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

    occupancy_path = os.path.join(result_dir, "route_maps", f"output_{episode_output_id}_occupancy.png")
    meta_path = os.path.join(result_dir, "route_maps", f"output_{episode_output_id}_map_meta.json")
    have_overview = os.path.exists(occupancy_path) and os.path.exists(meta_path)
    meta = json.load(open(meta_path)) if have_overview else None

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
            _draw_overview(occupancy_path, meta, frame, os.path.join(frame_dir, "overview_map.png"))

        current_points = frame.get("current_local_map_points_body")
        _plot_clean_points(current_points, f"current local map (step {step})",
                            os.path.join(frame_dir, "current_local_map.png"))

        current_arr = np.asarray(current_points, dtype=np.float32) if current_points else None
        for anchor in frame["anchors"]:
            idx = anchor["index"]
            anchor_points = anchor.get("local_map_points_body")
            if idx not in rendered_anchors:
                _plot_clean_points(anchor_points, f"anchor {idx} local map",
                                    os.path.join(anchors_dir, f"anchor{idx}_local_map.png"))
                rendered_anchors.add(idx)
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
